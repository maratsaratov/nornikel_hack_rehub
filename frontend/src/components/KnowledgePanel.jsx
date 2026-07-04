import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { Modal } from './ui.jsx'

const TYPE_META = {
  article: { label: 'Научные статьи', cardLabel: 'Научная статья' },
  literature: { label: 'Литература', cardLabel: 'Литература' },
  patent: { label: 'Патенты', cardLabel: 'Патент' },
  technical: { label: 'Тех. документация', cardLabel: 'Тех. документация' },
}

const YEAR_META = {
  2026: '2026',
  2025: '2025',
  2024: '2024',
  earlier: 'Ранее',
}

const CARD_METRICS = [
  { novelty: 'Высокая', value: 9 },
  { novelty: 'Средняя', value: 8 },
  { novelty: 'Низкая', value: 9 },
  { novelty: 'Высокая', value: 7 },
  { novelty: 'Экстремальная', value: 10 },
  { novelty: 'Средняя', value: 9 },
]

const ACCEPTED_DOCUMENT_EXTENSIONS = ['pdf', 'docx', 'xlsx', 'csv', 'txt']
const MAX_DOCUMENT_UPLOAD_MB = 25
const EMPTY_OPENALEX_RESULTS = { query: '', local: [], external: [], external_error: null }
const MIN_OPENALEX_QUERY_LENGTH = 2
const OPENALEX_SEARCH_DEBOUNCE_MS = 320

function compactText(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join(', ')
  if (value === null || value === undefined) return ''
  return String(value).replace(/\s+/g, ' ').trim()
}

