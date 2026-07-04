import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { rankHypotheses } from '../scoring.js'
import { Modal } from './ui.jsx'
import HypothesisRoadmapModal from './HypothesisRoadmapModal.jsx'

const EXPORT_FORMATS = [
  { key: 'pdf', label: 'PDF', hint: 'Бизнес-отчёт' },
  { key: 'docx', label: 'DOCX', hint: 'Бизнес-отчёт' },
  { key: 'csv', label: 'CSV', hint: 'Формат задач' },
  { key: 'json', label: 'JSON', hint: 'Формат задач' },
]

const SCORE_ITEMS = [
  { key: 'novelty', label: 'Новизна' },
  { key: 'value', label: 'Ценность' },
  { key: 'feasibility', label: 'Реализуемость' },
  { key: 'risk', label: 'Риск' },
]

const VERDICTS = [
  { key: 'proposed', label: 'Новая' },
  { key: 'review', label: 'На проверке' },
  { key: 'accepted', label: 'Подтверждена' },
  { key: 'rejected', label: 'Опровергнута' },
]

function Icon({ name }) {
  const common = {
    width: 16,
    height: 16,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    viewBox: '0 0 24 24',
    'aria-hidden': true,
  }

  if (name === 'doc') return <svg {...common}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M16 13H8M16 17H8M10 9H8" /></svg>
  if (name === 'sparkle') return <svg {...common}><path d="m12 3 1.75 5.25L19 10l-5.25 1.75L12 17l-1.75-5.25L5 10l5.25-1.75L12 3Z" /><path d="m5 14 .75 2.25L8 17l-2.25.75L5 20l-.75-2.25L2 17l2.25-.75L5 14Z" /></svg>
  if (name === 'chart') return <svg {...common}><path d="M3 3v18h18" /><path d="m7 15 4-4 3 3 5-7" /></svg>
  if (name === 'trash') return <svg {...common}><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="m10 11 .5 6M14 11l-.5 6" /><path d="M6 6l1 15h10l1-15" /></svg>
  if (name === 'folder') return <svg {...common}><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
  if (name === 'route') return <svg {...common}><circle cx="6" cy="18" r="3" /><circle cx="18" cy="6" r="3" /><path d="M9 18h1a4 4 0 0 0 4-4v-4a4 4 0 0 1 4-4" /></svg>
  if (name === 'edit') return <svg {...common}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></svg>
  if (name === 'download') return <svg {...common}><path d="M12 3v12" /><path d="m7 11 5 5 5-5" /><path d="M5 21h14" /></svg>
  if (name === 'chevron') return <svg {...common}><path d="m6 9 6 6 6-6" /></svg>
  return null
}

function retrievedMeta(source) {
  const parts = []
  if (typeof source?.score === 'number') parts.push(`Score ${source.score.toFixed(3)}`)
  if (Array.isArray(source?.terms) && source.terms.length > 0) parts.push(source.terms.join(', '))
  return parts.join(' · ')
}

