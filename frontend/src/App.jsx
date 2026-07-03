import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { DEFAULT_WEIGHTS, DIMS, rankHypotheses } from './scoring.js'
import { Toast } from './components/ui.jsx'
import KnowledgePanel from './components/KnowledgePanel.jsx'
import ProjectModal from './components/ProjectModal.jsx'
import HypothesisCard from './components/HypothesisCard.jsx'
import TransparencyPanel from './components/TransparencyPanel.jsx'

const DIR_LABEL = {
  increase: 'Увеличить KPI',
  decrease: 'Снизить KPI',
}

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
  const [projectModal, setProjectModal] = useState(null)
  const [toast, setToast] = useState(null)
  const timerRef = useRef(null)

  const flash = (msg, type = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }

  useEffect(() => {
    api.config().then(setConfig).catch(() => {})
    api.healthLlm().then((r) => setLlmOk(r.ok)).catch(() => setLlmOk(false))
    api.listProjects().then((ps) => {
      setProjects(ps)
      if (ps.length) setCurrentId(ps[0].id)
    }).catch((e) => flash(e.message, 'err'))
  }, [])

  useEffect(() => {
    if (!currentId) {
      setSources([])
      setHypotheses([])
      setLastRun(null)
      return
    }

    Promise.all([
      api.listSources(currentId),
      api.listHypotheses(currentId),
      api.listRuns(currentId),
    ]).then(([src, hyp, runs]) => {
      setSources(src)
      setHypotheses(hyp)
      setLastRun(runs[0] || null)
    }).catch((e) => flash(e.message, 'err'))
  }, [currentId])

  const project = useMemo(
    () => projects.find((p) => p.id === currentId) || null,
    [projects, currentId],
  )

  const reloadHyps = () => api.listHypotheses(currentId).then(setHypotheses).catch(() => {})

  async function saveProject(form) {
    if (form.id) {
      const p = await api.updateProject(form.id, form)
      setProjects((prev) => prev.map((x) => (x.id === p.id ? p : x)))
      flash('Проект обновлён')
    } else {
      const p = await api.createProject(form)
      setProjects((prev) => [p, ...prev])
      setCurrentId(p.id)
      flash('Проект создан')
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
    if (generating || !currentId) return
    setGenerating(true)
    setElapsed(0)
    const start = Date.now()
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)

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
    } catch (e) {
      flash(e.message, 'err')
    }
  }

  async function deleteHypothesis(id) {
    await api.deleteHypothesis(id)
    setHypotheses((prev) => prev.filter((h) => h.id !== id))
  }

  const ranked = useMemo(() => rankHypotheses(hypotheses, weights), [hypotheses, weights])
  const weightSum = DIMS.reduce((acc, dim) => acc + weights[dim.key], 0)
  const llmStateText = llmOk === null ? 'Проверяем модель' : llmOk ? 'LLM доступна' : 'LLM недоступна'
  const modelName = config?.model || 'Модель не задана'
  const topHypothesis = ranked[0]

  return (
    <div className="app">
      <header className="global-nav">
        <div className="global-nav__inner">
          <div className="global-nav__brand">
            <span className="global-nav__logo">N</span>
            <span>Re:Hub Research</span>
          </div>

          <nav className="global-nav__links" aria-label="Навигация по разделам">
            <a href="#overview">Обзор</a>
            <a href="#knowledge">Источники</a>
            <a href="#hypotheses">Гипотезы</a>
            <a href="#trace">Прозрачность</a>
          </nav>

          <div className="global-nav__tools">
            {projects.length > 0 && (
              <select
                className="proj-select global-nav__project-select"
                value={currentId || ''}
                onChange={(e) => setCurrentId(Number(e.target.value))}
                aria-label="Выбор проекта"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            )}
            <button className="btn primary global-nav__cta" onClick={() => setProjectModal('new')}>
              Новый проект
            </button>
          </div>
        </div>
      </header>

      <div className="sub-nav">
        <div className="sub-nav__inner">
          <div className="sub-nav__copy">
            <span className="sub-nav__eyebrow">Фабрика гипотез</span>
            <strong>{project?.title || 'Каталог исследовательских гипотез'}</strong>
          </div>

          <div className="sub-nav__actions">
            <div className="model-badge">
              <span className={`dot ${llmOk === null ? '' : llmOk ? 'ok' : 'bad'}`} />
              <span>{llmStateText}</span>
              <span className="model-badge__sep">·</span>
              <span>{modelName}</span>
            </div>
            {project && (
              <button className="btn secondary" onClick={() => setProjectModal(project)}>
                Параметры
              </button>
            )}
          </div>
        </div>
      </div>

      <main className="page-stack">
        {!currentId ? (
          <>
            <section className="product-tile product-tile-light" id="overview">
              <div className="section-shell section-shell--hero">
                <div className="hero-copy hero-copy--centered">
                  <p className="section-kicker">Research Operating Surface</p>
                  <h1 className="hero-title">Соберите первый НИОКР-проект и превратите базу знаний в очередь проверяемых гипотез.</h1>
                  <p className="hero-lead">
                    Интерфейс теперь построен как спокойная витрина исследования: один проект в фокусе, один синий акцент,
                    одна последовательность действий от KPI к отранжированным гипотезам.
                  </p>
                  <div className="hero-actions hero-actions--centered">
                    <button className="btn primary big" onClick={() => setProjectModal('new')}>
                      Создать проект
                    </button>
                  </div>
                  <p className="hero-footnote">
                    После создания проекта можно добавить источники, настроить веса ранжирования и запустить генерацию без
                    ручной подготовки бекэнда.
                  </p>
                </div>
              </div>
            </section>

            <section className="product-tile product-tile-dark" id="knowledge">
              <div className="section-shell">
                <div className="section-header section-header--dark">
                  <div>
                    <p className="section-kicker">Workflow</p>
                    <h2 className="section-title">Три шага, чтобы запустить исследовательский цикл.</h2>
                  </div>
                </div>

                <div className="utility-grid utility-grid--triple">
                  <article className="card feature-card">
                    <span className="feature-card__index">01</span>
                    <h3>Зафиксируйте KPI</h3>
                    <p>Опишите целевую метрику, направление изменения и ограничения проекта, чтобы генерация работала в конкретном научном контексте.</p>
                  </article>
                  <article className="card feature-card">
                    <span className="feature-card__index">02</span>
                    <h3>Соберите корпус знаний</h3>
                    <p>Добавьте статьи, отчёты и экспериментальные заметки. Каждый источник остаётся прозрачным и доступным для проверки.</p>
                  </article>
                  <article className="card feature-card">
                    <span className="feature-card__index">03</span>
                    <h3>Ранжируйте и проверяйте</h3>
                    <p>Меняйте веса новизны, ценности, реализуемости и риска, чтобы быстро увидеть, какие гипотезы лучше всего отвечают цели.</p>
                  </article>
                </div>
              </div>
            </section>
          </>
        ) : (
          <>
            <section className="product-tile product-tile-light" id="overview">
              <div className="section-shell section-shell--hero">
                <div className="project-overview">
                  <div className="hero-copy hero-copy--project">
                    <p className="section-kicker">{project.domain || 'Research Program'}</p>
                    <h1 className="hero-title">{project.title}</h1>
                    <p className="hero-lead">{project.kpi_target}</p>

                    <div className="hero-actions">
                      <button className="btn primary big" disabled={generating} onClick={generate}>
                        {generating ? 'Генерация…' : 'Сгенерировать гипотезы'}
                      </button>
                      <button className="btn secondary" onClick={() => setProjectModal(project)}>
                        Редактировать проект
                      </button>
                      <button className="btn utility-danger" onClick={deleteProject}>
                        Удалить
                      </button>
                    </div>

                    {project.constraints && <p className="hero-footnote">{project.constraints}</p>}
                  </div>

                  <div className="project-metrics-row">
                    <div className="card hero-panel hero-panel--primary">
                      <div className="hero-panel__header">
                        <span className="section-kicker">Целевой показатель</span>
                        <span className={`direction-pill direction-pill--${project.kpi_direction}`}>
                          {DIR_LABEL[project.kpi_direction]}
                        </span>
                      </div>

                      <div className="hero-panel__metric">{project.kpi_metric || 'Метрика пока не указана'}</div>

                      <div className="hero-panel__meta">
                        {project.domain && <span className="meta-pill">{project.domain}</span>}
                        <span className="meta-pill">Источники: {sources.length}</span>
                        <span className="meta-pill">Гипотезы: {ranked.length}</span>
                        {topHypothesis && <span className="meta-pill">Лидер: {topHypothesis._composite}</span>}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="product-tile product-tile-dark" id="knowledge">
              <div className="section-shell">
                <div className="section-header section-header--dark">
                  <div>
                    <p className="section-kicker">Knowledge Base</p>
                    <h2 className="section-title">Источники и настройки генерации.</h2>
                  </div>
                  <p className="section-copy">
                    Соберите фактуру проекта и задайте, как именно система должна балансировать новизну, ценность, реализуемость и риск.
                  </p>
                </div>

                <div className="utility-grid utility-grid--dual">
                  <KnowledgePanel sources={sources} onAdd={addSource} onDelete={deleteSource} />

                  <div className="card control-card">
                    <div className="card-head">
                      <h3>Генерация гипотез</h3>
                      <span className="count">{sources.length} источников в базе</span>
                    </div>

                    <div className="card-body">
                      <div className="gen-controls">
                        <div className="field">
                          <label>Количество гипотез</label>
                          <input
                            className="num-input"
                            type="number"
                            min="1"
                            max="10"
                            value={n}
                            onChange={(e) => setN(Math.max(1, Math.min(10, Number(e.target.value))))}
                          />
                        </div>
                        <div className="field">
                          <label>Источников в контексте</label>
                          <input
                            className="num-input"
                            type="number"
                            min="1"
                            max="12"
                            value={topK}
                            onChange={(e) => setTopK(Math.max(1, Math.min(12, Number(e.target.value))))}
                          />
                        </div>
                        <button className="btn primary big" disabled={generating} onClick={generate}>
                          {generating ? 'Генерация…' : 'Запустить'}
                        </button>
                      </div>

                      <div className="weights-head">
                        <div>
                          <h4>Весовая модель</h4>
                          <p>Перестройка списка происходит на клиенте, без повторного вызова модели.</p>
                        </div>
                        <button className="btn secondary" onClick={() => setWeights(DEFAULT_WEIGHTS)}>
                          Сбросить веса
                        </button>
                      </div>

                      <div className="weights">
                        {DIMS.map((d) => (
                          <div className="weight" key={d.key}>
                            <div className="wl">
                              <span>{d.label}</span>
                              <span className="pct">{Math.round((weights[d.key] / weightSum) * 100)}%</span>
                            </div>
                            <input
                              type="range"
                              min="0"
                              max="1"
                              step="0.05"
                              value={weights[d.key]}
                              onChange={(e) => setWeights({ ...weights, [d.key]: Number(e.target.value) })}
                            />
                          </div>
                        ))}
                      </div>

                      <div className="formula">
                        Ранг = ({weights.novelty} × Новизна + {weights.value} × Ценность + {weights.feasibility} × Реализуемость + {weights.risk} × (100 − Риск)) / {weightSum.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="product-tile product-tile-parchment" id="hypotheses">
              <div className="section-shell">
                <div className="section-header">
                  <div>
                    <p className="section-kicker">Prioritized Output</p>
                    <h2 className="section-title">Отранжированные гипотезы для проверки.</h2>
                  </div>
                  <p className="section-copy">
                    Каждая карточка показывает итоговый ранг, детализацию по осям оценки и объяснение, на каких источниках держится вывод модели.
                  </p>
                </div>

                {generating && (
                  <div className="card">
                    <div className="gen-loading">
                      <div className="spinner" />
                      <div className="gl-title">Модель формулирует и оценивает гипотезы.</div>
                      <div className="gl-sub">
                        Система подбирает релевантные источники, строит объяснения и формирует ранжированный список.
                        Прошло: <span className="timer">{elapsed} с</span>
                      </div>
                    </div>
                  </div>
                )}

                {!generating && ranked.length === 0 && (
                  <div className="card">
                    <div className="empty">
                      <p className="section-kicker">No Output Yet</p>
                      <h3>Гипотез пока нет.</h3>
                      <p>Запустите генерацию, и система соберёт список проверяемых идей на базе загруженных источников.</p>
                    </div>
                  </div>
                )}

                {!generating && ranked.map((h, i) => (
                  <HypothesisCard
                    key={h.id}
                    h={h}
                    rank={i + 1}
                    onUpdate={updateHypothesis}
                    onDelete={deleteHypothesis}
                  />
                ))}
              </div>
            </section>

            <section className="product-tile product-tile-dark-2" id="trace">
              <div className="section-shell">
                <div className="section-header section-header--dark">
                  <div>
                    <p className="section-kicker">Traceability</p>
                    <h2 className="section-title">Прозрачность последнего запуска.</h2>
                  </div>
                  <p className="section-copy">
                    Показываем, какие документы вошли в retrieval, какие термины совпали и сколько стоил запуск модели.
                  </p>
                </div>

                {lastRun ? (
                  <TransparencyPanel run={lastRun} />
                ) : (
                  <div className="card card--empty-dark">
                    <div className="empty empty--on-dark">
                      <p className="section-kicker">Trace Pending</p>
                      <h3>История запусков ещё не появилась.</h3>
                      <p>После первой генерации здесь будет видно, на какие документы опиралась система и как выглядел prompt preview.</p>
                    </div>
                  </div>
                )}
              </div>
            </section>
          </>
        )}
      </main>

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
