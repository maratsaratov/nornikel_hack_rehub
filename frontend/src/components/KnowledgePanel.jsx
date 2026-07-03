import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = {
  title: '',
  content: '',
  source_type: 'literature',
  authors: '',
  year: '',
  reference: '',
}

const EMPTY_RESULTS = {
  query: '',
  local: [],
  external: [],
  external_error: null,
}

const WORK_TYPE_LABEL = {
  article: 'Статья',
  book: 'Книга',
  dataset: 'Набор данных',
  dissertation: 'Диссертация',
  preprint: 'Препринт',
  report: 'Отчёт',
}

function compactText(value) {
  return (value || '').replace(/\s+/g, ' ').trim()
}

function previewText(source) {
  return compactText(source.excerpt || source.content || '')
}

function resultKey(source) {
  return source.external_id || source.reference || source.id || source.title
}

function isMostlyUppercase(text) {
  const letters = [...text].filter((char) => char.toLowerCase() !== char.toUpperCase())
  if (letters.length < 8) return false

  const uppercase = letters.filter((char) => char === char.toUpperCase()).length
  return uppercase / letters.length > 0.75
}

function displayTitle(source) {
  const title = compactText(source.title)
  if (!title) return ''
  if (!isMostlyUppercase(title)) return title

  const lower = title.toLocaleLowerCase('ru-RU')
  return lower.charAt(0).toLocaleUpperCase('ru-RU') + lower.slice(1)
}

function metaText(source) {
  return [source.authors, source.year].filter(Boolean).join(' / ')
}

function shortText(value, maxLength = 120) {
  const text = compactText(value)
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength - 3).trimEnd() + '...'
}

function miniDescription(source) {
  const journal = compactText(source.journal)
  if (journal) return journal

  const workType = compactText(WORK_TYPE_LABEL[source.work_type] || source.work_type)
  if (workType) return workType

  const excerpt = previewText(source)
  const firstSentence = excerpt.split(/(?<=[.!?])\s+/)[0]
  return shortText(firstSentence || excerpt, 140)
}

function sourceDescription(source) {
  if (source.origin === 'openalex') {
    return miniDescription(source)
  }
  return previewText(source)
}

