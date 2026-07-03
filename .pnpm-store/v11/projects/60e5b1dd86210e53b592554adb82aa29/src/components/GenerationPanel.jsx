import React, { useState, useEffect, useMemo } from 'react'
import { api } from '../api.js'
import { rankHypotheses } from '../scoring.js'

function Icon({ name }) {
  const common = { width: 16, height: 16, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', viewBox: '0 0 24 24', 'aria-hidden': true }
  if (name === 'download') return <svg {...common}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
  if (name === 'doc') return <svg {...common}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8M16 17H8M10 9H8"/></svg>
  if (name === 'sparkle') return <svg {...common}><path d="m12 3 1.75 5.25L19 10l-5.25 1.75L12 17l-1.75-5.25L5 10l5.25-1.75L12 3Z"/><path d="m5 14 .75 2.25L8 17l-2.25.75L5 20l-.75-2.25L2 17l2.25-.75L5 14Z"/></svg>
  if (name === 'chart') return <svg {...common}><path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-7"/></svg>
  if (name === 'trash') return <svg {...common}><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m10 11 .5 6M14 11l-.5 6"/><path d="M6 6l1 15h10l1-15"/></svg>
  if (name === 'folder') return <svg {...common}><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>
  if (name === 'route') return <svg {...common}><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/><path d="M9 18h1a4 4 0 0 0 4-4v-4a4 4 0 0 1 4-4"/></svg>
  if (name === 'edit') return <svg {...common}><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg>
  return null
}

export default function GenerationPanel({ project, flash }) {
  const [generating, setGenerating] = useState(false)
  
  const [params, setParams] = useState({ n: 5, top_k: 6 })
  
  const [weights, setWeights] = useState({
    novelty: 80,
    value: 95,
    feasibility: 40,
    risk: 20
  })

  const [rawHypotheses, setRawHypotheses] = useState([])
  const [latestRun, setLatestRun] = useState(null)

  useEffect(() => {
    if (!project) return
    Promise.all([
      api.listHypotheses(project.id),
      api.listRuns(project.id)
    ]).then(([hyps, runs]) => {
      setRawHypotheses(hyps)
      if (runs.length > 0) setLatestRun(runs[0])
    }).catch(e => flash(e.message, 'err'))
  }, [project, flash])

  const rankedHypotheses = useMemo(() => {
    const apiWeights = {
      novelty: weights.novelty / 100,
      value: weights.value / 100,
      feasibility: weights.feasibility / 100,
      risk: weights.risk / 100
    }
    return rankHypotheses(rawHypotheses, apiWeights)
  }, [rawHypotheses, weights])

  const handleGenerate = async () => {
    setGenerating(true)
    const apiWeights = {
      novelty: weights.novelty / 100,
      value: weights.value / 100,
      feasibility: weights.feasibility / 100,
      risk: weights.risk / 100
    }
    
    try {
      const res = await api.generate(project.id, {
        n: params.n,
        top_k: params.top_k,
        weights: apiWeights
      })
      setRawHypotheses(res.hypotheses)
      setLatestRun(res.run)
      flash('Гипотезы успешно сгенерированы!', 'ok')
    } catch (e) {
      flash(e.message, 'err')
    } finally {
      setGenerating(false)
    }
  }

  const updateWeight = (key, val) => setWeights(p => ({ ...p, [key]: Number(val) }))
  const rangeStyle = (value, min, max) => ({
    '--range-value': `${((Number(value) - min) / (max - min)) * 100}%`
  })
  
  const wFormula = `*ранг = ${weights.novelty/100} * инновационность + ${weights.value/100} * ценность + ${weights.feasibility/100} * реализуемость + ${weights.risk/100} * (100 - риск) * 1`

  return (
    <div className="gen-layout">
      <div className="gen-main">
        <header className="gen-header">
          <h1>Генерация гипотез</h1>
          <p>Используйте мощь ИИ для поиска нестандартных решений на основе базы знаний</p>
        </header>

        <div className="gen-controls">
          <div className="gen-panel gen-panel--params">
            <h3>Параметры генерации</h3>
            <div className="slider-group">
              <label>
                <span>Количество гипотез</span>
                <span>{params.n}</span>
              </label>
              <input type="range" min="1" max="10" value={params.n} style={rangeStyle(params.n, 1, 10)} onChange={e => setParams({...params, n: Number(e.target.value)})} />
            </div>
            <div className="slider-group">
              <label>
                <span>Источников в контекст</span>
                <span>{params.top_k}</span>
              </label>
              <input type="range" min="1" max="15" value={params.top_k} style={rangeStyle(params.top_k, 1, 15)} onChange={e => setParams({...params, top_k: Number(e.target.value)})} />
            </div>
            <div className="model-indicator">
              <span className="dot"></span> Модель: {latestRun?.model || 'deepseek/deepseek-v4-flash'}
            </div>
          </div>

          <div className="gen-panel gen-panel--weights">
            <h3>Веса ранжирования (Score Weight)</h3>
            <div className="weights-grid">
              <div className="slider-group">
                <label><span>Инновационность</span><span>{weights.novelty}%</span></label>
                <input type="range" min="0" max="100" value={weights.novelty} style={rangeStyle(weights.novelty, 0, 100)} onChange={e => updateWeight('novelty', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Ценность</span><span>{weights.value}%</span></label>
                <input type="range" min="0" max="100" value={weights.value} style={rangeStyle(weights.value, 0, 100)} onChange={e => updateWeight('value', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Реализуемость</span><span>{weights.feasibility}%</span></label>
                <input type="range" min="0" max="100" value={weights.feasibility} style={rangeStyle(weights.feasibility, 0, 100)} onChange={e => updateWeight('feasibility', e.target.value)} />
              </div>
              <div className="slider-group">
                <label><span>Риск</span><span>{weights.risk}%</span></label>
                <input type="range" min="0" max="100" value={weights.risk} style={rangeStyle(weights.risk, 0, 100)} onChange={e => updateWeight('risk', e.target.value)} />
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
          <span className="badge">Найдено {rankedHypotheses.length} релевантных решения</span>
          <div className="spacer" />
          <button className="text-btn" type="button"><Icon name="chart" /> Сравнение</button>
          <button className="text-btn text-muted" type="button"><Icon name="trash" /> Очистить</button>
        </div>

        <div className="gen-grid">
          {rankedHypotheses.map(h => (
            <div key={h.id} className="gen-card">
              <div className="card-top">
                <h3>{h.statement.split('.')[0]}</h3>
                <div className="rank-score">
                  <span className="val">{Math.round(h._composite * 10) || 0}</span>
                  <span className="lbl">РАНГ</span>
                </div>
              </div>
              
              <div className="card-tags">
                {(h.tags || []).map((t, i) => <span key={i} className="tag">{t}</span>)}
              </div>
              
              <p className="card-desc">{h.mechanism || h.statement}</p>
              
              <div className="card-meters">
                <Meter label="Новизна" val={h.scores.novelty} weight={weights.novelty} />
                <Meter label="Ценность" val={h.scores.value} weight={weights.value} />
                <Meter label="Реализуемость" val={h.scores.feasibility} weight={weights.feasibility} />
                <Meter label="Риск" val={h.scores.risk} weight={weights.risk} />
              </div>
              
              <div className="card-actions">
                {/* TODO: Реализовать открытие карточки, генерацию дорожной карты и экспорт в PDF на бэкенде */}
                <button className="btn-outline" type="button"><Icon name="folder" /> Открыть</button>
                <button className="btn-outline" type="button"><Icon name="route" /> Дорожная карта</button>
                <button className="btn-icon" type="button" title="Скачать" aria-label="Скачать"><Icon name="download" /></button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="gen-sidebar">
        <p className="sidebar-hint">Здесь вы можете еще раз проверить используемую базу знаний, и при желании отредактировать</p>
        
        <div className="sidebar-panel">
          <div className="sb-header">
            <h3><Icon name="doc" /> БАЗА ЗНАНИЙ</h3>
            <span className="badge-blue">{latestRun?.retrieved?.length || 0} источников</span>
          </div>
          {/* TODO: Ручка для редактирования/фильтрации источников конкретно для генерации */}
          <button className="btn-outline-dashed" type="button"><Icon name="edit" /> Редактировать источники</button>
          
          <div className="sb-list">
            {(latestRun?.retrieved || []).map((src, i) => (
              <div key={i} className="sb-item">
                <div className="sb-icon"><Icon name="doc" /></div>
                <div className="sb-info">
                  <h4>{src.title}</h4>
                  <p>Окт 2023 • 14 страниц • Высокая релевантность</p>
                  {/* Захардкодил дату и страницы под макет, в БД пока нет этих точных полей, используем что есть */}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
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