function clipped(value, limit = 165) {
  const text = compactText(value)
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit).trim()}...` : text
}

function summaryKey(value) {
  return compactText(value).toLowerCase().replace(/[^a-zа-яё0-9]+/gi, '')
}

function looksLikeTitleOnlySummary(value, ...candidates) {
  const summary = summaryKey(value)
  if (!summary || summary.length < 12) return true
  return candidates.some((candidate) => {
    const current = summaryKey(candidate)
    if (!current) return false
    return summary === current
      || (summary.length <= current.length + 12 && (summary.startsWith(current) || current.startsWith(summary)))
  })
}

function normalizeType(source, index) {
  if (source?.source_type === 'patent') return 'patent'
  if (source?.source_type === 'report' || source?.source_type === 'experiment') return 'technical'
  if (source?.origin === 'openalex') return 'article'
  return index % 2 === 0 ? 'article' : 'literature'
}

function sourceYear(source) {
  const rawYear = Number(source?.year || source?.publication_year || source?.metadata?.year)
  if (rawYear >= 2024 && rawYear <= 2026) {
    return { key: String(rawYear), label: String(rawYear) }
  }
  if (rawYear) {
    return { key: 'earlier', label: String(rawYear) }
  }
  return { key: 'earlier', label: 'Ранее' }
}

function sourceSummary(source) {
  return clipped(
    source?.excerpt
      || source?.summary
      || source?.metadata?.summary
      || source?.content
      || source?.abstract
      || source?.description
      || source?.metadata?.description
      || source?.raw_text_preview
      || 'Описание появится после обработки источника.',
  )
}

function sourceAuthor(source) {
  return compactText(source?.authors || source?.metadata?.authors || source?.origin || 'Внутренняя база')
}

function sourceTypeLabel(source, fallbackLabel = 'Источник') {
  const rawType = compactText(source?.source_type).toLowerCase()
  if (rawType === 'report') return 'Отчёт'
  if (rawType === 'experiment') return 'Эксперимент'
  if (rawType === 'patent') return 'Патент'
  if (rawType === 'literature') return 'Литература'
  return fallbackLabel
}

function sourceOriginLabel(source) {
  const origin = compactText(source?.origin).toLowerCase()
  if (!origin || origin === 'manual') return 'Внутренняя база'
  if (origin === 'openalex') return 'OpenAlex'
  return compactText(source?.origin)
}

function formatTimestamp(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return compactText(value)
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function documentParseStatusLabel(value) {
  const status = compactText(value).toLowerCase()
  if (status === 'parsed') return 'Обработан'
  if (status === 'uploaded') return 'Загружен'
  if (status === 'failed') return 'Ошибка парсинга'
  if (status === 'unsupported') return 'Формат не поддерживается'
  return compactText(value)
}

function fileExtension(filename) {
  const parts = String(filename || '').toLowerCase().split('.')
  return parts.length > 1 ? parts.pop() : ''
}

function openAlexTitle(item) {
  return compactText(item?.title || item?.display_name) || 'Без названия'
}

function openAlexResultKey(item, prefix = 'external') {
  return compactText(
    item?.openalex_id
      || item?.external_id
      || item?.id
      || item?.doi
      || `${prefix}-${openAlexTitle(item)}`,
  )
}

function openAlexMeta(item) {
  const authors = Array.isArray(item?.authors)
    ? item.authors.filter(Boolean).join(', ')
    : item?.authors

  return [
    compactText(authors),
    compactText(item?.year || item?.publication_year || item?.metadata?.year),
    compactText(item?.reference || item?.doi),
  ].filter(Boolean).join(' · ')
}

function openAlexDescription(item) {
  return clipped(
    item?.abstract
      || item?.description
      || item?.content
      || item?.excerpt
      || item?.raw_text_preview,
    140,
  )
}

function buildOpenAlexResults(query, payload = {}) {
  return {
    ...EMPTY_OPENALEX_RESULTS,
    ...payload,
    query: payload?.query || query,
    local: payload?.local || [],
    external: payload?.external || [],
  }
}

function makeItems(sources, documents) {
  const sourceItems = sources.map((source, index) => {
    const type = normalizeType(source, index)
    const metrics = CARD_METRICS[index % CARD_METRICS.length]
    const year = sourceYear(source)
    return {
      id: `source-${source.id}`,
      entityId: source.id,
      kind: 'source',
      type,
      label: TYPE_META[type].cardLabel,
      title: compactText(source.title || source.display_name) || 'Без названия',
      summary: sourceSummary(source),
      author: sourceAuthor(source),
      origin: source?.origin || 'manual',
      isExternal: Boolean(source?.is_external || (source?.origin && source.origin !== 'manual')),
      yearKey: year.key,
      yearLabel: year.label,
      novelty: metrics.novelty,
      value: metrics.value,
    }
  })

  const documentItems = documents.map((document, index) => {
    const itemIndex = sources.length + index
    const metrics = CARD_METRICS[itemIndex % CARD_METRICS.length]
    const year = sourceYear(document)
    return {
      id: `document-${document.id}`,
      entityId: document.id,
      kind: 'document',
      type: 'article',
      label: compactText(document.file_type).toUpperCase() || 'Файл',
      title: compactText(document.metadata?.title || document.filename) || 'Загруженный файл',
      summary: sourceSummary(document),
      author: sourceAuthor(document),
      yearKey: year.key,
      yearLabel: year.label,
      novelty: metrics.novelty,
      value: metrics.value,
    }
  })

  return [...sourceItems, ...documentItems]
}

function Icon({ name }) {
  const paths = {
    upload: (
      <>
        <path d="M12 15V4" />
        <path d="m8 8 4-4 4 4" />
        <path d="M5 19h14" />
      </>
    ),
    link: (
      <>
        <path d="M10.4 13.6a5 5 0 0 0 7.1 0l1.1-1.1a5 5 0 0 0-7.1-7.1l-.7.7" />
        <path d="M13.6 10.4a5 5 0 0 0-7.1 0l-1.1 1.1a5 5 0 0 0 7.1 7.1l.7-.7" />
      </>
    ),
    search: (
      <>
        <circle cx="11" cy="11" r="6" />
        <path d="m16 16 4 4" />
      </>
    ),
    file: (
      <>
        <path d="M8 4h6l4 4v12H8z" />
        <path d="M14 4v5h5" />
      </>
    ),
    book: (
      <>
        <path d="M5 5h9a3 3 0 0 1 3 3v11H8a3 3 0 0 0-3 3z" />
        <path d="M5 5v17" />
      </>
    ),
    filter: (
      <>
        <path d="M4 6h16" />
        <path d="M7 12h10" />
        <path d="M10 18h4" />
      </>
    ),
    plus: (
      <>
        <path d="M12 5v14" />
        <path d="M5 12h14" />
      </>
    ),
    chevron: <path d="m9 6 6 6-6 6" />,
    check: <path d="m5 12 4 4 10-10" />,
    trash: (
      <>
        <path d="M5 7h14" />
        <path d="M9 7V5h6v2" />
        <path d="m8 7 1 12h6l1-12" />
      </>
    ),
  }

  return (
    <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  )
}

function FilterRow({ checked, label, count, onChange }) {
  return (
    <label className="filter-row">
      <span>
        <input type="checkbox" checked={checked} onChange={onChange} />
        {label}
      </span>
      <strong>{count}</strong>
    </label>
  )
}

function KnowledgeCard({ item, selected, onToggle, onOpenDetails, onDeleteSource, onDeleteDocument }) {
  const isBook = item.type === 'literature'

  return (
    <article className={`source-card ${selected ? 'source-card--selected' : ''}`}>
      <div className="source-card__head">
        <div className="source-card__badges">
          <span className={`source-kind source-kind--${item.type}`}>
            <Icon name={isBook ? 'book' : 'file'} />
            {item.label}
          </span>
          {item.isExternal && (
            <span className="source-origin-badge" title="Внешний источник">
              <span className="source-origin-badge__dot" />
              Внешний
            </span>
          )}
        </div>
        <label className="select-box" aria-label={`Выбрать ${item.title}`}>
          <input type="checkbox" checked={selected} onChange={onToggle} />
          <span><Icon name="check" /></span>
        </label>
      </div>

      <h3>{item.title}</h3>
      <p>{item.summary}</p>

      <div className="source-card__metrics">
        <div>
          <span>Новизна</span>
          <strong>{item.novelty}</strong>
        </div>
        <div>
          <span>Ценность</span>
          <strong>{item.value}/10</strong>
        </div>
      </div>

      <footer className="source-card__footer">
        <span>{item.author}<small>{item.yearLabel}</small></span>
        <div className="source-card__actions">
          <button type="button" onClick={() => onOpenDetails?.(item)}>Подробнее</button>
          {item.kind === 'source' && (
            <>
              <button type="button" onClick={() => onOpenDetails?.(item)}>Подробнее</button>
              <button className="source-card__delete" type="button" onClick={() => onDeleteSource?.(item)} aria-label="Удалить источник">
                <Icon name="trash" />
              </button>
            </>
          )}
          {item.kind === 'document' && onDeleteDocument && (
            <button className="source-card__delete" type="button" onClick={() => onDeleteDocument(item)} aria-label="Удалить файл">
              <Icon name="trash" />
            </button>
          )}
        </div>
      </footer>
    </article>
  )
}

function SourceDetailsModal({ item, source, loading, error, onClose }) {
  const details = source || item || {}
  const metaItems = [
    { label: 'Тип', value: sourceTypeLabel(details, item?.label || 'Источник') },
    { label: 'Происхождение', value: sourceOriginLabel(details) },
    { label: 'Авторы', value: compactText(details?.authors) },
    { label: 'Год', value: compactText(details?.year) },
    { label: 'Ссылка', value: compactText(details?.reference) },
    { label: 'Добавлен', value: formatTimestamp(details?.created_at) },
  ].filter((entry) => entry.value)

  return (
    <Modal
      title={compactText(details?.title) || 'Источник'}
      onClose={onClose}
      className="modal--source-details"
      footer={(
        <button className="btn primary" type="button" onClick={onClose}>
          Закрыть
        </button>
      )}
    >
      <div className="source-details">
        <div className="source-details__badges">
          <span className={`source-kind source-kind--${item?.type || 'article'}`}>
            <Icon name={item?.type === 'literature' ? 'book' : 'file'} />
            {item?.label || 'Источник'}
          </span>
          {(details?.is_external || item?.isExternal) && (
            <span className="source-origin-badge">
              <span className="source-origin-badge__dot" />
              Внешний источник
            </span>
          )}
        </div>

        {metaItems.length > 0 && (
          <div className="source-details__meta">
            {metaItems.map((entry) => (
              <div key={entry.label} className="source-details__meta-item">
                <span>{entry.label}</span>
                <strong>{entry.value}</strong>
              </div>
            ))}
          </div>
        )}

        {loading && <div className="source-details__state">Загружаем данные источника...</div>}
        {!loading && error && <div className="source-details__state source-details__state--error">{error}</div>}

        {!loading && (
          <>
            <section className="source-details__section">
              <h4>Краткое описание</h4>
              <p>{compactText(details?.excerpt) || item?.summary || 'Описание отсутствует.'}</p>
            </section>

            <section className="source-details__section">
              <h4>Полный текст</h4>
              <div className="source-details__content">
                {String(details?.content || '').trim() || 'Полный текст для этого источника не сохранён.'}
              </div>
            </section>
          </>
        )}
      </div>
    </Modal>
  )
}

function DocumentDetailsModal({ item, document, loading, error, onClose }) {
  const details = document || item || {}
  const metaItems = [
    { label: 'Тип файла', value: compactText(details?.file_type || item?.label).toUpperCase() },
    { label: 'Статус', value: documentParseStatusLabel(details?.parse_status) },
    { label: 'Авторы', value: compactText(details?.metadata?.authors || details?.authors) },
    { label: 'Год', value: compactText(details?.metadata?.year || details?.year) },
    { label: 'Фрагменты', value: Number.isFinite(Number(details?.chunk_count)) ? String(details.chunk_count) : '' },
    { label: 'Таблицы', value: Number.isFinite(Number(details?.table_count)) ? String(details.table_count) : '' },
    { label: 'Обновлен', value: formatTimestamp(details?.updated_at) },
    { label: 'Добавлен', value: formatTimestamp(details?.created_at) },
  ].filter((entry) => entry.value)

  const title = compactText(
    details?.metadata?.title
      || details?.filename
      || item?.title,
  ) || 'Документ'

  const savedDescription = compactText(
    details?.summary
      || details?.metadata?.summary
      || details?.description
      || details?.metadata?.description
      || details?.raw_text_preview
      || item?.summary,
  )
  const extractedDescription = clipped(details?.raw_text || details?.raw_text_preview, 260)
  const description = !savedDescription || looksLikeTitleOnlySummary(
    savedDescription,
    title,
    details?.metadata?.title,
    details?.filename,
    item?.title,
  )
    ? extractedDescription || savedDescription
    : savedDescription

  const content = String(details?.raw_text || details?.raw_text_preview || '').trim()

  return (
    <Modal
      title={title}
      onClose={onClose}
      className="modal--source-details"
      footer={(
        <button className="btn primary" type="button" onClick={onClose}>
          Закрыть
        </button>
      )}
    >
      <div className="source-details">
        <div className="source-details__badges">
          <span className={`source-kind source-kind--${item?.type || 'article'}`}>
            <Icon name="file" />
            {item?.label || 'Документ'}
          </span>
        </div>

        {metaItems.length > 0 && (
          <div className="source-details__meta">
            {metaItems.map((entry) => (
              <div key={entry.label} className="source-details__meta-item">
                <span>{entry.label}</span>
                <strong>{entry.value}</strong>
              </div>
            ))}
          </div>
        )}

        {loading && <div className="source-details__state">Загружаем данные файла...</div>}
        {!loading && error && <div className="source-details__state source-details__state--error">{error}</div>}

        {!loading && (
          <>
            <section className="source-details__section">
              <h4>Краткое описание файла</h4>
              <p>{description || 'Описание файла пока не сформировано.'}</p>
            </section>

            <section className="source-details__section">
              <h4>Извлеченный текст</h4>
              <div className="source-details__content">
                {content || 'Парсер еще не сохранил извлеченный текст для этого файла.'}
              </div>
            </section>
          </>
        )}
      </div>
    </Modal>
  )
}

export default function KnowledgePanel({
  sources,
  documents = [],
  documentTypes = ACCEPTED_DOCUMENT_EXTENSIONS,
  maxUploadMb = MAX_DOCUMENT_UPLOAD_MB,
  onDelete,
  onSearch,
  onImportOpenAlex,
  onUploadDocument,
  onDeleteDocument,
}) {
  const [query, setQuery] = useState('')
  const [doi, setDoi] = useState('')
  const [doiStatus, setDoiStatus] = useState('')
  const [openAlexResults, setOpenAlexResults] = useState(EMPTY_OPENALEX_RESULTS)
  const [searchingOpenAlex, setSearchingOpenAlex] = useState(false)
  const [importingOpenAlexKey, setImportingOpenAlexKey] = useState('')
  const [uploadStatus, setUploadStatus] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [openedSourceItem, setOpenedSourceItem] = useState(null)
  const [openedSource, setOpenedSource] = useState(null)
  const [openingSource, setOpeningSource] = useState(false)
  const [openedSourceError, setOpenedSourceError] = useState('')
  const [typeFilters, setTypeFilters] = useState({
    article: true,
    literature: true,
    patent: false,
    technical: false,
  })
  const [yearFilters, setYearFilters] = useState({
    2026: true,
    2025: true,
    2024: true,
    earlier: true,
  })
  const fileInputRef = useRef(null)
  const selectedOnceRef = useRef(false)
  const openAlexRequestRef = useRef(0)
  const sourceRequestRef = useRef(0)
  const acceptedDocumentExtensions = useMemo(() => {
    const normalized = (documentTypes || [])
      .map((ext) => String(ext || '').toLowerCase().replace(/^\./, ''))
      .filter(Boolean)
    return normalized.length ? normalized : ACCEPTED_DOCUMENT_EXTENSIONS
  }, [documentTypes])
  const acceptedDocuments = useMemo(
    () => acceptedDocumentExtensions.map((ext) => `.${ext}`).join(','),
    [acceptedDocumentExtensions],
  )
  const maxDocumentUploadMb = Number(maxUploadMb) > 0 ? Number(maxUploadMb) : MAX_DOCUMENT_UPLOAD_MB
  const maxDocumentUploadBytes = maxDocumentUploadMb * 1024 * 1024

  const libraryItems = useMemo(() => makeItems(sources, documents), [sources, documents])
  const filterCounts = useMemo(() => {
    const counts = {
      article: 0,
      literature: 0,
      patent: 0,
      technical: 0,
      2026: 0,
      2025: 0,
      2024: 0,
      earlier: 0,
    }

    libraryItems.forEach((item) => {
      counts[item.type] = (counts[item.type] || 0) + 1
      counts[item.yearKey] = (counts[item.yearKey] || 0) + 1
    })

    return counts
  }, [libraryItems])

  useEffect(() => {
    if (selectedOnceRef.current || libraryItems.length === 0) return
    selectedOnceRef.current = true
    setSelectedIds(new Set([libraryItems[0].id]))
  }, [libraryItems])

  useEffect(() => {
    const term = doi.trim()
    if (!term || term.length < MIN_OPENALEX_QUERY_LENGTH || !onSearch) {
      setSearchingOpenAlex(false)
      setOpenAlexResults(EMPTY_OPENALEX_RESULTS)
      return undefined
    }

    const requestId = openAlexRequestRef.current + 1
    openAlexRequestRef.current = requestId

    const timerId = window.setTimeout(async () => {
      setSearchingOpenAlex(true)
      try {
        const results = await onSearch(term)
        if (openAlexRequestRef.current !== requestId) return
        setOpenAlexResults(buildOpenAlexResults(term, results))
      } catch (error) {
        if (openAlexRequestRef.current !== requestId) return
        setOpenAlexResults(buildOpenAlexResults(term, { external_error: error.message }))
      } finally {
        if (openAlexRequestRef.current === requestId) {
          setSearchingOpenAlex(false)
        }
      }
    }, OPENALEX_SEARCH_DEBOUNCE_MS)

    return () => window.clearTimeout(timerId)
  }, [doi, onSearch])

  const filteredItems = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return libraryItems.filter((item) => {
      const matchesType = Boolean(typeFilters[item.type])
      const matchesYear = Boolean(yearFilters[item.yearKey])
      const matchesQuery = !needle
        || item.title.toLowerCase().includes(needle)
        || item.summary.toLowerCase().includes(needle)
      return matchesType && matchesYear && matchesQuery
    })
  }, [libraryItems, query, typeFilters, yearFilters])

  const selectedVisibleCount = filteredItems.filter((item) => selectedIds.has(item.id)).length

  function toggleSelection(itemId) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  function selectAllVisible() {
    // TODO: сохранить выбранные источники на backend, когда появится сущность набора источников для генерации.
    setSelectedIds((prev) => {
      const next = new Set(prev)
      filteredItems.forEach((item) => next.add(item.id))
      return next
    })
  }

  function clearSelection(itemId) {
    setSelectedIds((prev) => {
      if (!prev.has(itemId)) return prev
      const next = new Set(prev)
      next.delete(itemId)
      return next
    })
  }

  function closeSourceDetails() {
    sourceRequestRef.current += 1
    setOpenedSourceItem(null)
    setOpenedSource(null)
    setOpeningSource(false)
    setOpenedSourceError('')
  }

  async function openSourceDetails(item) {
    if (!item) return

    const requestId = sourceRequestRef.current + 1
    sourceRequestRef.current = requestId
    setOpenedSourceItem(item)
    setOpenedSource(null)
    setOpeningSource(true)
    setOpenedSourceError('')

    try {
      const payload = item.kind === 'document'
        ? await api.getDocument(item.entityId, true)
        : await api.getSource(item.entityId)
      if (sourceRequestRef.current !== requestId) return
      setOpenedSource(payload)
    } catch (error) {
      if (sourceRequestRef.current !== requestId) return
      setOpenedSourceError(error.message)
    } finally {
      if (sourceRequestRef.current === requestId) {
        setOpeningSource(false)
      }
    }
  }

  async function handleDeleteSource(item) {
    if (!item || !onDelete) return
    if (!window.confirm(`Удалить источник «${item.title}»?`)) return
    await onDelete(item.entityId)
    clearSelection(item.id)
    if (openedSourceItem?.id === item.id) closeSourceDetails()
  }

  async function handleDeleteDocument(item) {
    if (!item || !onDeleteDocument) return
    if (!window.confirm(`Удалить файл «${item.title}»?`)) return
    await onDeleteDocument(item.entityId)
    clearSelection(item.id)
    if (openedSourceItem?.id === item.id) closeSourceDetails()
  }

  async function handleFile(file) {
    if (!file || !onUploadDocument) return
    const extension = fileExtension(file.name)
    if (!acceptedDocumentExtensions.includes(extension)) {
      setUploadStatus(`Unsupported file type: .${extension || 'unknown'}`)
      return
    }
    if (file.size > maxDocumentUploadBytes) {
      setUploadStatus(`File exceeds ${maxDocumentUploadMb} MB limit`)
      return
    }
    setUploadStatus(`Uploading: ${file.name}`)
    try {
      await onUploadDocument(file)
      setUploadStatus(`${file.name} uploaded`)
    } catch (error) {
      setUploadStatus(error.message)
    }
  }

  async function importOpenAlexResult(item) {
    if (!item || !onImportOpenAlex) return
    if (item?.already_added) {
      setDoiStatus('Источник уже есть в библиотеке')
      return
    }

    const itemKey = openAlexResultKey(item)
    setImportingOpenAlexKey(itemKey)
    setDoiStatus('Добавляем источник...')
    try {
      await onImportOpenAlex(item)
      setDoi('')
      setOpenAlexResults(EMPTY_OPENALEX_RESULTS)
      setDoiStatus('Ссылка добавлена')
    } catch (error) {
      setDoiStatus(error.message)
    } finally {
      setImportingOpenAlexKey('')
    }
  }

  async function addDoi() {
    const value = doi.trim()
    if (!value || !onSearch || !onImportOpenAlex) return
    setDoiStatus('Ищем источник...')
    try {
      // TODO: заменить поиск OpenAlex прямым backend-резолвером DOI/URL, когда он появится.
      const results = openAlexResults.query === value
        ? openAlexResults
        : buildOpenAlexResults(value, await onSearch(value))
      setOpenAlexResults(results)
      const firstExternal = results.external?.find((item) => !item?.already_added) || results.external?.[0]
      if (!firstExternal) {
        setDoiStatus(results.external_error || 'Источник не найден')
        return
      }
      await importOpenAlexResult(firstExternal)
    } catch (error) {
      setDoiStatus(error.message)
    }
  }

  return (
    <section className="knowledge-screen">
      <div className="knowledge-screen__intro">
        <h1>База знаний</h1>
        <p>
          Персональная библиотека исследований: загружайте статьи, DOI и отчёты, отмечайте
          важные фрагменты и связывайте источники с проектами. Эта база создаёт единый контекст,
          который ИИ использует при генерации и ранжировании гипотез.
        </p>
      </div>

      <section className="import-block">
        <div className="import-block__heading">
          <h2>Импорт данных</h2>
          <span>Поддерживаемые форматы: {acceptedDocumentExtensions.map((ext) => ext.toUpperCase()).join(', ')}</span>
        </div>

        <div className="import-grid">
          <button
            className={`file-drop ${dragOver ? 'file-drop--active' : ''}`}
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragOver(false)
              handleFile(event.dataTransfer.files?.[0])
            }}
          >
            <span className="file-drop__icon"><Icon name="upload" /></span>
            <strong>Перетащите файлы сюда или выберите на диске</strong>
            <small>{uploadStatus || `Максимальный размер файла: ${maxDocumentUploadMb} MB. Поддерживаются: ${acceptedDocumentExtensions.map((ext) => ext.toUpperCase()).join(', ')}`}</small>
          </button>
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept={acceptedDocuments}
            onChange={(event) => {
              handleFile(event.target.files?.[0])
              event.target.value = ''
            }}
          />

          <aside className="doi-card">
            <div className="doi-card__title">
              <Icon name="link" />
              <h3>DOI, URL или название статьи</h3>
            </div>
            <input
              type="text"
              value={doi}
              onChange={(event) => {
                setDoi(event.target.value)
                setDoiStatus('')
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') addDoi()
              }}
              placeholder="10.1038/s41586-020... или запрос к OpenAlex"
            />
            <button
              className="doi-card__action"
              type="button"
              onClick={addDoi}
              disabled={!doi.trim() || importingOpenAlexKey !== ''}
            >
              <Icon name="plus" />
              Добавить ссылку
            </button>
            {doiStatus && <p className="doi-card__status">{doiStatus}</p>}

            {doi.trim().length >= MIN_OPENALEX_QUERY_LENGTH && (
              <div className="doi-suggestions">
                <div className="doi-suggestions__head">
                  <span>Варианты OpenAlex</span>
                  <small>
                    {searchingOpenAlex
                      ? 'Ищем...'
                      : openAlexResults.external.length > 0
                        ? `${openAlexResults.external.length} найдено`
                        : 'Без совпадений'}
                  </small>
                </div>

                {openAlexResults.local.length > 0 && (
                  <p className="doi-suggestions__hint">
                    Уже в проекте найдено совпадений: {openAlexResults.local.length}
                  </p>
                )}

                {openAlexResults.external.map((item) => {
                  const itemKey = openAlexResultKey(item)
                  const meta = openAlexMeta(item)
                  const description = openAlexDescription(item)

                  return (
                    <button
                      key={itemKey}
                      className={`doi-suggestion ${item?.already_added ? 'doi-suggestion--added' : ''}`}
                      type="button"
                      onClick={() => importOpenAlexResult(item)}
                      disabled={item?.already_added || importingOpenAlexKey === itemKey}
                    >
                      <div className="doi-suggestion__copy">
                        <strong>{openAlexTitle(item)}</strong>
                        {meta && <span>{meta}</span>}
                        {description && <small>{description}</small>}
                      </div>
                      <em>
                        {importingOpenAlexKey === itemKey
                          ? 'Импорт...'
                          : item?.already_added
                            ? 'Уже в библиотеке'
                            : 'Добавить'}
                      </em>
                    </button>
                  )
                })}

                {!searchingOpenAlex && openAlexResults.query && openAlexResults.external.length === 0 && (
                  <div className="doi-suggestions__empty">
                    {openAlexResults.external_error || 'По этому запросу OpenAlex пока ничего не вернул.'}
                  </div>
                )}
              </div>
            )}
          </aside>
        </div>
      </section>

      <section className="library-block">
        <aside className="filters">
          <h2><Icon name="filter" />Фильтры</h2>
          <div className="filters__group">
            <h3>Тип источника</h3>
            {Object.entries(TYPE_META).map(([key, meta]) => (
              <FilterRow
                key={key}
                checked={typeFilters[key]}
                label={meta.label}
                count={filterCounts[key]}
                onChange={() => setTypeFilters((prev) => ({ ...prev, [key]: !prev[key] }))}
              />
            ))}
          </div>

          <div className="filters__group">
            <h3>Год публикации</h3>
            {Object.entries(YEAR_META).map(([key, label]) => (
              <FilterRow
                key={key}
                checked={yearFilters[key]}
                label={label}
                count={filterCounts[key]}
                onChange={() => setYearFilters((prev) => ({ ...prev, [key]: !prev[key] }))}
              />
            ))}
          </div>

          <div className="ai-advice">
            <strong>Совет AI</strong>
            <p>Используйте статьи за последние 2 года для более актуальных гипотез. Сейчас выбрано {selectedIds.size} источника.</p>
          </div>
        </aside>

        <div className="library">
          <div className="library__toolbar">
            <div className="library__title">
              <h2>Библиотека источников</h2>
              <span>{filteredItems.length} документов</span>
              <mark>Выбран {selectedVisibleCount} элемент</mark>
            </div>
            <div className="library__actions">
              <label className="library-search">
                <Icon name="search" />
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Найти в библиотеке..."
                />
              </label>
              <button type="button" onClick={selectAllVisible}>Выбрать все</button>
            </div>
          </div>

          {filteredItems.length > 0 ? (
            <div className="sources-grid">
              {filteredItems.map((item) => (
                <KnowledgeCard
                  key={item.id}
                  item={item}
                  selected={selectedIds.has(item.id)}
                  onToggle={() => toggleSelection(item.id)}
                  onOpenDetails={openSourceDetails}
                  onDeleteSource={handleDeleteSource}
                  onDeleteDocument={handleDeleteDocument}
                />
              ))}
            </div>
          ) : (
            <div className="library-empty">Нет источников по выбранным фильтрам</div>
          )}

          {filteredItems.length > 0 && (
            <button className="load-more" type="button">
              Показать больше
              <Icon name="chevron" />
            </button>
          )}
        </div>
      </section>

      {openedSourceItem && (
        openedSourceItem.kind === 'document' ? (
          <DocumentDetailsModal
            item={openedSourceItem}
            document={openedSource}
            loading={openingSource}
            error={openedSourceError}
            onClose={closeSourceDetails}
          />
        ) : (
          <SourceDetailsModal
            item={openedSourceItem}
            source={openedSource}
            loading={openingSource}
            error={openedSourceError}
            onClose={closeSourceDetails}
          />
        )
      )}
    </section>
  )
}