export default function KnowledgePanel({ sources, onAdd, onDelete, onSearch, onImportOpenAlex }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [importingKey, setImportingKey] = useState(null)

  const canSearchCatalog = typeof onSearch === 'function'
  const canImportOpenAlex = typeof onImportOpenAlex === 'function'
  const updateField = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function submit() {
    if (!form.title.trim() || !form.content.trim()) return
    setSaving(true)
    try {
      await onAdd({ ...form, year: form.year ? parseInt(form.year, 10) : null })
      setForm(EMPTY)
      setOpen(false)
    } finally {
      setSaving(false)
    }
  }

  async function runSearch() {
    if (!canSearchCatalog) return

    const cleaned = query.trim()
    if (cleaned.length < 2) {
      setResults(EMPTY_RESULTS)
      return
    }

    setSearching(true)
    try {
      const next = await onSearch(cleaned)
      setResults(next)
    } catch (e) {
      setResults({
        query: cleaned,
        local: [],
        external: [],
        external_error: e.message,
      })
    } finally {
      setSearching(false)
    }
  }

  function clearSearch() {
    setQuery('')
    setResults(null)
  }

  async function importResult(source) {
    if (!canImportOpenAlex) return

    const key = resultKey(source)
    setImportingKey(key)
    try {
      const res = await onImportOpenAlex(source)
      setResults((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          external: prev.external.map((item) => (
            resultKey(item) === key
              ? { ...item, already_added: true, existing_source_id: res.source?.id || item.existing_source_id }
              : item
          )),
        }
      })
    } finally {
      setImportingKey(null)
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>База знаний</h3>
        <span className="count">{sources.length}</span>
        <div className="spacer" />
        <button className="btn primary" type="button" onClick={() => setOpen(true)}>
          Добавить источник
        </button>
      </div>

      <div className="card-body knowledge-panel">
        {canSearchCatalog && (
          <div className="source-tools">
            <div className="source-search-row">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && runSearch()}
                placeholder="Ключевые слова, DOI, авторы..."
              />
              <button className="btn primary btn-compact" type="button" disabled={searching} onClick={runSearch}>
                {searching ? 'Поиск...' : 'Найти'}
              </button>
              {(query || results) && (
                <button className="btn secondary btn-compact" type="button" onClick={clearSearch}>
                  Сбросить
                </button>
              )}
            </div>
            <p className="section-hint">
              Поиск идёт по источникам проекта и по внешнему каталогу. Подходящие публикации можно сразу импортировать в базу.
            </p>
          </div>
        )}

        {results && (
          <div className="search-results">
            <div className="search-group">
              <div className="search-group-head">
                <h4>Совпадения в проекте</h4>
                <span>{results.local.length}</span>
              </div>
              {results.local.length === 0 ? (
                <p className="section-hint">В локальной базе совпадений пока нет.</p>
              ) : (
                results.local.map((source) => (
                  <div className="search-item" key={`local-${source.id}`}>
                    <div className="search-top">
                      <div className="search-main">
                        <div className="search-tags">
                          <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
                          <span className="search-badge local">в базе</span>
                        </div>
                        <div className="search-title">{displayTitle(source)}</div>
                      </div>
                    </div>
                    {metaText(source) && <div className="search-meta">{metaText(source)}</div>}
                    {sourceDescription(source) && <div className="search-description">{sourceDescription(source)}</div>}
                    {source.reference && <div className="search-links"><span>{source.reference}</span></div>}
                  </div>
                ))
              )}
            </div>

            <div className="search-group">
              <div className="search-group-head">
                <h4>Внешний каталог</h4>
                <span>{results.external.length}</span>
              </div>
              {results.external_error && (
                <p className="section-hint search-error">{results.external_error}</p>
              )}
              {!results.external_error && results.external.length === 0 ? (
                <p className="section-hint">Внешний каталог ничего не вернул по этому запросу.</p>
              ) : (
                results.external.map((source) => {
                  const key = resultKey(source)
                  const disabled = source.already_added || importingKey === key

                  return (
                    <div className="search-item" key={`external-${key}`}>
                      <div className="search-top">
                        <div className="search-main">
                          <div className="search-tags">
                            <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
                            {source.already_added && <span className="search-badge added">уже в базе</span>}
                          </div>
                          <div className="search-title">{displayTitle(source)}</div>
                        </div>
                        {canImportOpenAlex && (
                          <button
                            className={`btn ${source.already_added ? 'secondary' : 'primary'} btn-compact search-action`}
                            type="button"
                            disabled={disabled}
                            onClick={() => importResult(source)}
                          >
                            {importingKey === key ? 'Добавление...' : source.already_added ? 'Уже добавлен' : 'Добавить'}
                          </button>
                        )}
                      </div>
                      {metaText(source) && <div className="search-meta">{metaText(source)}</div>}
                      {miniDescription(source) && <div className="search-description">{miniDescription(source)}</div>}
                      <div className="search-links">
                        {source.reference && <span>{source.reference}</span>}
                        {source.landing_page_url && (
                          <a href={source.landing_page_url} target="_blank" rel="noreferrer">Страница</a>
                        )}
                        {source.pdf_url && (
                          <a href={source.pdf_url} target="_blank" rel="noreferrer">PDF</a>
                        )}
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            {!results.external_error && results.local.length === 0 && results.external.length === 0 && (
              <p className="section-hint">
                По запросу «{results.query}» ничего не найдено.
              </p>
            )}
          </div>
        )}

        {sources.length > 0 && <div className="source-list-title">Все источники проекта</div>}
        {sources.length === 0 && (
          <p className="section-hint">
            Добавьте статьи, отчёты и экспериментальные заметки. Эти материалы станут основой retrieval и объяснений для гипотез.
          </p>
        )}

        {sources.map((source) => (
          <article className="source" key={source.id}>
            <div className="s-top">
              <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
              <span className="s-title">{displayTitle(source)}</span>
              <button
                className="btn secondary btn-compact source-remove"
                type="button"
                title="Удалить источник"
                onClick={() => onDelete(source.id)}
              >
                Удалить
              </button>
            </div>

            {(metaText(source) || sourceDescription(source)) && (
              <div className="s-excerpt">
                {metaText(source) && (
                  <b>
                    {metaText(source)}
                    {sourceDescription(source) ? ' · ' : ''}
                  </b>
                )}
                {sourceDescription(source)}
              </div>
            )}
          </article>
        ))}
      </div>

      {open && (
        <Modal
          title="Новый источник знаний"
          onClose={() => setOpen(false)}
          footer={(
            <>
              <button className="btn secondary" type="button" onClick={() => setOpen(false)}>
                Отмена
              </button>
              <button className="btn primary" type="button" disabled={saving} onClick={submit}>
                {saving ? 'Сохранение...' : 'Добавить'}
              </button>
            </>
          )}
        >
          <Field label="Тип источника">
            <select value={form.source_type} onChange={updateField('source_type')}>
              <option value="literature">Литература / статья</option>
              <option value="report">Внутренний отчёт</option>
              <option value="experiment">Эксперимент / лабораторные данные</option>
            </select>
          </Field>

          <Field label="Заголовок *">
            <input value={form.title} onChange={updateField('title')} placeholder="Название статьи или отчёта" />
          </Field>

          <div className="row">
            <Field label="Авторы / подразделение">
              <input value={form.authors} onChange={updateField('authors')} placeholder="Petrov et al." />
            </Field>
            <Field label="Год">
              <input value={form.year} onChange={updateField('year')} placeholder="2025" className="num-input" />
            </Field>
          </div>

          <Field label="Ссылка / DOI / инвентарный номер">
            <input value={form.reference} onChange={updateField('reference')} placeholder="DOI, ссылка или номер отчёта" />
          </Field>

          <Field label="Содержание / аннотация *">
            <textarea
              value={form.content}
              onChange={updateField('content')}
              rows={7}
              placeholder="Вставьте текст, аннотацию или ключевые выводы источника..."
            />
          </Field>
        </Modal>
      )}
    </div>
  )
}
