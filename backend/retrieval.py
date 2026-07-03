"""Лёгкий интерпретируемый поиск по базе знаний на TF-IDF.

Почему TF-IDF, а не эмбеддинги:
  * работает локально, без обращений к внешним API -> экономия ресурсов;
  * полностью прозрачен -> можно показать, ПОЧЕМУ источник отобран
    (какие термины совпали с запросом и с каким весом);
  * этого достаточно, чтобы дать модели релевантный контекст под KPI.
"""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Русские + английские стоп-слова (материаловедческие тексты часто смешанные)
RU_STOP = """и в во не что он на я с со как а то все она так его но да ты к у же вы
за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли
если или быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они
тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под
будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем
чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над
больше тот через эти нас про всего них какая много разве три эту моя впрочем свою этой перед
иногда лучше чуть том нельзя такой им более всегда конечно всю между это при также""".split()


def _tokenize(text: str):
    # Слова длиной 2+, поддержка дефисов (Ni-based, high-entropy)
    return re.findall(r"[a-zA-Zа-яА-Я0-9][a-zA-Zа-яА-Я0-9\-]+", (text or "").lower())


def retrieve(query: str, sources: list, top_k: int = 6):
    """Отобрать top_k релевантных источников под запрос (KPI).

    sources: list[KnowledgeSource]
    Возвращает список dict: {source, score, terms} по убыванию релевантности.
    Если корпус мал/пуст — деградирует мягко (вернёт что есть).
    """
    if not sources:
        return []

    docs = [f"{s.title}. {s.content}" for s in sources]
    corpus = docs + [query]

    try:
        vec = TfidfVectorizer(
            tokenizer=_tokenize,
            token_pattern=None,
            stop_words=RU_STOP,
            lowercase=True,
            min_df=1,
            ngram_range=(1, 2),
        )
        matrix = vec.fit_transform(corpus)
    except ValueError:
        # Пустой словарь (например, только стоп-слова) — вернём все источники поровну
        return [{"source": s, "score": 0.0, "terms": []} for s in sources[:top_k]]

    doc_matrix = matrix[:-1]
    query_vec = matrix[-1]
    sims = cosine_similarity(query_vec, doc_matrix).ravel()

    feature_names = np.array(vec.get_feature_names_out())
    query_arr = query_vec.toarray().ravel()
    query_term_idx = set(np.nonzero(query_arr)[0])

    ranked = np.argsort(sims)[::-1][:top_k]
    results = []
    for i in ranked:
        doc_arr = doc_matrix[i].toarray().ravel()
        # Термины, которые есть и в запросе, и в документе — «почему совпало»
        shared = [j for j in query_term_idx if doc_arr[j] > 0]
        shared.sort(key=lambda j: doc_arr[j] * query_arr[j], reverse=True)
        terms = [str(feature_names[j]) for j in shared[:6]]
        results.append({
            "source": sources[i],
            "score": round(float(sims[i]), 4),
            "terms": terms,
        })
    return results
