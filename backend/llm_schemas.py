"""JSON Schema для structured output LLM (OpenAI json_schema / strict)."""

_EVIDENCE = {
    "type": "object",
    "properties": {
        "source_id": {
            "type": "string",
            "description": "ID источника из контекста, напр. S1 или S2",
        },
        "snippet": {
            "type": "string",
            "description": "Короткая цитата или факт из источника",
        },
        "relevance": {
            "type": "string",
            "description": "Чем этот факт помогает гипотезе",
        },
    },
    "required": ["source_id", "snippet", "relevance"],
    "additionalProperties": False,
}

_HYPOTHESIS = {
    "type": "object",
    "properties": {
        "statement": {
            "type": "string",
            "description": "Чёткая проверяемая формулировка: что изменить и как это повлияет на цель",
        },
        "goal_link": {
            "type": "string",
            "description": "Прямая связь с целью проекта: на какую метрику/KPI и как влияет",
        },
        "rationale": {
            "type": "string",
            "description": "Научное обоснование со ссылками на источники по ID, напр. [S1], [S3]",
        },
        "mechanism": {
            "type": "string",
            "description": "Предполагаемый физико-химический механизм влияния (кратко)",
        },
        "validation": {
            "type": "string",
            "description": "План проверки: образцы, условия, оборудование, что измеряем",
        },
        "evidence": {
            "type": "array",
            "items": _EVIDENCE,
            "description": "Подтверждающие факты из базы знаний",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ключевые слова гипотезы",
        },
        "novelty": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Новизна относительно базы знаний (100 = прорыв)",
        },
        "novelty_rationale": {
            "type": "string",
            "description": "Обоснование оценки новизны (1–2 предложения)",
        },
        "value": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Ожидаемый вклад/эффект для цели (100 = решающий)",
        },
        "value_rationale": {
            "type": "string",
            "description": "Обоснование ожидаемого эффекта для цели",
        },
        "feasibility": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Реализуемость проверки имеющимися ресурсами (100 = легко проверить)",
        },
        "feasibility_rationale": {
            "type": "string",
            "description": "Обоснование реализуемости имеющимися средствами",
        },
        "risk": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Суммарный научно-технический риск (100 = очень высокий)",
        },
        "risk_rationale": {
            "type": "string",
            "description": "Ключевые научные/технические риски и неопределённости",
        },
    },
    "required": [
        "statement", "goal_link", "rationale", "mechanism", "validation",
        "evidence", "tags",
        "novelty", "novelty_rationale",
        "value", "value_rationale",
        "feasibility", "feasibility_rationale",
        "risk", "risk_rationale",
    ],
    "additionalProperties": False,
}

GENERATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": _HYPOTHESIS,
            "description": "Список сгенерированных научных гипотез",
        },
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}

_WEIGHTS = {
    "type": "object",
    "properties": {
        "novelty": {"type": "number", "minimum": 0, "maximum": 1},
        "value": {"type": "number", "minimum": 0, "maximum": 1},
        "feasibility": {"type": "number", "minimum": 0, "maximum": 1},
        "risk": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["novelty", "value", "feasibility", "risk"],
    "additionalProperties": False,
}

_WEIGHT_NOTES = {
    "type": "object",
    "properties": {
        "novelty": {"type": "string", "description": "Почему такой вес новизны"},
        "value": {"type": "string", "description": "Почему такой вес ценности/эффекта"},
        "feasibility": {"type": "string", "description": "Почему такой вес реализуемости"},
        "risk": {"type": "string", "description": "Почему такой вес риска"},
    },
    "required": ["novelty", "value", "feasibility", "risk"],
    "additionalProperties": False,
}

WEIGHT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "weights": {
            **_WEIGHTS,
            "description": "Веса критериев ранжирования; сумма должна быть близка к 1",
        },
        "rationale": {
            "type": "string",
            "description": "1–3 предложения: почему именно так расставлены веса под проект/стадию",
        },
        "notes": _WEIGHT_NOTES,
    },
    "required": ["weights", "rationale", "notes"],
    "additionalProperties": False,
}
