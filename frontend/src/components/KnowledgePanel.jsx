import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = { title: '', content: '', source_type: 'literature', authors: '', year: '', reference: '' }
const EMPTY_RESULTS = { query: '', local: [], external: [], external_error: null }

function previewText(source) {
  return source.excerpt || source.content || ''
}

function resultKey(source) {
  return source.external_id || source.reference || source.id || source.title
}

function metaText(source) {
  return [source.authors, source.year, source.journal].filter(Boolean).join(' / ')
}

function originLabel(source) {
  if (source.origin === 'openalex') return 'Внешний'
  return ''
}

export default function KnowledgePanel({ sources, onAdd, onDelete, onSearch, onImportOpenAlex }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [importingKey, setImportingKey] = useState(null)

  const upd = (key) => (e) => setForm({ ...form, [key]: e.target.value })

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
        <button className="btn sm" onClick={() => setOpen(true)}>+ Источник</button>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        <div className="source-tools">
          <div className="source-search-row">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runSearch()}
              placeholder="Ключевые слова, DOI, авторы..."
            />
            <button className="btn sm primary" disabled={searching} onClick={runSearch}>
              {searching ? 'Поиск...' : 'Найти'}
            </button>
            {(query || results) && (
              <button className="btn sm" onClick={clearSearch}>Сбросить</button>
            )}
          </div>
          <p className="section-hint">
            Поиск идет по источникам проекта и по OpenAlex. Внешние статьи можно сразу добавить в базу.
          </p>
        </div>

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
                          <div className="marker-stack">
                            <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
                            {originLabel(source) && <span className="origin-badge">{originLabel(source)}</span>}
                          </div>
                          <span className="search-badge local">в базе</span>
                        </div>
                        <div className="s-title">{source.title}</div>
                      </div>
                    </div>
                    {metaText(source) && <div className="search-meta">{metaText(source)}</div>}
                    <div className="s-excerpt">{previewText(source)}</div>
                    {source.reference && <div className="search-links">{source.reference}</div>}
                  </div>
                ))
              )}
            </div>

            <div className="search-group">
              <div className="search-group-head">
                <h4>OpenAlex</h4>
                <span>{results.external.length}</span>
              </div>
              {results.external_error && (
                <p className="section-hint search-error">{results.external_error}</p>
              )}
              {!results.external_error && results.external.length === 0 ? (
                <p className="section-hint">OpenAlex ничего не вернул по этому запросу.</p>
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
                            <span className="search-badge external">OpenAlex</span>
                            {source.already_added && <span className="search-badge added">уже в базе</span>}
                          </div>
                          <div className="s-title">{source.title}</div>
                        </div>
                        <button
                          className={`btn sm ${source.already_added ? '' : 'primary'}`}
                          disabled={disabled}
                          onClick={() => importResult(source)}
                        >
                          {importingKey === key ? 'Добавление...' : source.already_added ? 'Уже добавлен' : 'Добавить'}
                        </button>
                      </div>
                      {metaText(source) && <div className="search-meta">{metaText(source)}</div>}
                      <div className="s-excerpt">{previewText(source)}</div>
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
              <p className="section-hint" style={{ marginTop: -4 }}>
                По запросу «{results.query}» ничего не найдено.
              </p>
            )}
          </div>
        )}

        {sources.length > 0 && <div className="source-list-title">Все источники проекта</div>}
        {sources.length === 0 && (
          <p className="section-hint" style={{ padding: '10px 0' }}>
            Добавьте литературу, отчеты и эксперименты. На их основе будут строиться гипотезы.
          </p>
        )}
        {sources.map((source) => (
          <div className="source" key={source.id}>
            <div className="s-top">
              <div className="marker-stack">
                <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
                {originLabel(source) && <span className="origin-badge">{originLabel(source)}</span>}
              </div>
              <span className="s-title">{source.title}</span>
              <button className="btn ghost sm danger" title="Удалить" onClick={() => onDelete(source.id)}>✕</button>
            </div>
            <div className="s-excerpt">
              {(source.authors || source.year) && (
                <b style={{ color: 'var(--ink-soft)' }}>
                  {[source.authors, source.year].filter(Boolean).join(', ')} -{' '}
                </b>
              )}
              {previewText(source)}
            </div>
          </div>
        ))}
      </div>

      {open && (
        <Modal
          title="Новый источник знаний"
          onClose={() => setOpen(false)}
          footer={(
            <>
              <button className="btn" onClick={() => setOpen(false)}>Отмена</button>
              <button className="btn primary" disabled={saving} onClick={submit}>
                {saving ? 'Сохранение...' : 'Добавить'}
              </button>
            </>
          )}
        >
          <Field label="Тип источника">
            <select value={form.source_type} onChange={upd('source_type')}>
              <option value="literature">Литература / статья</option>
              <option value="report">Внутренний отчет</option>
              <option value="experiment">Эксперимент / лабораторные данные</option>
            </select>
          </Field>
          <Field label="Заголовок *">
            <input value={form.title} onChange={upd('title')} placeholder="Название статьи / отчета" />
          </Field>
          <div className="row">
            <Field label="Авторы / подразделение">
              <input value={form.authors} onChange={upd('authors')} placeholder="Petrov et al." />
            </Field>
            <Field label="Год">
              <input value={form.year} onChange={upd('year')} placeholder="2023" className="num-input" />
            </Field>
          </div>
          <Field label="Ссылка / DOI / инв. номер">
            <input value={form.reference} onChange={upd('reference')} placeholder="DOI, ссылка или ID отчета" />
          </Field>
          <Field label="Содержание / аннотация *">
            <textarea
              value={form.content}
              onChange={upd('content')}
              rows={7}
              placeholder="Вставьте текст, аннотацию или ключевые выводы источника..."
            />
          </Field>
        </Modal>
      )}
    </div>
  )
}
