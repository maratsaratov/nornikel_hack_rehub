import React, { useState } from 'react'

export default function TransparencyPanel({ run }) {
  const [showPrompt, setShowPrompt] = useState(false)
  if (!run) return null

  const retrieved = run.retrieved || []
  const maxScore = Math.max(0.0001, ...retrieved.map((r) => r.score || 0))
  const usage = run.usage || {}

  return (
    <div className="card transparency-card">
      <div className="card-head">
        <h3>Прозрачность генерации</h3>
        <div className="spacer" />
        <span className="count">Запуск #{run.id}</span>
      </div>

      <div className="card-body transparency">
        <p className="section-hint">
          Ниже показано, какие документы вошли в retrieval под ваш KPI, какие термины совпали и с какими параметрами отработала модель.
        </p>

        <div className="transparency-grid">
          <div>
            <h4>Отобранные источники ({retrieved.length})</h4>
            {retrieved.length === 0 && <p className="section-hint">Во время запуска не было найдено релевантных документов.</p>}
            {retrieved.map((r) => (
              <div className="retr-item" key={r.source_id}>
                <span className="retr-score">{(r.score ?? 0).toFixed(3)}</span>
                <div className="retr-main">
                  <div className="retr-title" title={r.title}>{r.title}</div>
                  {r.terms && r.terms.length > 0 && (
                    <div className="retr-terms">
                      {r.terms.map((term, index) => <span key={index}>{term}</span>)}
                    </div>
                  )}
                </div>
                <div className="retr-bar">
                  <i style={{ width: `${((r.score || 0) / maxScore) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>

          <div className="trace-meta">
            <h4>Параметры запуска</h4>
            <div className="usage-line">
              {run.model && <span>Модель: <b>{run.model}</b></span>}
              {usage.total_tokens != null && <span>Токены: <b>{usage.total_tokens}</b></span>}
              {usage.cost_usd != null && <span>Стоимость: <b>${Number(usage.cost_usd).toFixed(5)}</b></span>}
              {run.weights && (
                <span>
                  Веса: <b>Н {run.weights.novelty} · Ц {run.weights.value} · Р {run.weights.feasibility} · Риск {run.weights.risk}</b>
                </span>
              )}
            </div>

            {run.prompt_preview && (
              <div className="prompt-block">
                <button className="collapse-toggle" type="button" onClick={() => setShowPrompt(!showPrompt)}>
                  {showPrompt ? 'Скрыть prompt preview' : 'Показать prompt preview'}
                </button>
                {showPrompt && <pre className="prompt-preview">{run.prompt_preview}</pre>}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
