"""Кросс-энкодер-реранкер второго этапа RAG.

Cohere rerank-4-fast через OpenRouter (OpenAI-совместимый шлюз).
Эндпоинт: POST {OPENAI_API_BASE}/rerank
  body: {"model", "query", "documents": [str], "top_n"}
  resp: {"results": [{"index", "relevance_score"}], "usage": {"search_units","cost"}}

Реранкер даёт релевантность запрос↔документ гораздо точнее, чем TF-IDF/косинус,
потому что смотрит на пару целиком (а не на пересечение мешков слов).
Деградирует мягко: при недоступности возвращает исходный порядок.
"""
import httpx
from config import Config


def available() -> bool:
    return bool(Config.RERANK_ENABLED and Config.OPENAI_API_KEY)


def rerank(query: str, documents: list[str], top_n: int | None = None) -> dict:
    """Переупорядочить documents по релевантности query.

    Возвращает dict:
      {
        "ok": bool,
        "results": [{"index": i, "score": float|None}],  # по убыванию релевантности
        "usage": {...}, "model": str, "error": str|None
      }
    Индексы в results указывают на позиции в исходном списке documents.
    """
    n = len(documents)
    passthrough = [{"index": i, "score": None} for i in range(n)]
    if n == 0 or not (query or "").strip():
        return {"ok": False, "results": passthrough, "usage": {}, "model": None,
                "error": "пустой запрос или документы"}
    if not available():
        return {"ok": False, "results": passthrough, "usage": {}, "model": None,
                "error": "реранкер отключён"}

    top_n = min(top_n or n, n)
    try:
        with httpx.Client(timeout=Config.RERANK_TIMEOUT) as client:
            resp = client.post(
                f"{Config.OPENAI_API_BASE}/rerank",
                headers={
                    "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.RERANK_MODEL,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "results": passthrough, "usage": {}, "model": None,
                "error": f"реранкер недоступен: {exc}"}

    results = []
    for item in data.get("results", []):
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < n:
            results.append({"index": idx, "score": item.get("relevance_score")})
    if not results:
        return {"ok": False, "results": passthrough, "usage": {}, "model": None,
                "error": "реранкер вернул пустой результат"}

    return {
        "ok": True,
        "results": results,
        "usage": data.get("usage", {}),
        "model": data.get("model") or Config.RERANK_MODEL,
        "error": None,
    }


def ping() -> dict:
    """Проверка доступности реранкера (для /api/health)."""
    r = rerank("nickel corrosion", ["Molybdenum reduces pitting in Ni-Cr-Mo.", "A cat sat on a mat."], top_n=2)
    return {"ok": r["ok"], "model": Config.RERANK_MODEL, "error": r.get("error")}
