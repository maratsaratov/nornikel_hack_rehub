import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = { title: '', content: '', source_type: 'literature', authors: '', year: '', reference: '' }
const EMPTY_RESULTS = { query: '', local: [], external: [], external_error: null }
const ACCEPTED_DOCUMENTS = '.pdf,.docx,.xlsx,.csv,.txt'
const MAX_DOCUMENT_UPLOAD_MB = 25
const MAX_DOCUMENT_UPLOAD_BYTES = MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024

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
  if (Array.isArray(value)) return value.filter(Boolean).join(', ')
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

function previewText(value, limit = 180) {
  const text = compactText(value).replace(/\s+/g, ' ')
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit).trim()}...` : text
}

function fileSizeMb(size) {
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`
}

function displayTitle(item) {
  return compactText(item?.title || item?.display_name || item?.filename) || 'Без названия'
}

function sourceMeta(item) {
  const parts = [
    TYPE_LABEL[item?.source_type] || WORK_TYPE_LABEL[item?.work_type] || compactText(item?.source_type || item?.type),
    compactText(item?.authors),
    compactText(item?.year || item?.publication_year),
    compactText(item?.reference || item?.doi),
  ]
  return parts.filter(Boolean).join(' · ')
}

function sourceDescription(item) {
  return previewText(item?.content || item?.abstract || item?.description)
}

function sourceOriginBadge(item) {
  const origin = compactText(item?.origin).toLowerCase()
  if (origin === 'openalex') return 'OpenAlex'
  if (item?.is_external) return 'External'
  return ''
}

function resultKey(item, prefix) {
  return compactText(item?.openalex_id || item?.id || item?.doi || `${prefix}-${displayTitle(item)}-${sourceMeta(item)}`)
}

function documentStatus(doc) {
  return compactText(doc?.parse_status || 'uploaded').toLowerCase()
}

function documentStatusLabel(doc) {
  const status = documentStatus(doc)
  return DOCUMENT_STATUS_LABEL[status] || status
}

