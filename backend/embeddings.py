"""Плотный (dense) ретривер на BAAI/bge-m3 через OpenRouter.

bge-m3 — компактная (568M) мультиязычная эмбеддинг-модель (100+ языков, вкл. русский),
что делает dense-поиск кросс-языковым уже на 1-м этапе: русский запрос семантически
близок к релевантному англоязычному документу (проверено: cos≈0.54).

Эмбеддинги берём через тот же OpenRouter-ключ (эндпоинт /embeddings) — без torch и
локальной модели: минимум ресурсов, ~$0.0000002 за запрос. При любой ошибке возвращаем
None -> rag.py мягко откатывается на BM25-only.
"""
import httpx
import numpy as np
from config import Config


def available() -> bool:
    return bool(Config.EMBED_ENABLED and Config.OPENAI_API_KEY)


def _embed_batch(texts: list[str], client: httpx.Client) -> list[list[float]] | None:
    resp = client.post(
        f"{Config.OPENAI_API_BASE}/embeddings",
        headers={
            "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": Config.EMBED_MODEL, "input": texts},
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if len(data) != len(texts):
        return None
    ordered = sorted(data, key=lambda x: x.get("index", 0))
    return [row["embedding"] for row in ordered]


def embed(texts: list[str]) -> list[list[float]] | None:
    """Вернуть эмбеддинги для texts (в том же порядке). None при недоступности/ошибке."""
    if not texts or not available():
        return None
    out: list[list[float]] = []
    try:
        with httpx.Client(timeout=Config.EMBED_TIMEOUT) as client:
            for i in range(0, len(texts), Config.EMBED_BATCH):
                batch = texts[i:i + Config.EMBED_BATCH]
                embs = _embed_batch(batch, client)
                if embs is None:
                    return None
                out.extend(embs)
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return out if len(out) == len(texts) else None


def cosine_scores(query_emb: list[float], doc_embs: list[list[float]]) -> list[float]:
    """Косинусная близость запроса к каждому документу (bge-m3 уже нормирован, но нормируем на всякий случай)."""
    q = np.asarray(query_emb, dtype=float)
    d = np.asarray(doc_embs, dtype=float)
    qn = q / (np.linalg.norm(q) or 1.0)
    dn = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-9)
    return (dn @ qn).tolist()


def ping() -> dict:
    """Проверка доступности эмбеддингов (для /api/health)."""
    try:
        embs = embed(["nickel corrosion", "коррозия никеля"])
        ok = bool(embs) and len(embs) == 2 and len(embs[0]) > 0
        return {"ok": ok, "model": Config.EMBED_MODEL, "dim": (len(embs[0]) if ok else None)}
    except Exception as e:  # noqa
        return {"ok": False, "model": Config.EMBED_MODEL, "error": str(e)[:200]}
