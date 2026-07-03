import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { DEFAULT_WEIGHTS, DIMS, rankHypotheses } from './scoring.js'
import { Toast } from './components/ui.jsx'
import KnowledgePanel from './components/KnowledgePanel.jsx'
import ProjectModal from './components/ProjectModal.jsx'
import HypothesisCard from './components/HypothesisCard.jsx'
import TransparencyPanel from './components/TransparencyPanel.jsx'

const DIR_LABEL = { increase: '↑ увеличить', decrease: '↓ снизить' }

export default function App() {
  const [config, setConfig] = useState(null)
  const [llmOk, setLlmOk] = useState(null)
  const [projects, setProjects] = useState([])
  const [currentId, setCurrentId] = useState(null)
  const [sources, setSources] = useState([])
  const [hypotheses, setHypotheses] = useState([])
  const [lastRun, setLastRun] = useState(null)

  const [weights, setWeights] = useState(DEFAULT_WEIGHTS)
  const [n, setN] = useState(5)
  const [topK, setTopK] = useState(6)

  const [generating, setGenerating] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [projectModal, setProjectModal] = useState(null) // 'new' | project | null
  const [toast, setToast] = useState(null)
  const timerRef = useRef(null)

  const flash = (msg, type = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }

  // ── initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    api.config().then(setConfig).catch(() => {})
    api.healthLlm().then((r) => setLlmOk(r.ok)).catch(() => setLlmOk(false))
    api.listProjects().then((ps) => {
      setProjects(ps)
      if (ps.length) setCurrentId(ps[0].id)
    }).catch((e) => flash(e.message, 'err'))
  }, [])

  // ── load project context when selection changes ─────────────────────────────
  useEffect(() => {
    if (!currentId) { setSources([]); setHypotheses([]); setLastRun(null); return }
    Promise.all([
      api.listSources(currentId),
      api.listHypotheses(currentId),
      api.listRuns(currentId),
    ]).then(([src, hyp, runs]) => {
      setSources(src)
      setHypotheses(hyp)
      setLastRun(runs[0] || null)
    }).catch((e) => flash(e.message, 'err'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId])

  const project = useMemo(() => projects.find((p) => p.id === currentId) || null, [projects, currentId])

  const reloadHyps = () => api.listHypotheses(currentId).then(setHypotheses).catch(() => {})

  // ── handlers ────────────────────────────────────────────────────────────────
  async function saveProject(form) {
    if (form.id) {
      const p = await api.updateProject(form.id, form)
      setProjects((prev) => prev.map((x) => (x.id === p.id ? p : x)))
      flash('Проект обновлён')
    } else {
      const p = await api.createProject(form)
      setProjects((prev) => [p, ...prev]); setCurrentId(p.id); flash('Проект создан')
    }
  }

  async function deleteProject() {
    if (!project || !window.confirm(`Удалить проект «${project.title}» со всеми гипотезами?`)) return
    await api.deleteProject(project.id)
    const rest = projects.filter((p) => p.id !== project.id)
    setProjects(rest)
    setCurrentId(rest[0]?.id || null)
    flash('Проект удалён')
  }

  async function addSource(data) {
    await api.addSource(currentId, data)
    const src = await api.listSources(currentId)
    setSources(src)
    flash('Источник добавлен')
  }
  async function deleteSource(id) {
    await api.deleteSource(id)
    setSources((prev) => prev.filter((s) => s.id !== id))
  }

  async function generate() {
    if (generating) return
    setGenerating(true); setElapsed(0)
    const start = Date.now()
    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    try {
      const res = await api.generate(currentId, { n, top_k: topK, weights })
      await reloadHyps()
      setLastRun(res.run)
      flash(`Сгенерировано гипотез: ${res.hypotheses.length}`)
    } catch (e) {
      flash(e.message, 'err')
    } finally {
      clearInterval(timerRef.current)
      setGenerating(false)
    }
  }

  async function updateHypothesis(id, patch) {
    try {
      const updated = await api.updateHypothesis(id, patch)
      setHypotheses((prev) => prev.map((h) => (h.id === id ? updated : h)))
    } catch (e) { flash(e.message, 'err') }
  }
  async function deleteHypothesis(id) {
    await api.deleteHypothesis(id)
    setHypotheses((prev) => prev.filter((h) => h.id !== id))
  }

  const ranked = useMemo(() => rankHypotheses(hypotheses, weights), [hypotheses, weights])
  const weightSum = DIMS.reduce((a, d) => a + weights[d.key], 0)

  // ── render ──────────────────────────────────────────────────────────────────
  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">
          <span className="mark">⚗️</span>
          <div>
            Фабрика гипотез
            <small>генерация и ранжирование НИОКР-гипотез</small>
          </div>
        </div>
        <div className="spacer" />
        {projects.length > 0 && (
          <select
            className="proj-select"
            value={currentId || ''}
            onChange={(e) => setCurrentId(Number(e.target.value))}
          >
            {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        )}
        <button className="btn" onClick={() => setProjectModal('new')}>+ Проект</button>
        <div className="model-badge">
          <span className={`dot ${llmOk === null ? '' : llmOk ? 'ok' : 'bad'}`} />
          {config?.model || 'модель…'}
        </div>
      </header>

      {!currentId ? (
        <div className="layout" style={{ gridTemplateColumns: '1fr' }}>
          <div className="card"><div className="empty">
            <div className="big-ico">⚗️</div>
            <h3>Создайте первый НИОКР-проект</h3>
            <p>Задайте целевой показатель (KPI) и наполните базу знаний — система сгенерирует
              ранжированный список проверяемых гипотез с обоснованием, новизной, рисками и ценностью.</p>
            <button className="btn primary big" style={{ marginTop: 18 }} onClick={() => setProjectModal('new')}>
              + Новый проект
            </button>
          </div></div>
        </div>
      ) : (
        <div className="layout">
          {/* ── Sidebar ── */}
          <aside className="sidebar">
            <div className="card">
              <div className="card-head">
                <h3>Целевой показатель</h3>
                <div className="spacer" />
                <button className="btn ghost sm" title="Редактировать" onClick={() => setProjectModal(project)}>⚙</button>
                <button className="btn ghost sm danger" title="Удалить проект" onClick={deleteProject}>🗑</button>
              </div>
              <div className="card-body">
                {project && (
                  <>
                    <div className="kpi-target">{project.kpi_target}</div>
                    <div className="kpi-meta">
                      {project.kpi_metric && <span className="chip"><b>Метрика:</b> {project.kpi_metric}</span>}
                      <span className={`chip dir-${project.kpi_direction}`}>{DIR_LABEL[project.kpi_direction]}</span>
                      {project.domain && <span className="chip">{project.domain}</span>}
                    </div>
                    {project.constraints && (
                      <p className="section-hint" style={{ marginTop: 12 }}>
                        <b style={{ color: 'var(--ink-soft)' }}>Ограничения:</b> {project.constraints}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>

            <KnowledgePanel sources={sources} onAdd={addSource} onDelete={deleteSource} />
          </aside>

          {/* ── Main ── */}
          <main className="main">
            {/* Generate + weights */}
            <div className="card">
              <div className="card-head">
                <h3>Генерация гипотез</h3>
                <div className="spacer" />
                <span className="count">{sources.length} источников в базе</span>
              </div>
              <div className="card-body">
                <div className="gen-controls">
                  <div className="field">
                    <label>Сколько гипотез</label>
                    <input className="num-input" type="number" min="1" max="10" value={n}
                      onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value))))} />
                  </div>
                  <div className="field">
                    <label>Источников в контекст</label>
                    <input className="num-input" type="number" min="1" max="12" value={topK}
                      onChange={(e) => setTopK(Math.max(1, Math.min(12, Number(e.target.value))))} />
                  </div>
                  <button className="btn primary big" disabled={generating} onClick={generate}>
                    {generating ? 'Генерация…' : '⚡ Сгенерировать гипотезы'}
                  </button>
                </div>

                <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '16px 0' }} />

                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
                  <h4 style={{ margin: 0, fontSize: 13 }}>Веса ранжирования</h4>
                  <span className="section-hint" style={{ margin: '0 0 0 10px' }}>
                    двигайте ползунки — список пере-ранжируется мгновенно, без повторного вызова модели
                  </span>
                  <div style={{ flex: 1 }} />
                  <button className="btn ghost sm" onClick={() => setWeights(DEFAULT_WEIGHTS)}>сбросить</button>
                </div>
                <div className="weights">
                  {DIMS.map((d) => (
                    <div className="weight" key={d.key} style={{ '--accent': d.color }}>
                      <div className="wl">
                        <span style={{ color: d.color }}>{d.label}</span>
                        <span className="pct">{Math.round((weights[d.key] / weightSum) * 100)}%</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.05" value={weights[d.key]}
                        style={{ accentColor: d.color }}
                        onChange={(e) => setWeights({ ...weights, [d.key]: Number(e.target.value) })} />
                    </div>
                  ))}
                </div>
                <div className="formula">
                  ранг = ( {weights.novelty}·Новизна + {weights.value}·Ценность + {weights.feasibility}·Реализуемость
                  {' '}+ {weights.risk}·(100−Риск) ) / {weightSum.toFixed(2)}
                </div>
              </div>
            </div>

            {/* Hypotheses */}
            {generating && (
              <div className="card"><div className="gen-loading">
                <div className="spinner" />
                <div className="gl-title">Модель формулирует и оценивает гипотезы…</div>
                <div className="gl-sub">
                  Reasoning-модель рассуждает над базой знаний — обычно это занимает 1–2 минуты.
                  Прошло: <span className="timer">{elapsed} с</span>
                </div>
              </div></div>
            )}

            {!generating && ranked.length === 0 && (
              <div className="card"><div className="empty">
                <div className="big-ico">💡</div>
                <h3>Гипотез пока нет</h3>
                <p>Нажмите «Сгенерировать гипотезы» — система отберёт релевантные источники из базы знаний
                  и предложит ранжированный список проверяемых гипотез.</p>
              </div></div>
            )}

            {!generating && ranked.map((h, i) => (
              <HypothesisCard
                key={h.id} h={h} rank={i + 1}
                onUpdate={updateHypothesis} onDelete={deleteHypothesis}
              />
            ))}

            {!generating && lastRun && <TransparencyPanel run={lastRun} />}
          </main>
        </div>
      )}

      {projectModal && (
        <ProjectModal
          initial={projectModal === 'new' ? null : projectModal}
          onClose={() => setProjectModal(null)}
          onSave={saveProject}
        />
      )}
      <Toast toast={toast} />
    </div>
  )
}
