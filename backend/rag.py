"""Качественный гибридный RAG.

    источники → пассажи (chunking)
             → этап 1 (ГИБРИД): BM25 (лексика) + bge-m3 (dense, семантика)
                                 → слияние Reciprocal Rank Fusion (RRF)
             → этап 2: реранкер cohere/rerank-4-fast переупорядочивает по релевантности
             → диверсификация: лучший пассаж на источник, топ-K источников

Зачем гибрид: BM25 ловит точные термины (Ni-Cr-Mo, H2SO4), но лексичен и языково-силосен;
bge-m3 (мультиязычный) ловит СМЫСЛ и связывает языки (русский запрос ↔ англоязычный
источник) уже на 1-м этапе. RRF устойчиво объединяет два ранга без подгонки шкал.
Финальный кросс-энкодер-реранкер уточняет. Всё логируется — прозрачность.

Мягкая деградация: если эмбеддинги недоступны — откат на BM25-only (dense=False).
"""
from config import Config
import bm25
import embeddings
import reranker
from models import DocumentChunk


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
        source_kind = getattr(s, "retrieval_kind", "source")
        source_key = getattr(s, "retrieval_id", getattr(s, "id", None))
        if source_kind == "document":
            chunks = s.chunks.order_by(DocumentChunk.chunk_index.asc()).all()
            for chunk in chunks:
                text = " ".join(str(chunk.text or "").split()).strip()
                if not text:
                    continue
                prefix = " / ".join(filter(None, [
                    str(chunk.section_title or "").strip(),
                    f"page {chunk.page_ref}" if chunk.page_ref else None,
                ]))
                if prefix and prefix.lower() not in text[: min(len(text), len(prefix) + 40)].lower():
                    text = f"{prefix}. {text}"
                out.append({
                    "source": s,
                    "source_key": source_key,
                    "source_kind": source_kind,
                    "chunk": chunk.chunk_index,
                    "text": text,
                    "page_ref": chunk.page_ref,
                    "section_title": chunk.section_title,
                })
            if chunks:
                continue

        body = f"{s.title}. {s.content or ''}".strip()
        for i, ch in enumerate(chunk_text(body)):
            out.append({
                "source": s,
                "source_key": source_key,
                "source_kind": source_kind,
                "chunk": i,
                "text": ch,
                "page_ref": None,
                "section_title": None,
            })
    return out


def _ranks(scores: list[float]) -> list[int]:
    """1-based ранг каждого документа (лучший счёт → ранг 1). Тай-брейк по порядку."""
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranks = [0] * len(scores)
    for r, i in enumerate(order, start=1):
        ranks[i] = r
    return ranks


def _fuse(bm25_scores, dense_scores, k, w_bm, w_de):
    """Reciprocal Rank Fusion. Возвращает список hybrid-очков по индексам пассажей."""
    if dense_scores is None:
        return list(bm25_scores)  # откат: гибрид = BM25
    bm_rank = _ranks(bm25_scores)
    de_rank = _ranks(dense_scores)
    return [
        w_bm / (k + bm_rank[i]) + w_de / (k + de_rank[i])
        for i in range(len(bm25_scores))
    ]


def _select_candidates(scored: list[dict], budget: int, min_per_lang: int) -> list[dict]:
    """Отобрать до `budget` кандидатов, ГАРАНТИРУЯ минимум на каждый язык (safety net).

    Сортируем по гибридному счёту; берём топ min_per_lang из каждого языка (чтобы
    кросс-языковые источники дошли до реранкера даже при отказе dense), затем добиваем
    бюджет лучшими по общему счёту.
    """
    ranked = sorted(scored, key=lambda x: x["score"], reverse=True)
    if len(ranked) <= budget:
        return ranked

    by_lang: dict[str, list] = {}
    for x in ranked:
        by_lang.setdefault(x["lang"], []).append(x)

    selected, taken = [], set()
    for items in by_lang.values():
        for x in items[:min_per_lang]:
            if len(selected) >= budget:
                break
            if x["index"] not in taken:
                selected.append(x)
                taken.add(x["index"])
    for x in ranked:
        if len(selected) >= budget:
            break
        if x["index"] not in taken:
            selected.append(x)
            taken.add(x["index"])

    selected.sort(key=lambda x: x["score"], reverse=True)
    return selected


def retrieve(query, sources, top_k=6, candidates=None, use_rerank=True,
             use_dense=True, per_source=1, min_per_lang=None):
    """Гибридный двухэтапный отбор контекста под запрос.

    Возвращает:
      {
        "items": [{source, passage, bm25_score, dense_score, hybrid_score,
                   rerank_score, score, terms, lang}],  # по убыванию
        "stages": {passages, candidates, dense, fusion, reranked, rerank_model, languages},
        "rerank_usage": {...}, "rerank_error": str|None, "embed_usage": {...}
      }
    """
    candidates = candidates or Config.RERANK_CANDIDATES
    min_per_lang = Config.RETRIEVAL_MIN_PER_LANG if min_per_lang is None else min_per_lang
    passages = _passages(sources)
    stages = {"passages": len(passages), "candidates": 0, "dense": False,
              "fusion": "bm25", "reranked": False, "rerank_model": None, "languages": {}}
    if not passages:
        return {"items": [], "stages": stages, "rerank_usage": {}, "rerank_error": None}

    texts = [p["text"] for p in passages]

    # ── Этап 1a: BM25 (лексический) ──────────────────────────────────────────
    scored = bm25.rank(query, texts, k1=Config.BM25_K1, b=Config.BM25_B)
    bm25_scores = [x["score"] for x in scored]
    stages["languages"] = _lang_counts(scored)

    # ── Этап 1b: dense (bge-m3, семантический, мультиязычный) ─────────────────
    dense_scores = None
    if use_dense and embeddings.available():
        embs = embeddings.embed([query] + texts)
        if embs and len(embs) == len(texts) + 1:
            dense_scores = [round(v, 4) for v in embeddings.cosine_scores(embs[0], embs[1:])]
            stages["dense"] = True
            stages["fusion"] = "rrf"

    # ── Слияние RRF ──────────────────────────────────────────────────────────
    hybrid = _fuse(bm25_scores, dense_scores,
                   Config.HYBRID_RRF_K, Config.HYBRID_BM25_WEIGHT, Config.HYBRID_DENSE_WEIGHT)

    scored_h = [{
        "index": i, "score": hybrid[i],
        "bm25_score": bm25_scores[i],
        "dense_score": (dense_scores[i] if dense_scores else None),
        "terms": scored[i]["terms"], "lang": scored[i]["lang"],
    } for i in range(len(passages))]

    selected = _select_candidates(scored_h, candidates, min_per_lang)
    cand = []
    for x in selected:
        p = passages[x["index"]]
        cand.append({
            "source": p["source"], "passage": p["text"],
            "source_key": p.get("source_key"),
            "source_kind": p.get("source_kind"),
            "page_ref": p.get("page_ref"),
            "section_title": p.get("section_title"),
            "bm25_score": x["bm25_score"], "dense_score": x["dense_score"],
            "hybrid_score": round(x["score"], 6), "rerank_score": None,
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
        c["score"] = c["rerank_score"] if c["rerank_score"] is not None else c["hybrid_score"]

    # ── Диверсификация: лучший пассаж на источник, затем top_k источников ─────
    seen, diversified = {}, []
    for c in cand:
        sid = c.get("source_key") or getattr(c["source"], "retrieval_id", c["source"].id)
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
