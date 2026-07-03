// Прозрачное ранжирование на стороне клиента: те же формулы, что и на бэкенде.
// Это позволяет мгновенно пере-ранжировать гипотезы при движении ползунков весов,
// не обращаясь к модели заново (экономия ресурсов + мгновенный отклик).

export const DEFAULT_WEIGHTS = { novelty: 0.25, value: 0.30, feasibility: 0.25, risk: 0.20 }

export const DIMS = [
  { key: 'novelty', label: 'Новизна', color: 'var(--c-novelty)', hint: 'нетривиальность относительно базы знаний' },
  { key: 'value', label: 'Ценность', color: 'var(--c-value)', hint: 'ожидаемый вклад в достижение KPI' },
  { key: 'feasibility', label: 'Реализуемость', color: 'var(--c-feas)', hint: 'насколько реально проверить имеющимися средствами' },
  { key: 'risk', label: 'Риск', color: 'var(--c-risk)', hint: 'научно-технический риск и неопределённость (инвертируется)' },
]

// Оценки с учётом экспертных правок
export function effectiveScores(h) {
  return { ...(h.scores || {}), ...(h.expert_scores || {}) }
}

// composite = Σ(w_i·s_i)/Σ(w_i), вклад риска = (100 - risk)
export function composite(scores, w = DEFAULT_WEIGHTS) {
  const n = +scores.novelty || 0
  const v = +scores.value || 0
  const f = +scores.feasibility || 0
  const r = +scores.risk || 0
  const num = w.novelty * n + w.value * v + w.feasibility * f + w.risk * (100 - r)
  const den = w.novelty + w.value + w.feasibility + w.risk
  return den ? Math.round((num / den) * 10) / 10 : 0
}

export function rankHypotheses(list, weights) {
  return [...list]
    .map((h) => ({ ...h, _composite: composite(effectiveScores(h), weights) }))
    .sort((a, b) => b._composite - a._composite)
}

export function scoreColor(v) {
  if (v >= 70) return 'var(--good)'
  if (v >= 45) return 'var(--mid)'
  return 'var(--weak)'
}