function documentMeta(doc) {
  const metadata = doc?.metadata_json || doc?.metadata || {}
  const parts = [
    compactText(doc?.file_type).toUpperCase(),
    compactText(metadata.title),
    compactText(metadata.language),
    compactText(metadata.year || metadata.date),
  ]
  return parts.filter(Boolean).join(' · ')
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
  const [results, setResults] = useState(EMPTY_RESULTS)
  const [searching, setSearching] = useState(false)
  const [importingKey, setImportingKey] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadError, setUploadError] = useState('')
  const [fileInputKey, setFileInputKey] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [deletingDocumentId, setDeletingDocumentId] = useState(null)

  const updateField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await onAdd({
        ...form,
        year: form.year ? Number(form.year) : null,
      })
      setForm(EMPTY)
      setOpen(false)
    } finally {
      setSaving(false)
    }
  }

  async function runSearch() {
    const term = query.trim()
    if (!term || !onSearch) {
      setResults(EMPTY_RESULTS)
      return
    }

    setSearching(true)
    try {
      const payload = await onSearch(term)
      setResults({
        ...EMPTY_RESULTS,
        ...payload,
        query: payload?.query || term,
        local: payload?.local || [],
        external: payload?.external || [],
      })
    } finally {
      setSearching(false)
    }
  }

  function clearSearch() {
    setQuery('')
    setResults(EMPTY_RESULTS)
  }

  async function importResult(item) {
    if (!onImportOpenAlex) return
    const key = resultKey(item, 'external')
    setImportingKey(key)
    try {
      await onImportOpenAlex(item)
      setResults((prev) => ({
        ...prev,
        external: prev.external.map((entry) => (
          resultKey(entry, 'external') === key
            ? { ...entry, already_added: true }
            : entry
        )),
      }))
    } finally {
      setImportingKey('')
    }
  }

  async function uploadSelectedFile() {
    if (!selectedFile || !onUploadDocument) return
    if (selectedFile.size > MAX_DOCUMENT_UPLOAD_BYTES) {
      setUploadError(`Файл ${fileSizeMb(selectedFile.size)} больше лимита ${MAX_DOCUMENT_UPLOAD_MB} МБ`)
      return
    }
    setUploading(true)
    try {
      await onUploadDocument(selectedFile)
      setSelectedFile(null)
      setUploadError('')
      setFileInputKey((key) => key + 1)
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0] || null
    if (!file) {
      setSelectedFile(null)
      setUploadError('')
      return
    }
    if (file.size > MAX_DOCUMENT_UPLOAD_BYTES) {
      setSelectedFile(null)
      setUploadError(`Файл ${fileSizeMb(file.size)} больше лимита ${MAX_DOCUMENT_UPLOAD_MB} МБ`)
      setFileInputKey((key) => key + 1)
      return
    }
    setSelectedFile(file)
    setUploadError('')
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

  const selectedFileName = selectedFile?.name || 'Выберите файл для парсинга'

  return (
    <div className="card">
      <div className="card-head">
        <h3>База знаний</h3>
        <span className="count">{sources.length + documents.length}</span>
        <div className="spacer" />
        <button className="btn primary" onClick={() => setOpen(true)}>Добавить источник</button>
      </div>

      <div className="card-body knowledge-panel">
        <div className="source-tools">
          <section className="source-tool-card source-tool-card--search">
            <div className="tool-card-head">
              <div>
                <span className="tool-eyebrow">Literature Search</span>
                <h4>Поиск литературы</h4>
              </div>
              <span className="tool-chip">Project + OpenAlex</span>
            </div>

            <div className="source-search-row">
              <div className="source-search-box">
                <span className="source-search-icon">⌕</span>
                <input
                  className="source-search-input"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') runSearch() }}
                  placeholder="Название статьи, DOI, автор или тема"
                />
              </div>
              <button className="btn primary" onClick={runSearch} disabled={searching || !query.trim()}>
                {searching ? 'Ищем...' : 'Найти'}
              </button>
              {results.query && (
                <button className="btn ghost" onClick={clearSearch}>Сбросить</button>
              )}
            </div>

            {results.query && (
              <div className="search-results">
                <div className="search-group">
                  <div className="search-group-head">
                    <span>В проекте</span>
                    <span className="count">{results.local.length}</span>
                  </div>
                  {results.local.length === 0 && <p className="section-hint">Совпадений в добавленных источниках нет.</p>}
                  {results.local.map((item) => (
                    <div className="search-item" key={resultKey(item, 'local')}>
                      <div className="search-item-heading">
                        <div className="search-item-title">{displayTitle(item)}</div>
                        {sourceOriginBadge(item) && (
                          <div className="source-badges">
                            <span className="source-badge source-badge--external">{sourceOriginBadge(item)}</span>
                          </div>
                        )}
                      </div>
                      {sourceMeta(item) && <div className="search-item-meta">{sourceMeta(item)}</div>}
                      {sourceDescription(item) && <p className="search-item-desc">{sourceDescription(item)}</p>}
                    </div>
                  ))}
                </div>

                <div className="search-group search-group--external">
                  <div className="search-group-head">
                    <span>OpenAlex</span>
                    <span className="count">{results.external.length}</span>
                  </div>
                  {results.external_error && <p className="search-error">{results.external_error}</p>}
                  {results.external.length === 0 && !results.external_error && (
                    <p className="section-hint">Внешних результатов нет.</p>
                  )}
                  {results.external.map((item) => {
                    const key = resultKey(item, 'external')
                    return (
                      <div className="search-item" key={key}>
                        <div className="search-actions">
                          <div>
                            <div className="search-item-heading">
                              <div className="search-item-title">{displayTitle(item)}</div>
                              <div className="source-badges">
                                <span className="source-badge source-badge--external">OpenAlex</span>
                                {item?.already_added && <span className="source-badge source-badge--existing">In project</span>}
                              </div>
                            </div>
                            {sourceMeta(item) && <div className="search-item-meta">{sourceMeta(item)}</div>}
                          </div>
                          <button
                            className="btn secondary btn-compact"
                            onClick={() => importResult(item)}
                            disabled={importingKey === key || item?.already_added}
                          >
                            {importingKey === key ? 'Импорт...' : 'Импорт'}
                          </button>
                        </div>
                        {sourceDescription(item) && <p className="search-item-desc">{sourceDescription(item)}</p>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </section>

          <section className="source-tool-card source-tool-card--upload">
            <div className="tool-card-head">
              <div>
                <span className="tool-eyebrow">Document Parser</span>
                <h4>Загрузка файлов</h4>
              </div>
              <span className="tool-chip">PDF DOCX XLSX CSV TXT</span>
            </div>
            <p className="section-hint">Файлы до {MAX_DOCUMENT_UPLOAD_MB} МБ сохраняются и парсятся отдельно от генератора гипотез.</p>
            <div className="doc-upload-row">
              <label className={`doc-file-drop ${selectedFile ? 'has-file' : ''}`}>
                <input
                  key={fileInputKey}
                  className="doc-file-input"
                  type="file"
                  accept={ACCEPTED_DOCUMENTS}
                  onChange={handleFileChange}
                />
                <span className="doc-file-mark">FILE</span>
                <span className="doc-file-copy">
                  <strong>{selectedFileName}</strong>
                  <small>Нажмите, чтобы выбрать PDF, DOCX, XLSX, CSV или TXT до {MAX_DOCUMENT_UPLOAD_MB} МБ</small>
                </span>
              </label>
              <button className="btn primary" onClick={uploadSelectedFile} disabled={!selectedFile || uploading}>
                {uploading ? 'Загрузка...' : 'Загрузить'}
              </button>
            </div>
            {uploadError && <p className="upload-error">{uploadError}</p>}
          </section>
        </div>

        {documents.length > 0 && (
          <div className="document-list">
            <div className="list-section-head">
              <span>Загруженные файлы</span>
              <span className="count">{documents.length}</span>
            </div>
            {documents.map((doc) => {
              const status = documentStatus(doc)
              return (
                <div className="document-item" key={doc.id}>
                  <div className="doc-main">
                    <div className="doc-title-row">
                      <strong>{displayTitle(doc)}</strong>
                      <span className={`doc-status status-${status}`}>{documentStatusLabel(doc)}</span>
                    </div>
                    {documentMeta(doc) && <p className="doc-meta">{documentMeta(doc)}</p>}
                  </div>
                  {onDeleteDocument && (
                    <button
                      className="btn secondary btn-compact"
                      onClick={() => removeDocument(doc.id)}
                      disabled={deletingDocumentId === doc.id}
                    >
                      {deletingDocumentId === doc.id ? 'Удаление...' : 'Удалить'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {sources.length === 0 && documents.length === 0 && (
          <p className="section-hint">Добавьте статьи, отчеты, патенты или файлы, чтобы сформировать базу знаний проекта.</p>
        )}

        {sources.map((s) => (
          <div className="source" key={s.id}>
            <div className="s-top">
              <strong>{displayTitle(s)}</strong>
              <button className="btn secondary btn-compact" onClick={() => onDelete(s.id)}>Удалить</button>
            </div>
            <p className="s-meta">{sourceMeta(s)}</p>
            <p>{sourceDescription(s)}</p>
          </div>
        ))}
      </div>

      {open && (
        <Modal title="Новый источник" onClose={() => setOpen(false)}>
          <form onSubmit={submit} className="form-grid">
            <Field label="Название">
              <input value={form.title} onChange={updateField('title')} required />
            </Field>
            <Field label="Тип">
              <select value={form.source_type} onChange={updateField('source_type')}>
                {Object.entries(TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Field label="Авторы">
              <input value={form.authors} onChange={updateField('authors')} />
            </Field>
            <Field label="Год">
              <input type="number" min="1900" max="2100" value={form.year} onChange={updateField('year')} />
            </Field>
            <Field label="Ссылка / DOI">
              <input value={form.reference} onChange={updateField('reference')} />
            </Field>
            <Field label="Содержание">
              <textarea rows="8" value={form.content} onChange={updateField('content')} required />
            </Field>
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Отмена</button>
              <button type="submit" className="btn primary" disabled={saving}>{saving ? 'Сохраняем...' : 'Сохранить'}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
