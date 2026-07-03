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
  const [openRat, setOpenRat] = useState(null)   // какая ось-обоснование раскрыта
  const [notes, setNotes] = useState(h.expert_notes || '')
  const eff = effectiveScores(h)

  const setStatus = (status) => onUpdate(h.id, { status })

  const overrideScore = (key, raw) => {
    const val = raw === '' ? null : Math.max(0, Math.min(100, Number(raw)))
    onUpdate(h.id, { expert_scores: { [key]: val } })
  }
  const resetOverrides = () => onUpdate(h.id, {
    expert_scores: { novelty: null, value: null, feasibility: null, risk: null },
  })

  const hasOverrides = h.expert_scores && Object.keys(h.expert_scores).length > 0

  return (
    <div className={`card hyp status-${h.status}`}>
      <div className="hyp-head">
        <div className="rank-badge">
          <span className="rk">#{rank}</span>
          <div className="comp" title="Итоговый ранг = прозрачная взвешенная сумма оценок">
            {h._composite}
            <small>ранг</small>
          </div>
        </div>
        <div className="hyp-body">
          <p className="hyp-statement">{h.statement}</p>
          {h.tags && h.tags.length > 0 && (
            <div className="hyp-tags">
              {h.tags.map((t, i) => <span className="tag" key={i}>{t}</span>)}
            </div>
          )}

          <div className="scores">
            {DIMS.map((d) => {
              const v = eff[d.key] ?? 0
              const overridden = h.expert_scores && h.expert_scores[d.key] != null
              const col = d.key === 'risk' ? d.color : scoreColor(v)
              return (
                <div
                  className={`sbar ${overridden ? 'overridden' : ''}`}
                  key={d.key}
                  style={{ '--accent': d.color }}
                  onClick={() => setOpenRat(openRat === d.key ? null : d.key)}
                >
                  <div className="sb-top">
                    <span className="sb-label" style={{ color: d.color }}>{d.label}</span>
                    <span className="sb-val" style={{ color: col }}>{Math.round(v)}</span>
                  </div>
                  <div className="track">
                    <div className="fill" style={{ width: `${v}%`, background: d.color }} />
                  </div>
                </div>
              )
            })}
          </div>

          {openRat && (
            <div className="rationale-pop" style={{ '--accent': DIMS.find((d) => d.key === openRat).color }}>
              <b>{DIMS.find((d) => d.key === openRat).label}: </b>
              {h.rationales[openRat] || 'Обоснование не предоставлено моделью.'}
            </div>
          )}
        </div>
      </div>

      <div className="hyp-actions">
        <div className="status-pills">
          {STATUSES.map((s) => (
            <button
              key={s.key}
              data-s={s.key}
              className={h.status === s.key ? 'on' : ''}
              onClick={() => setStatus(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="collapse-toggle" onClick={() => setExpanded(!expanded)}>
          {expanded ? '▲ Свернуть' : '▼ Обоснование, механизм, проверка, источники'}
        </button>
        <button className="btn ghost sm danger" title="Удалить гипотезу" onClick={() => onDelete(h.id)}>🗑</button>
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
              <h4>Как проверить (эксперимент)</h4>
              <p>{h.validation}</p>
            </div>
          )}
          {h.evidence && h.evidence.length > 0 && (
            <div className="detail-block">
              <h4>Опора на источники ({h.evidence.length})</h4>
              {h.evidence.map((ev, i) => (
                <div className="evidence-item" key={i}>
                  <span className="ev-src">📎</span>
                  <div className="ev-body">
                    {ev.title && <div style={{ fontWeight: 700, fontSize: 12.5 }}>{ev.title}</div>}
                    {ev.snippet && <div className="ev-snip">«{ev.snippet}»</div>}
                    {ev.relevance && <div className="ev-rel">→ {ev.relevance}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="expert-panel">
            <h4 style={{ margin: 0, fontSize: 12, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--ink-faint)' }}>
              Экспертная корректировка
            </h4>
            <div className="override-grid">
              {DIMS.map((d) => (
                <div className="ov" key={d.key}>
                  <label style={{ color: d.color, fontWeight: 600 }}>{d.label}</label>
                  <input
                    type="number" min="0" max="100"
                    defaultValue={h.expert_scores && h.expert_scores[d.key] != null ? h.expert_scores[d.key] : ''}
                    placeholder={String(Math.round(h.scores[d.key] ?? 0))}
                    onBlur={(e) => {
                      const cur = h.expert_scores && h.expert_scores[d.key] != null ? String(h.expert_scores[d.key]) : ''
                      if (e.target.value !== cur) overrideScore(d.key, e.target.value)
                    }}
                  />
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-start' }}>
              <textarea
                style={{ flex: 1, minHeight: 44, border: '1px solid var(--line-strong)', borderRadius: 8, padding: '8px 10px', fontSize: 13, resize: 'vertical' }}
                placeholder="Заметки эксперта: замечания, корректировки, следующий шаг…"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                onBlur={() => notes !== (h.expert_notes || '') && onUpdate(h.id, { expert_notes: notes })}
              />
            </div>
            {hasOverrides && (
              <button className="btn ghost sm" style={{ marginTop: 6 }} onClick={resetOverrides}>
                ↺ Сбросить ручные оценки (вернуть оценки модели)
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
