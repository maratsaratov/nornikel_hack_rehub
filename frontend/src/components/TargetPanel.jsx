import React, { useEffect, useState } from 'react'
import { projectStorageKey, readStorage, writeStorage } from '../storage.js'

const DEFAULT_METRICS = [
  {
    id: 'metric-opex',
    name: 'Операционные расходы (OPEX)',
    unit: 'млн руб.',
    current: '145.2',
    target: '130.0',
  },
  {
    id: 'metric-load',
    name: 'Коэффициент загрузки оборудования',
    unit: '%',
    current: '78.5',
    target: '85.0',
  },
]

const DEFAULT_TAGS = ['Эффективность', 'Q4_2024', 'Логистика', 'Затраты']
const DEFAULT_CONSTRAINTS = ['Лом стальной 3А', 'Чугун ПЛ-1', 'Феррохром ФХ010', 'Бюджет 15млн ₽', 'Печь ДСП-25', 'ГОСТ 5632-2014']
const TARGET_DRAFT_STORAGE_SCOPE = 'target-draft'
const TARGET_ACTIONS = new Set(['decrease', 'increase', 'optimize'])

function Icon({ name }) {
  const common = {
    className: 'target-icon',
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  }

  const paths = {
    plus: (
      <>
        <path d="M12 5v14" />
        <path d="M5 12h14" />
      </>
    ),
    tag: (
      <>
        <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z" />
        <path d="M7.5 7.5h.01" />
      </>
    ),
    trash: (
      <>
        <path d="M5 7h14" />
        <path d="M9 7V5h6v2" />
        <path d="m8 7 1 12h6l1-12" />
        <path d="M10 11v5" />
        <path d="M14 11v5" />
      </>
    ),
    save: (
      <>
        <path d="M5 5a2 2 0 0 1 2-2h9l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" />
        <path d="M7 3v6h8" />
        <path d="M8 21v-7h8v7" />
      </>
    ),
    shield: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
  }

  return <svg {...common}>{paths[name]}</svg>
}

function splitTokens(value, fallback) {
  const tokens = String(value || '')
    .split(/[,;\n]/)
    .map((item) => item.trim())
    .filter(Boolean)

  return tokens.length > 0 ? tokens : fallback
}

function projectMetrics(project) {
  const metric = project?.kpi_metric?.trim()
  if (!metric) return DEFAULT_METRICS

  return [{
    id: 'metric-backend',
    name: metric,
    unit: '',
    current: '',
    target: '',
  }]
}

function normalizeAction(value) {
  return TARGET_ACTIONS.has(value) ? value : 'optimize'
}

function normalizeMetric(metric, index) {
  if (!metric || typeof metric !== 'object') return null
  return {
    id: String(metric.id || `metric-${index}`),
    name: String(metric.name || ''),
    unit: String(metric.unit || ''),
    current: String(metric.current || ''),
    target: String(metric.target || ''),
  }
}

function normalizeMetrics(value, fallback) {
  if (!Array.isArray(value)) return fallback

  const normalized = value
    .map(normalizeMetric)
    .filter(Boolean)

  return normalized.length > 0 ? normalized : fallback
}

function normalizeStringList(value, fallback) {
  if (!Array.isArray(value)) return fallback

  const normalized = value
    .map((item) => String(item || '').trim())
    .filter(Boolean)

  return normalized.length > 0 ? normalized : fallback
}

function buildTargetDraft(project) {
  return {
    goal: project?.kpi_target || '',
    action: normalizeAction(project?.kpi_direction || 'optimize'),
    metrics: projectMetrics(project),
    tags: splitTokens(project?.domain, DEFAULT_TAGS),
    constraints: splitTokens(project?.constraints, DEFAULT_CONSTRAINTS),
  }
}

function readTargetDraft(project) {
  const defaults = buildTargetDraft(project)
  const stored = readStorage(projectStorageKey(TARGET_DRAFT_STORAGE_SCOPE, project?.id), null)
  if (!stored || typeof stored !== 'object') return defaults

  return {
    ...defaults,
    goal: typeof stored.goal === 'string' ? stored.goal : defaults.goal,
    action: normalizeAction(stored.action || defaults.action),
    metrics: normalizeMetrics(stored.metrics, defaults.metrics),
    tags: normalizeStringList(stored.tags, defaults.tags),
    constraints: normalizeStringList(stored.constraints, defaults.constraints),
  }
}

