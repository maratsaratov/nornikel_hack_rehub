import React, { useState } from 'react'
import { DIMS, effectiveScores, scoreColor } from '../scoring.js'

const STATUSES = [
  { key: 'proposed', label: 'Новая' },
  { key: 'review', label: 'На проверке' },
  { key: 'accepted', label: 'Принять' },
  { key: 'rejected', label: 'Отклонить' },
]

export default function HypothesisCard({ h, rank, onUpdate, onDelete }) {
  const [expanded, setExpanded] = useState(false)
  const [openRat, setOpenRat] = useState(null)
  const [notes, setNotes] = useState(h.expert_notes || '')
  const eff = effectiveScores(h)

  const setStatus = (status) => onUpdate(h.id, { status })

  const overrideScore = (key, raw) => {
    const value = raw === '' ? null : Math.max(0, Math.min(100, Number(raw)))
    onUpdate(h.id, { expert_scores: { [key]: value } })
  }

  const resetOverrides = () => onUpdate(h.id, {
    expert_scores: { novelty: null, value: null, feasibility: null, risk: null },
  })

  const hasOverrides = h.expert_scores && Object.values(h.expert_scores).some((value) => value != null)

  return (
    <article className={`card hyp status-${h.status}`}>
      <div className="hyp-head">
        <div className="rank-badge">
          <span className="rk">#{rank}</span>
          <div className="comp" title="Итоговый ранг — взвешенная сумма оценок">
            {h._composite}
            <small>rank</small>
          </div>
        </div>

        <div className="hyp-body">
          <div className="hyp-copy">
            <p className="hyp-statement">{h.statement}</p>
            {h.tags && h.tags.length > 0 && (
              <div className="hyp-tags">
                {h.tags.map((tag, index) => (
                  <span className="tag" key={index}>{tag}</span>
                ))}
              </div>
            )}
          </div>

          <div className="scores">
            {DIMS.map((d) => {
              const value = eff[d.key] ?? 0
              const overridden = h.expert_scores && h.expert_scores[d.key] != null
              const tone = d.key === 'risk' ? 'var(--ink)' : scoreColor(value)

              return (
                <button
                  type="button"
                  className={`sbar ${overridden ? 'overridden' : ''}`}
                  key={d.key}
                  onClick={() => setOpenRat(openRat === d.key ? null : d.key)}
                >
                  <div className="sb-top">
                    <span className="sb-label">{d.label}</span>
                    <span className="sb-val" style={{ color: tone }}>{Math.round(value)}</span>
                  </div>
                  <div className="track">
                    <div className="fill" style={{ width: `${value}%` }} />
                  </div>
                </button>
              )
            })}
          </div>

          {openRat && (
            <div className="rationale-pop">
              <b>{DIMS.find((d) => d.key === openRat)?.label}: </b>
              {h.rationales?.[openRat] || 'Обоснование для этой оси не было возвращено моделью.'}
            </div>
          )}
        </div>
      </div>

      <div className="hyp-actions">
        <div className="status-pills">
          {STATUSES.map((status) => (
            <button
              key={status.key}
              type="button"
              data-s={status.key}
              className={h.status === status.key ? 'on' : ''}
              onClick={() => setStatus(status.key)}
            >
              {status.label}
            </button>
          ))}
        </div>

        <div className="hyp-actions__spacer" />

        <button className="collapse-toggle" type="button" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Свернуть детали' : 'Открыть обоснование и экспертизу'}
        </button>

        <button className="btn secondary btn-compact" type="button" onClick={() => onDelete(h.id)}>
          Удалить
        </button>
      </div>

      {expanded && (
        <div className="hyp-detail">
          {h.rationale && (
            <div className="detail-block">
              <h4>Научное обоснование</h4>
              <p>{h.rationale}</p>
            </div>
          )}

          {h.mechanism && (
            <div className="detail-block">
              <h4>Предполагаемый механизм</h4>
              <p>{h.mechanism}</p>
            </div>
          )}

          {h.validation && (
            <div className="detail-block">
              <h4>Как проверить</h4>
              <p>{h.validation}</p>
            </div>
          )}

          {h.evidence && h.evidence.length > 0 && (
            <div className="detail-block">
              <h4>Опорные источники ({h.evidence.length})</h4>
              <div className="evidence-list">
                {h.evidence.map((ev, index) => (
                  <div className="evidence-item" key={index}>
                    <div className="ev-body">
                      {ev.title && <div className="ev-title">{ev.title}</div>}
                      {ev.snippet && <div className="ev-snip">«{ev.snippet}»</div>}
                      {ev.relevance && <div className="ev-rel">{ev.relevance}</div>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="expert-panel">
            <h4>Экспертная корректировка</h4>
            <div className="override-grid">
              {DIMS.map((d) => (
                <div className="ov" key={d.key}>
                  <label>{d.label}</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    defaultValue={h.expert_scores && h.expert_scores[d.key] != null ? h.expert_scores[d.key] : ''}
                    placeholder={String(Math.round(h.scores[d.key] ?? 0))}
                    onBlur={(e) => {
                      const current = h.expert_scores && h.expert_scores[d.key] != null ? String(h.expert_scores[d.key]) : ''
                      if (e.target.value !== current) overrideScore(d.key, e.target.value)
                    }}
                  />
                </div>
              ))}
            </div>

            <textarea
              className="expert-notes"
              placeholder="Заметки эксперта: уточнения, сомнения, следующий шаг проверки…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => notes !== (h.expert_notes || '') && onUpdate(h.id, { expert_notes: notes })}
            />

            {hasOverrides && (
              <button className="btn secondary" type="button" onClick={resetOverrides}>
                Сбросить ручные оценки
              </button>
            )}
          </div>
        </div>
      )}
    </article>
  )
}
