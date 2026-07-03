"""Качественный двухэтапный RAG.

    источники → пассажи (chunking)
             → этап 1: TF-IDF отбирает N кандидатов  (быстрый дешёвый фильтр)
             → этап 2: реранкер cohere/rerank-4-fast переупорядочивает по релевантности
             → диверсификация: лучший пассаж на источник, топ-K источников

Почему так: TF-IDF дёшев, но грубоват; кросс-энкодер точен, но дорог на больших
корпусах. Связка «дешёвый отбор → точный реранк» — это классический production-RAG
паттерн: экономно (реранкер видит только N кандидатов) и качественно.
Каждый этап логируется -> полная прозрачность (не «чёрный ящик»).
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import Config
from retrieval import _tokenize, RU_STOP
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


def _tfidf_rank(query: str, texts: list[str], k: int) -> list[tuple[int, float, list[str]]]:
    """Топ-k пассажей по TF-IDF: (index, score, совпавшие_термины)."""
    corpus = texts + [query]
    try:
        vec = TfidfVectorizer(
            tokenizer=_tokenize, token_pattern=None, stop_words=RU_STOP,
            lowercase=True, min_df=1, ngram_range=(1, 2),
        )
        matrix = vec.fit_transform(corpus)
    except ValueError:
        return [(i, 0.0, []) for i in range(min(k, len(texts)))]

    doc_m, q = matrix[:-1], matrix[-1]
    sims = cosine_similarity(q, doc_m).ravel()
    names = np.array(vec.get_feature_names_out())
    q_arr = q.toarray().ravel()
    q_idx = set(np.nonzero(q_arr)[0])

    order = np.argsort(sims)[::-1][:k]
    ranked = []
    for i in order:
        d_arr = doc_m[i].toarray().ravel()
        shared = [j for j in q_idx if d_arr[j] > 0]
        shared.sort(key=lambda j: d_arr[j] * q_arr[j], reverse=True)
        ranked.append((int(i), round(float(sims[i]), 4), [str(names[j]) for j in shared[:6]]))
    return ranked


def retrieve(query, sources, top_k=6, candidates=None, use_rerank=True, per_source=1):
    """Двухэтапный отбор контекста под запрос.

    Возвращает:
      {
        "items": [{source, passage, tfidf_score, rerank_score, score, terms}],  # по убыванию
        "stages": {passages, candidates, reranked, rerank_model},
        "rerank_usage": {...}, "rerank_error": str|None
      }
    """
    candidates = candidates or Config.RERANK_CANDIDATES
    passages = _passages(sources)
    stages = {"passages": len(passages), "candidates": 0, "reranked": False, "rerank_model": None}
    if not passages:
        return {"items": [], "stages": stages, "rerank_usage": {}, "rerank_error": None}

    # ── Этап 1: TF-IDF отбор кандидатов ──────────────────────────────────────
    cand = []
    for idx, score, terms in _tfidf_rank(query, [p["text"] for p in passages], candidates):
        p = passages[idx]
        cand.append({
            "source": p["source"], "passage": p["text"],
            "tfidf_score": score, "rerank_score": None, "terms": terms,
        })
    stages["candidates"] = len(cand)

    # ── Этап 2: реранкер ─────────────────────────────────────────────────────
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
        c["score"] = c["rerank_score"] if c["rerank_score"] is not None else c["tfidf_score"]

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
