"""Качественный двухэтапный RAG.

    источники → пассажи (chunking)
             → этап 1: BM25 (Okapi) отбирает N кандидатов  (быстрый дешёвый фильтр)
             → этап 2: реранкер cohere/rerank-4-fast переупорядочивает по релевантности
             → диверсификация: лучший пассаж на источник, топ-K источников

Почему так: BM25 дёшев, но лексичен (не видит смысл и плохо связывает языки);
кросс-энкодер точен и мультиязычен, но дорог на больших корпусах. Связка
«дешёвый отбор → точный реранк» — классический production-RAG паттерн.

Мультиязычность: BM25 лексичен, поэтому русский запрос почти не набирает очков на
англоязычных документах. Чтобы англо- и русскоязычные источники честно сравнил
МУЛЬТИЯЗЫЧНЫЙ реранкер, на этапе отбора гарантируем минимум кандидатов на каждый
язык (см. _select_candidates). Каждый этап логируется — полная прозрачность.
"""
from config import Config
import bm25
import reranker


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """Разбить текст на перекрывающиеся пассажи по границам предложений/слов."""
    size = size or Config.RAG_CHUNK_SIZE
    overlap = overlap or Config.RAG_CHUNK_OVERLAP
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks, start = [], 0
    while start < len(text):
        end = start + size
        if end < len(text):
            window = text[start:end]
            brk = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if brk < size * 0.5:
                brk = window.rfind(" ")
            if brk > 0:
                end = start + brk + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _passages(sources) -> list[dict]:
    out = []
    for s in sources:
        body = f"{s.title}. {s.content or ''}".strip()
        for i, ch in enumerate(chunk_text(body)):
            out.append({"source": s, "chunk": i, "text": ch})
    return out


def _select_candidates(scored: list[dict], budget: int, min_per_lang: int) -> list[dict]:
    """Отобрать до `budget` кандидатов, ГАРАНТИРУЯ минимум на каждый язык.

    scored — результат bm25.rank (по исходному порядку). Сначала берём топ
    min_per_lang по BM25 из каждого языка (чтобы кросс-языковые источники дошли до
    реранкера), затем добиваем бюджет лучшими по общему счёту. Итог сортируем по счёту.
    """
    ranked = sorted(scored, key=lambda x: x["score"], reverse=True)
    if len(ranked) <= budget:
        return ranked

    by_lang: dict[str, list] = {}
    for x in ranked:
        by_lang.setdefault(x["lang"], []).append(x)

    selected, taken = [], set()
    # 1) квота на каждый язык
    for items in by_lang.values():
        for x in items[:min_per_lang]:
            if len(selected) >= budget:
                break
            if x["index"] not in taken:
                selected.append(x)
                taken.add(x["index"])
    # 2) добить бюджет лучшими по общему счёту
    for x in ranked:
        if len(selected) >= budget:
            break
        if x["index"] not in taken:
            selected.append(x)
            taken.add(x["index"])

    selected.sort(key=lambda x: x["score"], reverse=True)
    return selected


def retrieve(query, sources, top_k=6, candidates=None, use_rerank=True,
             per_source=1, min_per_lang=None):
    """Двухэтапный отбор контекста под запрос.

    Возвращает:
      {
        "items": [{source, passage, bm25_score, rerank_score, score, terms, lang}],  # по убыванию
        "stages": {passages, candidates, reranked, rerank_model, languages},
        "rerank_usage": {...}, "rerank_error": str|None
      }
    """
    candidates = candidates or Config.RERANK_CANDIDATES
    min_per_lang = Config.RETRIEVAL_MIN_PER_LANG if min_per_lang is None else min_per_lang
    passages = _passages(sources)
    stages = {"passages": len(passages), "candidates": 0, "reranked": False,
              "rerank_model": None, "languages": {}}
    if not passages:
        return {"items": [], "stages": stages, "rerank_usage": {}, "rerank_error": None}

    # ── Этап 1: BM25 по всем пассажам + языко-сбалансированный отбор кандидатов ─
    scored = bm25.rank(query, [p["text"] for p in passages], k1=Config.BM25_K1, b=Config.BM25_B)
    stages["languages"] = _lang_counts(scored)
    selected = _select_candidates(scored, candidates, min_per_lang)
    cand = []
    for x in selected:
        p = passages[x["index"]]
        cand.append({
            "source": p["source"], "passage": p["text"],
            "bm25_score": x["score"], "rerank_score": None,
            "terms": x["terms"], "lang": x["lang"],
        })
    stages["candidates"] = len(cand)

    # ── Этап 2: мультиязычный реранкер ───────────────────────────────────────
    rerank_usage, rerank_error = {}, None
    if use_rerank and reranker.available() and cand:
        rr = reranker.rerank(query, [c["passage"] for c in cand], top_n=len(cand))
        if rr["ok"]:
            reordered = []
            for res in rr["results"]:
                c = cand[res["index"]]
                c["rerank_score"] = res["score"]
                reordered.append(c)
            cand = reordered
            stages.update(reranked=True, rerank_model=rr["model"])
            rerank_usage = rr["usage"]
        else:
            rerank_error = rr["error"]

    for c in cand:
        c["score"] = c["rerank_score"] if c["rerank_score"] is not None else c["bm25_score"]

    # ── Диверсификация: лучший пассаж на источник, затем top_k источников ─────
    seen, diversified = {}, []
    for c in cand:
        sid = c["source"].id
        if seen.get(sid, 0) >= per_source:
            continue
        seen[sid] = seen.get(sid, 0) + 1
        diversified.append(c)
        if len(diversified) >= top_k:
            break

    return {"items": diversified, "stages": stages,
            "rerank_usage": rerank_usage, "rerank_error": rerank_error}


def _lang_counts(scored: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for x in scored:
        counts[x["lang"]] = counts.get(x["lang"], 0) + 1
    return counts
