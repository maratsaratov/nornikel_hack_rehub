import React, { useState } from 'react'

export default function TransparencyPanel({ run }) {
  const [showPrompt, setShowPrompt] = useState(false)
  if (!run) return null

  const retrieved = run.retrieved || []
  const maxScore = Math.max(0.0001, ...retrieved.map((r) => r.score || 0))
  const u = run.usage || {}

  return (
    <div className="card">
      <div className="card-head">
        <h3>🔍 Прозрачность генерации</h3>
        <div className="spacer" />
        <span className="count">запуск #{run.id}</span>
      </div>
      <div className="card-body transparency">
        <p className="section-hint" style={{ marginTop: 0, marginBottom: 12 }}>
          Ниже — ровно то, на что опиралась система: какие источники отобраны TF-IDF под ваш KPI
          (и по каким совпавшим терминам), с какими весами шло ранжирование и сколько это стоило.
        </p>

        <h4 style={{ margin: '0 0 6px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--ink-faint)' }}>
          Отобранные источники ({retrieved.length})
        </h4>
        {retrieved.length === 0 && <p className="section-hint">База знаний была пуста.</p>}
        {retrieved.map((r) => (
          <div className="retr-item" key={r.source_id}>
            <span className="retr-score">{(r.score ?? 0).toFixed(3)}</span>
            <div style={{ flex: 2, minWidth: 0 }}>
              <div className="retr-title" title={r.title}>{r.title}</div>
              {r.terms && r.terms.length > 0 && (
                <div className="retr-terms">
                  {r.terms.map((t, i) => <span key={i}>{t}</span>)}
                </div>
              )}
            </div>
            <div className="retr-bar"><i style={{ width: `${((r.score || 0) / maxScore) * 100}%` }} /></div>
          </div>
        ))}

        <div className="usage-line">
          {run.model && <span>Модель: <b>{run.model}</b></span>}
          {u.total_tokens != null && <span>Токены: <b>{u.total_tokens}</b></span>}
          {u.cost_usd != null && <span>Стоимость: <b>${Number(u.cost_usd).toFixed(5)}</b></span>}
          {run.weights && (
            <span>
              Веса: <b>
                Н {run.weights.novelty} · Ц {run.weights.value} · Р {run.weights.feasibility} · Риск {run.weights.risk}
              </b>
            </span>
          )}
        </div>

        {run.prompt_preview && (
          <div style={{ marginTop: 12 }}>
            <button className="collapse-toggle" onClick={() => setShowPrompt(!showPrompt)}>
              {showPrompt ? '▲ Скрыть промпт' : '▼ Показать промпт, отправленный модели'}
            </button>
            {showPrompt && <pre className="prompt-preview">{run.prompt_preview}</pre>}
          </div>
        )}
      </div>
    </div>
  )
}