function formatSavedDate(value) {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return ''

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export default function TargetPanel({ project, onSave }) {
  const storageKey = projectStorageKey(TARGET_DRAFT_STORAGE_SCOPE, project?.id)
  const initialDraft = readTargetDraft(project)

  const [goal, setGoal] = useState(initialDraft.goal)
  const [action, setAction] = useState(initialDraft.action)
  const [metrics, setMetrics] = useState(initialDraft.metrics)
  const [tags, setTags] = useState(initialDraft.tags)
  const [tagDraft, setTagDraft] = useState('')
  const [constraints, setConstraints] = useState(initialDraft.constraints)
  const [constraintDraft, setConstraintDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [lastSaved, setLastSaved] = useState(() => formatSavedDate(project?.created_at))
  const [activeStorageKey, setActiveStorageKey] = useState(storageKey)

  useEffect(() => {
    const draft = readTargetDraft(project)
    setGoal(draft.goal)
    setAction(draft.action)
    setMetrics(draft.metrics)
    setTags(draft.tags)
    setConstraints(draft.constraints)
    setLastSaved(formatSavedDate(project?.created_at))
    setTagDraft('')
    setConstraintDraft('')
    setActiveStorageKey(storageKey)
  }, [project, storageKey])

  useEffect(() => {
    if (!storageKey || activeStorageKey !== storageKey) return

    writeStorage(storageKey, {
      goal,
      action,
      metrics,
      tags,
      constraints,
    })
  }, [action, activeStorageKey, constraints, goal, metrics, storageKey, tags])

  const updateMetric = (id, field, value) => {
    setMetrics((prev) => prev.map((metric) => (
      metric.id === id ? { ...metric, [field]: value } : metric
    )))
  }

  const addMetric = () => {
    setMetrics((prev) => [
      ...prev,
      {
        id: `metric-${Date.now()}`,
        name: '',
        unit: '',
        current: '',
        target: '',
      },
    ])
  }

  const deleteMetric = (id) => {
    setMetrics((prev) => prev.length > 1 ? prev.filter((metric) => metric.id !== id) : prev)
  }

  const addTag = () => {
    const value = tagDraft.trim()
    if (!value || tags.includes(value)) return
    setTags((prev) => [...prev, value])
    setTagDraft('')
  }

  const removeTag = (tag) => {
    setTags((prev) => prev.filter((item) => item !== tag))
  }

  const addConstraint = () => {
    const value = constraintDraft.trim()
    if (!value || constraints.includes(value)) return
    setConstraints((prev) => [...prev, value])
    setConstraintDraft('')
  }

  const removeConstraint = (constraint) => {
    setConstraints((prev) => prev.filter((item) => item !== constraint))
  }

  const save = async () => {
    if (!goal.trim()) return
    setSaving(true)

    try {
      const primaryMetric = metrics.find((metric) => metric.name.trim()) || metrics[0]
      // TODO backend: заменить плоские поля проекта на структурированный target payload:
      // { goal, action: increase|decrease|optimize, metrics: [{ name, unit, current, target }], tags, constraints }.
      // Сейчас backend умеет хранить только kpi_target, kpi_metric, kpi_direction, domain и constraints.
      const saved = await onSave({
        kpi_target: goal.trim(),
        kpi_metric: primaryMetric?.name?.trim() || '',
        kpi_direction: action === 'decrease' ? 'decrease' : 'increase',
        domain: tags.join(', '),
        constraints: constraints.join(', '),
      })
      setLastSaved(formatSavedDate(saved?.created_at || new Date()))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="target-screen">
      <div className="target-layout">
        <div className="target-main">
          <header className="target-header">
            <h1>Целевой показатель</h1>
            <p>Опишите основную проблему или целевой результат для оптимизации модели</p>
          </header>

          <div className="target-field">
            <label htmlFor="target-goal">Описание основной цели</label>
            <input
              id="target-goal"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="Например: Оптимизация логистических цепочек на Q4"
            />
          </div>

          <fieldset className="target-field target-actions">
            <legend>Требуемое действие</legend>
            <div className="target-segments" role="group" aria-label="Требуемое действие">
              {[
                { key: 'decrease', label: 'Снизить' },
                { key: 'increase', label: 'Повысить' },
                { key: 'optimize', label: 'Оптимизировать' },
              ].map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={action === item.key ? 'is-active' : ''}
                  onClick={() => setAction(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </fieldset>

          <section className="target-metrics">
            <div className="target-section-head">
              <div>
                <h2>Метрики эффективности</h2>
                <p>Выберите отраслевой шаблон или настройте показатели вручную</p>
              </div>
              <button className="target-add-button" type="button" onClick={addMetric}>
                <Icon name="plus" />
                Добавить вручную
              </button>
            </div>

            <div className="target-table" role="table" aria-label="Метрики эффективности">
              <div className="target-table__head" role="row">
                <span role="columnheader">Метрика</span>
                <span role="columnheader">Ед. изм.</span>
                <span role="columnheader">Текущее</span>
                <span role="columnheader">Цель</span>
                <span aria-hidden="true" />
              </div>
              {metrics.map((metric) => (
                <div className="target-table__row" role="row" key={metric.id}>
                  <label>
                    <span className="visually-hidden">Метрика</span>
                    <input value={metric.name} onChange={(event) => updateMetric(metric.id, 'name', event.target.value)} />
                  </label>
                  <label>
                    <span className="visually-hidden">Единица измерения</span>
                    <input value={metric.unit} onChange={(event) => updateMetric(metric.id, 'unit', event.target.value)} />
                  </label>
                  <label>
                    <span className="visually-hidden">Текущее значение</span>
                    <input value={metric.current} onChange={(event) => updateMetric(metric.id, 'current', event.target.value)} inputMode="decimal" />
                  </label>
                  <label>
                    <span className="visually-hidden">Целевое значение</span>
                    <input value={metric.target} onChange={(event) => updateMetric(metric.id, 'target', event.target.value)} inputMode="decimal" />
                  </label>
                  <button type="button" onClick={() => deleteMetric(metric.id)} aria-label="Удалить метрику">
                    <Icon name="trash" />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="target-constraints">
            <h2>Ограничения и лимиты</h2>
            <p>Укажите доступные ресурсы, бюджетные рамки и нормативные требования</p>

            <div className="target-chip-box">
              {constraints.map((constraint) => (
                <button key={constraint} type="button" onClick={() => removeConstraint(constraint)}>
                  {constraint}
                  <span aria-hidden="true">×</span>
                </button>
              ))}
              <label className="target-inline-add">
                <span className="visually-hidden">Новое ограничение</span>
                <input
                  value={constraintDraft}
                  onChange={(event) => setConstraintDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      addConstraint()
                    }
                  }}
                  placeholder="Новое ограничение"
                />
              </label>
              <button className="target-link-button" type="button" onClick={addConstraint}>
                <Icon name="plus" />
                Добавить
              </button>
            </div>
          </section>

          <div className="target-save-row">
            <button className="target-save" type="button" onClick={save} disabled={saving || !goal.trim()}>
              <Icon name="save" />
              {saving ? 'Сохранение...' : 'Сохранить изменения'}
            </button>
            {lastSaved && (
              <span className="target-saved">
                <Icon name="shield" />
                Последнее сохранение: {lastSaved}
              </span>
            )}
          </div>
        </div>

        <aside className="target-sidebar">
          <div className="target-tag-search">
            <h2>Поиск по тегам</h2>
            <label>
              <Icon name="tag" />
              <input
                value={tagDraft}
                onChange={(event) => setTagDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    addTag()
                  }
                }}
                placeholder="Добавить тег..."
              />
            </label>
            <button type="button" className="visually-hidden" onClick={addTag}>Добавить тег</button>
            <div className="target-tags" aria-label="Теги проекта">
              {tags.map((tag) => (
                <button type="button" key={tag} onClick={() => removeTag(tag)}>
                  {tag}
                </button>
              ))}
            </div>
          </div>
          {/* TODO backend: добавить отдельную коллекцию тегов проекта вместо временного хранения в поле domain. */}
          {/* TODO backend: добавить updated_at для проекта, чтобы показывать точное время последнего сохранения. */}
        </aside>
      </div>
    </section>
  )
}