export default function GenerationPanel({ project, flash }) {
  const [generating, setGenerating] = useState(false)
  const [params, setParams] = useState({ n: 5, top_k: 6 })
  const [weights, setWeights] = useState({
    novelty: 80,
    value: 95,
    feasibility: 40,
    risk: 20,
  })
  const [rawHypotheses, setRawHypotheses] = useState([])
  const [latestRun, setLatestRun] = useState(null)
  const [openedHypothesisId, setOpenedHypothesisId] = useState(null)
  const [roadmapHypothesisId, setRoadmapHypothesisId] = useState(null)

  useEffect(() => {
    if (!project) return

    Promise.all([
      api.listHypotheses(project.id),
      api.listRuns(project.id),
    ]).then(([hyps, runs]) => {
      setRawHypotheses(hyps)
      setLatestRun(runs[0] || null)
    }).catch((error) => flash(error.message, 'err'))
  }, [project, flash])

  const rankedHypotheses = useMemo(() => {
    const apiWeights = {
      novelty: weights.novelty / 100,
      value: weights.value / 100,
      feasibility: weights.feasibility / 100,
      risk: weights.risk / 100,
    }
    return rankHypotheses(rawHypotheses, apiWeights)
  }, [rawHypotheses, weights])

  const openedHypothesis = useMemo(
    () => rankedHypotheses.find((item) => item.id === openedHypothesisId) || null,
    [rankedHypotheses, openedHypothesisId],
  )

  const openedHypothesisRank = useMemo(() => {
    const index = rankedHypotheses.findIndex((item) => item.id === openedHypothesisId)
    return index >= 0 ? index + 1 : null
  }, [rankedHypotheses, openedHypothesisId])

  const roadmapHypothesis = useMemo(
    () => rankedHypotheses.find((item) => item.id === roadmapHypothesisId) || null,
    [rankedHypotheses, roadmapHypothesisId],
  )

  const roadmapHypothesisRank = useMemo(() => {
    const index = rankedHypotheses.findIndex((item) => item.id === roadmapHypothesisId)
    return index >= 0 ? index + 1 : null
  }, [rankedHypotheses, roadmapHypothesisId])

  const handleGenerate = async () => {
    setGenerating(true)
    const apiWeights = {
      novelty: weights.novelty / 100,
      value: weights.value / 100,
      feasibility: weights.feasibility / 100,
      risk: weights.risk / 100,
    }

    try {
      const res = await api.generate(project.id, {
        n: params.n,
        top_k: params.top_k,
        weights: apiWeights,
      })
      setRawHypotheses(res.hypotheses)
      setLatestRun(res.run)
      setOpenedHypothesisId(null)
      setRoadmapHypothesisId(null)
      flash('Гипотезы успешно сгенерированы!', 'ok')
    } catch (error) {
      flash(error.message, 'err')
    } finally {
      setGenerating(false)
    }
  }

  const updateHypothesis = async (id, patch) => {
    try {
      const updated = await api.updateHypothesis(id, patch)
      setRawHypotheses((prev) => prev.map((item) => (item.id === id ? updated : item)))
    } catch (error) {
      flash(error.message, 'err')
    }
  }

  const exportProject = async (format) => {
    if (!project) return
    try {
      const apiWeights = {
        novelty: weights.novelty / 100,
        value: weights.value / 100,
        feasibility: weights.feasibility / 100,
        risk: weights.risk / 100,
      }
      const url = `/api/projects/${project.id}/hypotheses/export?format=${format}`
        + `&weights=${encodeURIComponent(JSON.stringify(apiWeights))}`
      const res = await fetch(url)
      if (!res.ok) {
        let msg = `Ошибка ${res.status}`
        try { const e = await res.json(); msg = e.error || msg } catch (_) { /* ignore */ }
        throw new Error(msg)
      }
      const blob = await res.blob()
      const cd = res.headers.get('Content-Disposition') || ''
      const match = cd.match(/filename="?([^"]+)"?/)
      const filename = match ? match[1] : `project_${project.id}_hypotheses.${format}`
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(link.href)
      flash(`Экспорт (${format.toUpperCase()}) готов`, 'ok')
    } catch (error) {
      flash(error.message, 'err')
    }
  }

  const updateWeight = (key, val) => setWeights((prev) => ({ ...prev, [key]: Number(val) }))
  const rangeStyle = (value, min, max) => ({
    '--range-value': `${((Number(value) - min) / (max - min)) * 100}%`,
  })
  const openKnowledgeEditor = () => {
    window.location.hash = '#knowledge'
    window.setTimeout(() => {
      document.querySelector('.library-block')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
  }
  const openComparisonPlaceholder = () => flash('Сравнение гипотез появится в следующем обновлении интерфейса.', 'err')
  const openRoadmapPlaceholder = () => flash('Дорожная карта появится после backend-поддержки.', 'err')
  const openRoadmap = (hypothesisId) => setRoadmapHypothesisId(hypothesisId)
  const clearResults = () => {
    setRawHypotheses([])
    setLatestRun(null)
    setOpenedHypothesisId(null)
    setRoadmapHypothesisId(null)
  }

  const wFormula = `rank = ${weights.novelty / 100} * novelty + ${weights.value / 100} * value + ${weights.feasibility / 100} * feasibility + ${weights.risk / 100} * (100 - risk)`

  return (
    <div className="gen-layout">
      <div className="gen-main">
        <header className="gen-header">
          <h1>Генерация гипотез</h1>
          <p>Используйте мощь ИИ для поиска нестандартных решений на основе базы знаний проекта.</p>
        </header>

        <div className="gen-controls">
          <div className="gen-panel gen-panel--params">
            <h3>Параметры генерации</h3>
            <div className="slider-group">
              <label>
                <span>Количество гипотез</span>
                <span>{params.n}</span>
              </label>
              <input type="range" min="1" max="10" value={params.n} style={rangeStyle(params.n, 1, 10)} onChange={(e) => setParams({ ...params, n: Number(e.target.value) })} />
            </div>
            <div className="slider-group">
              <label>
                <span>Источников в контексте</span>
                <span>{params.top_k}</span>
              </label>
              <input type="range" min="1" max="15" value={params.top_k} style={rangeStyle(params.top_k, 1, 15)} onChange={(e) => setParams({ ...params, top_k: Number(e.target.value) })} />
            </div>
            <div className="model-indicator">
              <span className="dot"></span> Модель: {latestRun?.model || 'deepseek/deepseek-v4-flash'}
            </div>
          </div>

          <div className="gen-panel gen-panel--weights">
            <h3>Веса ранжирования</h3>
            <div className="weights-grid">
              <div className="slider-group">
                <label><span>Новизна</span><span>{weights.novelty}%</span></label>
                <input type="range" min="0" max="100" value={weights.novelty} style={rangeStyle(weights.novelty, 0, 100)} onChange={(e) => updateWeight('novelty', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Ценность</span><span>{weights.value}%</span></label>
                <input type="range" min="0" max="100" value={weights.value} style={rangeStyle(weights.value, 0, 100)} onChange={(e) => updateWeight('value', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Реализуемость</span><span>{weights.feasibility}%</span></label>
                <input type="range" min="0" max="100" value={weights.feasibility} style={rangeStyle(weights.feasibility, 0, 100)} onChange={(e) => updateWeight('feasibility', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Риск</span><span>{weights.risk}%</span></label>
                <input type="range" min="0" max="100" value={weights.risk} style={rangeStyle(weights.risk, 0, 100)} onChange={(e) => updateWeight('risk', e.target.value)} />
              </div>
            </div>
            <div className="formula-hint">{wFormula}</div>
          </div>
        </div>

        <button className="gen-btn-primary" onClick={handleGenerate} disabled={generating}>
          <Icon name="sparkle" />
          {generating ? 'Генерация...' : 'Сгенерировать гипотезы'}
        </button>

        <div className="gen-results-header">
          <h2>Результаты анализа</h2>
          <span className="badge">Найдено {rankedHypotheses.length} релевантных решений</span>
          <div className="spacer" />
          <ExportMenu onExport={exportProject} disabled={rankedHypotheses.length === 0} />
          <button className="text-btn" type="button" onClick={openComparisonPlaceholder}><Icon name="chart" /> Сравнение</button>
          <button className="text-btn text-muted" type="button" onClick={clearResults}><Icon name="trash" /> Очистить</button>
        </div>

        <div className="gen-grid">
          {rankedHypotheses.map((h) => (
            <div key={h.id} className="gen-card">
              <div className="card-top">
                <h3>{h.statement.split('.')[0]}</h3>
                <div className="rank-score">
                  <span className="val">{Math.round(h._composite * 10) || 0}</span>
                  <span className="lbl">РАНГ</span>
                </div>
              </div>

              <div className="card-tags">
                {(h.tags || []).map((tag, index) => <span key={index} className="tag">{tag}</span>)}
              </div>

              <p className="card-desc">{h.mechanism || h.statement}</p>

              <div className="card-meters">
                <Meter label="Новизна" val={h.scores.novelty} weight={weights.novelty} />
                <Meter label="Ценность" val={h.scores.value} weight={weights.value} />
                <Meter label="Реализуемость" val={h.scores.feasibility} weight={weights.feasibility} />
                <Meter label="Риск" val={h.scores.risk} weight={weights.risk} />
              </div>

              <div className="card-actions">
                <button className="btn-outline btn-outline--roadmap" type="button" onClick={() => openRoadmap(h.id)}><Icon name="route" /> Дорожная карта</button>
                <button className="btn-outline" type="button" onClick={() => setOpenedHypothesisId(h.id)}><Icon name="folder" /> Открыть</button>
                <button className="btn-outline" type="button" onClick={openRoadmapPlaceholder}><Icon name="route" /> Дорожная карта</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="gen-sidebar">
        <p className="sidebar-hint">Здесь можно ещё раз проверить использованную базу знаний и быстро перейти к её редактированию.</p>

        <div className="sidebar-panel">
          <div className="sb-header">
            <h3><Icon name="doc" /> БАЗА ЗНАНИЙ</h3>
            <span className="badge-blue">{latestRun?.retrieved?.length || 0} источников</span>
          </div>

          <button className="btn-outline-dashed" type="button" onClick={openKnowledgeEditor}><Icon name="edit" /> Редактировать источники</button>

          {(latestRun?.retrieved || []).length > 0 ? (
            <div className="sb-list">
              {(latestRun?.retrieved || []).map((src, index) => (
                <div key={index} className="sb-item">
                  <div className="sb-icon"><Icon name="doc" /></div>
                  <div className="sb-info">
                    <h4>{src.title}</h4>
                    <p>{retrievedMeta(src) || 'Источник вошёл в контекст последнего запуска.'}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="sb-empty">После генерации здесь появятся источники, которые реально попали в retrieval-контекст.</p>
          )}
        </div>
      </div>

      {openedHypothesis && (
        <Modal
          title={openedHypothesisRank ? `Гипотеза #${openedHypothesisRank}` : 'Гипотеза'}
          onClose={() => setOpenedHypothesisId(null)}
          footer={(
            <button className="btn primary" type="button" onClick={() => setOpenedHypothesisId(null)}>
              Закрыть
            </button>
          )}
        >
          <div className="hypothesis-modal">
            <div className="hypothesis-modal__meta">
              <span className="badge">Ранг {Math.round((openedHypothesis._composite || 0) * 10) || 0}</span>
              {openedHypothesis.tags?.length > 0 && (
                <div className="hypothesis-modal__tags">
                  {openedHypothesis.tags.map((tag, index) => <span key={index}>{tag}</span>)}
                </div>
              )}
            </div>

            <div className="hypothesis-modal__lead">
              <h3>{openedHypothesis.statement}</h3>
              <p>{openedHypothesis.goal_link || openedHypothesis.mechanism || 'Подробное описание гипотезы доступно ниже.'}</p>
            </div>

            <div className="hypothesis-modal__scores">
              {SCORE_ITEMS.map((item) => (
                <div className="hypothesis-modal__score" key={item.key}>
                  <span>{item.label}</span>
                  <strong>{Math.round(openedHypothesis.scores?.[item.key] ?? 0)}</strong>
                </div>
              ))}
            </div>

            {openedHypothesis.rationale && (
              <section className="hypothesis-modal__section">
                <h4>Научное обоснование</h4>
                <p>{openedHypothesis.rationale}</p>
              </section>
            )}

            {openedHypothesis.mechanism && (
              <section className="hypothesis-modal__section">
                <h4>Предполагаемый механизм</h4>
                <p>{openedHypothesis.mechanism}</p>
              </section>
            )}

            {openedHypothesis.validation && (
              <section className="hypothesis-modal__section">
                <h4>Как проверить</h4>
                <p>{openedHypothesis.validation}</p>
              </section>
            )}

            {SCORE_ITEMS.some((item) => openedHypothesis.rationales?.[item.key]) && (
              <section className="hypothesis-modal__section">
                <h4>Обоснование оценок</h4>
                <div className="hypothesis-modal__rationales">
                  {SCORE_ITEMS.map((item) => (
                    openedHypothesis.rationales?.[item.key] ? (
                      <div className="hypothesis-modal__rationale" key={item.key}>
                        <strong>{item.label}</strong>
                        <p>{openedHypothesis.rationales[item.key]}</p>
                      </div>
                    ) : null
                  ))}
                </div>
              </section>
            )}

            {openedHypothesis.evidence?.length > 0 && (
              <section className="hypothesis-modal__section">
                <h4>Опорные источники</h4>
                <div className="hypothesis-modal__evidence">
                  {openedHypothesis.evidence.map((item, index) => (
                    <div className="hypothesis-modal__evidence-item" key={`${item.source_id || item.title || 'ev'}-${index}`}>
                      <strong>{item.title || `Источник ${index + 1}`}</strong>
                      {item.snippet && <p>{item.snippet}</p>}
                      {item.relevance && <span>{item.relevance}</span>}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!openedHypothesis.evidence?.length && (latestRun?.retrieved || []).length > 0 && (
              <section className="hypothesis-modal__section">
                <h4>Источники последнего запуска</h4>
                <div className="hypothesis-modal__evidence">
                  {(latestRun?.retrieved || []).map((item, index) => (
                    <div className="hypothesis-modal__evidence-item" key={`${item.source_id || item.title || 'run'}-${index}`}>
                      <strong>{item.title || `Источник ${index + 1}`}</strong>
                      {retrievedMeta(item) && <span>{retrievedMeta(item)}</span>}
                    </div>
                  ))}
                </div>
              </section>
            )}

            <ExpertFeedback
              key={openedHypothesis.id}
              hypothesis={openedHypothesis}
              onUpdate={updateHypothesis}
            />
          </div>
        </Modal>
      )}

      {roadmapHypothesis && (
        <HypothesisRoadmapModal
          hypothesis={roadmapHypothesis}
          hypothesisRank={roadmapHypothesisRank}
          project={project}
          retrieved={latestRun?.retrieved || []}
          onClose={() => setRoadmapHypothesisId(null)}
        />
      )}
    </div>
  )
}

function ExportMenu({ onExport, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDocClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const pick = (format) => {
    setOpen(false)
    onExport(format)
  }

  return (
    <div className={`export-menu ${open ? 'export-menu--open' : ''}`} ref={ref}>
      <button className="text-btn" type="button" disabled={disabled} onClick={() => setOpen((v) => !v)}>
        <Icon name="download" /> Экспорт <Icon name="chevron" />
      </button>
      {open && (
        <div className="export-menu__pop" role="menu">
          {EXPORT_FORMATS.map((format) => (
            <button
              key={format.key}
              type="button"
              className="export-menu__item"
              role="menuitem"
              onClick={() => pick(format.key)}
            >
              <span className="export-menu__fmt">{format.label}</span>
              <span className="export-menu__hint">{format.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ExpertFeedback({ hypothesis, onUpdate }) {
  const [notes, setNotes] = useState(hypothesis.expert_notes || '')

  const setStatus = (status) => onUpdate(hypothesis.id, { status })
  const saveNotes = () => {
    if (notes !== (hypothesis.expert_notes || '')) onUpdate(hypothesis.id, { expert_notes: notes })
  }
  const overrideScore = (key, raw) => {
    const value = raw === '' ? null : Math.max(0, Math.min(100, Number(raw)))
    onUpdate(hypothesis.id, { expert_scores: { [key]: value } })
  }
  const resetScores = () => onUpdate(hypothesis.id, {
    expert_scores: { novelty: null, value: null, feasibility: null, risk: null },
  })
  const hasOverrides = hypothesis.expert_scores
    && Object.values(hypothesis.expert_scores).some((v) => v != null)

  return (
    <section className="hypothesis-modal__section expert-review">
      <h4>Экспертная оценка</h4>
      <p className="expert-review__hint">
        Вердикт и отзыв учитываются моделью при следующей генерации гипотез в этом проекте (обучение на фидбэке).
      </p>

      <div className="expert-review__verdicts">
        {VERDICTS.map((verdict) => (
          <button
            key={verdict.key}
            type="button"
            data-verdict={verdict.key}
            className={hypothesis.status === verdict.key ? 'is-active' : ''}
            onClick={() => setStatus(verdict.key)}
          >
            {verdict.label}
          </button>
        ))}
      </div>

      <label className="expert-review__label" htmlFor={`expert-notes-${hypothesis.id}`}>Отзыв эксперта</label>
      <textarea
        id={`expert-notes-${hypothesis.id}`}
        className="expert-review__notes"
        rows={3}
        placeholder="Почему подтверждена или опровергнута, замечания и что учесть в следующих гипотезах…"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={saveNotes}
      />

      <div className="expert-review__weights-head">
        <span className="expert-review__label">Экспертные оценки (0–100)</span>
        {hasOverrides && (
          <button type="button" className="expert-review__reset" onClick={resetScores}>Сбросить</button>
        )}
      </div>
      <div className="expert-review__weights">
        {SCORE_ITEMS.map((item) => (
          <label className="expert-review__weight" key={item.key}>
            <span>{item.label}</span>
            <input
              type="number"
              min="0"
              max="100"
              defaultValue={hypothesis.expert_scores?.[item.key] ?? ''}
              placeholder={String(Math.round(hypothesis.scores?.[item.key] ?? 0))}
              onBlur={(e) => {
                const current = hypothesis.expert_scores?.[item.key] != null
                  ? String(hypothesis.expert_scores[item.key]) : ''
                if (e.target.value !== current) overrideScore(item.key, e.target.value)
              }}
            />
          </label>
        ))}
      </div>
    </section>
  )
}

function Meter({ label, val = 0, weight }) {
  return (
    <div className="meter">
      <div className="m-head">
        <span>{label}</span>
        <span>{weight}%</span>
      </div>
      <div className="m-track">
        <div className="m-fill" style={{ width: `${val}%`, opacity: weight / 100 + 0.2 }}></div>
      </div>
    </div>
  )
}
