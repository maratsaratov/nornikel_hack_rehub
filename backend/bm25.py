"""Okapi BM25 + мультиязычная (RU/EN) токенизация для 1-го этапа RAG.

BM25 — стандарт лексического ранжирования: в отличие от TF-IDF+cosine он учитывает
насыщение частоты терма (k1) и нормировку по длине документа (b), что даёт заметно
более качественный отбор кандидатов. Реализован без внешних зависимостей
(экономия ресурсов) и с покомпонентным вкладом термов -> сохраняется
интерпретируемость («какие термины совпали»).

Мультиязычность:
  * токенайзер понимает и кириллицу, и латиницу (материаловедческие тексты смешанные);
  * стоп-слова RU + EN, нормализация ё→е;
  * см. detect_lang() — язык пассажа; балансировку кандидатов по языкам делает rag.py,
    чтобы мультиязычный реранкер увидел и англо-, и русскоязычные источники.
"""
import re
import math
from collections import Counter

# Русские стоп-слова
RU_STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы
за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли
если или быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они
тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под
будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем
чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над
больше тот через эти нас про всего них какая много разве три эту моя впрочем свою этой перед
иногда лучше чуть том нельзя такой им более всегда конечно всю между это при также""".split())

# Английские стоп-слова (+ типовые «академические» филлеры, дающие шум в аннотациях)
EN_STOP = set("""a an the and or but if of at by for with about against between into through
during before after above below to from up down in out on off over under again further then
once here there all any both each few more most other some such no nor not only own same so
than too very can will just is are was were be been being have has had do does did this that
these those it its as we you they he she i our their your his her them us was were which who
whom whose what when where why how using used use based study studies paper papers show shown
shows results result method methods approach via due within also may can could would should
et al fig table""".split())

STOPWORDS = RU_STOP | EN_STOP

_TOKEN_RE = re.compile(r"[a-zа-я0-9][a-zа-я0-9\-]+")
_CYR_RE = re.compile(r"[а-я]")
_LAT_RE = re.compile(r"[a-z]")


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    """Мультиязычная токенизация: слова 2+ символов (RU/EN/цифры, дефисы), без стоп-слов."""
    return [t for t in _TOKEN_RE.findall(normalize(text)) if t not in STOPWORDS]


def detect_lang(text: str) -> str:
    """Грубая детекция языка по соотношению кириллицы и латиницы: 'ru' | 'en' | 'other'."""
    low = (text or "").lower()
    cyr = len(_CYR_RE.findall(low))
    lat = len(_LAT_RE.findall(low))
    if cyr + lat == 0:
        return "other"
    return "ru" if cyr >= lat else "en"


class BM25:
    """Okapi BM25. corpus — список списков токенов."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(corpus)
        self.tf = [Counter(doc) for doc in corpus]
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 0.0

        df = Counter()
        for doc in corpus:
            df.update(set(doc))
        # Неотрицательный вариант IDF (Lucene-style): ln(1 + (N-n+0.5)/(n+0.5))
        self.idf = {
            t: math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for t, n in df.items()
        }

    def score(self, query_tokens: list[str], i: int):
        """Оценка документа i по запросу. Возвращает (score, {term: вклад})."""
        if not self.avgdl:
            return 0.0, {}
        tf, dl = self.tf[i], self.doc_len[i]
        total, contrib = 0.0, {}
        norm = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
        for t in set(query_tokens):
            f = tf.get(t, 0)
            if not f:
                continue
            c = self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / (f + norm)
            if c > 0:
                total += c
                contrib[t] = c
        return total, contrib


def rank(query: str, texts: list[str], k1: float = 1.5, b: float = 0.75):
    """Оценить все тексты по запросу. Возвращает список по ИСХОДНОМУ порядку текстов:
    [{index, score, terms, lang}]. Сортировку/отбор делает вызывающая сторона.
    """
    docs = [tokenize(t) for t in texts]
    q = tokenize(query)
    bm = BM25(docs, k1=k1, b=b)
    out = []
    for i, text in enumerate(texts):
        s, contrib = bm.score(q, i)
        terms = [t for t, _ in sorted(contrib.items(), key=lambda x: x[1], reverse=True)[:6]]
        out.append({"index": i, "score": round(s, 4), "terms": terms, "lang": detect_lang(text)})
    return out
