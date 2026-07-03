import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = { title: '', content: '', source_type: 'literature', authors: '', year: '', reference: '' }
const EMPTY_RESULTS = { query: '', local: [], external: [], external_error: null }
const ACCEPTED_DOCUMENTS = '.pdf,.docx,.xlsx,.csv,.txt'

const DOCUMENT_STATUS_LABEL = {
  uploaded: 'загружен',
  parsed: 'распарсен',
  failed: 'ошибка',
  unsupported: 'не поддерживается',
}

const WORK_TYPE_LABEL = {
  article: 'Статья',
  book: 'Книга',
  dataset: 'Набор данных',
  dissertation: 'Диссертация',
  preprint: 'Препринт',
  report: 'Отчет',
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

function documentStatusLabel(status) {
  return DOCUMENT_STATUS_LABEL[status] || status || 'unknown'
}

function documentMeta(document) {
  const parts = [
    document.file_type?.toUpperCase(),
    `${document.chunk_count || 0} чанков`,
    `${document.table_count || 0} таблиц`,
  ]
  return parts.filter(Boolean).join(' / ')
}

function documentTitle(document) {
  return compactText(document.metadata?.title) || document.filename
}

export default function KnowledgePanel({
  sources,
  documents = [],
  onAdd,
  onDelete,
  onSearch,
  onImportOpenAlex,
  onUploadDocument,
  onDeleteDocument,
}) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [importingKey, setImportingKey] = useState(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [deletingDocumentId, setDeletingDocumentId] = useState(null)

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

  async function uploadSelectedFile() {
    if (!selectedFile || !onUploadDocument) return
    setUploading(true)
    try {
      await onUploadDocument(selectedFile)
      setSelectedFile(null)
      setFileInputKey((value) => value + 1)
    } finally {
      setUploading(false)
    }
  }

  async function removeDocument(id) {
    if (!onDeleteDocument) return
    setDeletingDocumentId(id)
    try {
      await onDeleteDocument(id)
    } finally {
      setDeletingDocumentId(null)
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>База знаний</h3>
        <span className="count">{sources.length + documents.length}</span>
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
            Поиск идет по источникам проекта и по внешнему источнику. Внешние статьи можно сразу добавить в базу.
          </p>
        </div>

        <div className="document-upload">
          <div className="doc-upload-row">
            <input
              key={fileInputKey}
              className="doc-file-input"
              type="file"
              accept={ACCEPTED_DOCUMENTS}
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
            />
            <button
              className="btn sm primary"
              disabled={!selectedFile || uploading}
              onClick={uploadSelectedFile}
            >
              {uploading ? 'Загрузка...' : 'Загрузить файл'}
            </button>
          </div>
          <p className="section-hint">
            PDF, DOCX, XLSX, CSV и TXT сохраняются как документы проекта и парсятся отдельно от генерации гипотез.
          </p>
        </div>

        {documents.length > 0 && (
          <div className="document-list">
            <div className="source-list-title">Файлы проекта</div>
            {documents.map((document) => (
              <div className="document-item" key={document.id}>
                <div className="document-top">
                  <span className={`doc-status status-${document.parse_status}`}>
                    {documentStatusLabel(document.parse_status)}
                  </span>
                  <span className="document-title">{documentTitle(document)}</span>
                  <button
                    className="btn ghost sm danger"
                    disabled={deletingDocumentId === document.id}
                    title="Удалить файл"
                    onClick={() => removeDocument(document.id)}
                  >
                    ×
                  </button>
                </div>
                <div className="document-meta">
                  <span>{document.filename}</span>
                  <span>{documentMeta(document)}</span>
                </div>
                {document.raw_text_preview && (
                  <div className="document-preview">{document.raw_text_preview}</div>
                )}
              </div>
            ))}
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
                    {source.reference && <div className="search-links">{source.reference}</div>}
                  </div>
                ))
              )}
            </div>

            <div className="search-group">
              <div className="search-group-head">
                <h4>Внешний источник</h4>
                <span>{results.external.length}</span>
              </div>
              {results.external_error && (
                <p className="section-hint search-error">{results.external_error}</p>
              )}
              {!results.external_error && results.external.length === 0 ? (
                <p className="section-hint">Внешний источник ничего не вернул по этому запросу.</p>
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
                        <button
                          className={`btn sm ${source.already_added ? '' : 'primary'}`}
                          disabled={disabled}
                          onClick={() => importResult(source)}
                        >
                          {importingKey === key ? 'Добавление...' : source.already_added ? 'Уже добавлен' : 'Добавить'}
                        </button>
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
              <p className="section-hint" style={{ marginTop: -4 }}>
                По запросу «{results.query}» ничего не найдено.
              </p>
            )}
          </div>
        )}

        {sources.length > 0 && <div className="source-list-title">Все источники проекта</div>}
        {sources.length === 0 && documents.length === 0 && (
          <p className="section-hint" style={{ padding: '10px 0' }}>
            Добавьте литературу, отчеты и эксперименты. На их основе будут строиться гипотезы.
          </p>
        )}
        {sources.map((source) => (
          <div className="source" key={source.id}>
            <div className="s-top">
              <span className={`type-tag type-${source.source_type}`}>{TYPE_LABEL[source.source_type] || source.source_type}</span>
              <span className="s-title">{displayTitle(source)}</span>
              <button className="btn ghost sm danger" title="Удалить" onClick={() => onDelete(source.id)}>✕</button>
            </div>
            {(metaText(source) || sourceDescription(source)) && (
              <div className="s-excerpt">
                {metaText(source) && (
                  <b style={{ color: 'var(--ink-soft)' }}>
                    {metaText(source)}
                    {sourceDescription(source) ? ' - ' : ''}
                  </b>
                )}
                {sourceDescription(source)}
              </div>
            )}
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
