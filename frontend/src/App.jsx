import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { Toast } from './components/ui.jsx'
import KnowledgePanel from './components/KnowledgePanel.jsx'
import ProjectModal from './components/ProjectModal.jsx'

function Icon({ name }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  }

  if (name === 'target') {
    return (
      <svg {...common}>
        <rect x="4" y="4" width="14" height="14" rx="2" />
        <path d="M9 4v14" />
        <path d="M4 9h14" />
      </svg>
    )
  }

  if (name === 'knowledge') {
    return (
      <svg {...common}>
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M8 4v16" />
        <path d="M4 8h16" />
        <path d="M4 14h16" />
      </svg>
    )
  }

  return (
    <svg {...common}>
      <path d="M7 4H5a1 1 0 0 0-1 1v2" />
      <path d="M17 4h2a1 1 0 0 1 1 1v2" />
      <path d="M7 20H5a1 1 0 0 1-1-1v-2" />
      <path d="M17 20h2a1 1 0 0 0 1-1v-2" />
      <path d="M9 12h6" />
    </svg>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [llmOk, setLlmOk] = useState(null)
  const [projects, setProjects] = useState([])
  const [currentId, setCurrentId] = useState(null)
  const [sources, setSources] = useState([])
  const [documents, setDocuments] = useState([])
  const [projectModal, setProjectModal] = useState(null)
  const [toast, setToast] = useState(null)

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

  const project = useMemo(
    () => projects.find((p) => p.id === currentId) || null,
    [projects, currentId],
  )

  async function reloadKnowledge(projectId = currentId) {
    if (!projectId) {
      setSources([])
      setDocuments([])
      return
    }

    const [src, docs] = await Promise.all([
      api.listSources(projectId),
      api.listDocuments(projectId),
    ])
    setSources(src)
    setDocuments(docs)
  }

  useEffect(() => {
    reloadKnowledge().catch((e) => flash(e.message, 'err'))
  }, [currentId])

  async function saveProject(form) {
    if (form.id) {
      const p = await api.updateProject(form.id, form)
      setProjects((prev) => prev.map((x) => (x.id === p.id ? p : x)))
      flash('Проект обновлён')
      return
    }

    const p = await api.createProject(form)
    setProjects((prev) => [p, ...prev])
    setCurrentId(p.id)
    flash('Проект создан')
  }

  async function addSource(data) {
    await api.addSource(currentId, data)
    await reloadKnowledge()
    flash('Источник добавлен')
  }

  async function deleteSource(id) {
    await api.deleteSource(id)
    setSources((prev) => prev.filter((s) => s.id !== id))
  }

  async function searchSources(query) {
    return api.searchSources(currentId, query)
  }

  async function importOpenAlex(item) {
    await api.importOpenAlex(currentId, item)
    await reloadKnowledge()
    flash('Ссылка добавлена в библиотеку')
  }

  async function uploadDocument(file) {
    await api.uploadDocument(currentId, file, true)
    await reloadKnowledge()
    flash('Файл загружен и отправлен на парсинг')
  }

  async function deleteDocument(id) {
    await api.deleteDocument(id)
    setDocuments((prev) => prev.filter((doc) => doc.id !== id))
  }

  const systemState = llmOk === null ? 'Проверка модулей' : llmOk ? 'Система активна' : 'Модель недоступна'
  const systemHint = llmOk === false ? (config?.model || 'Проверьте настройки LLM') : 'Все модули работают в штатном режиме'

  return (
    <div className="knowledge-app">
      <header className="topbar">
        <div className="topbar__inner">
          <a className="brand" href="#knowledge" aria-label="Фабрика гипотез">
            <span className="brand__mark">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M3 12h3l2-6 4 12 3-8 2 2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span>Фабрика гипотез</span>
          </a>

          <nav className="topnav" aria-label="Разделы приложения">
            <a href="#target"><Icon name="target" />Целевой показатель</a>
            <a className="is-active" href="#knowledge"><Icon name="knowledge" />База знаний</a>
            <a href="#generation"><Icon name="generation" />Генерация</a>
          </nav>

          <div className="project-switcher">
            <span>Проект</span>
            {projects.length > 0 ? (
              <select value={currentId || ''} onChange={(e) => setCurrentId(Number(e.target.value))} aria-label="Выбор проекта">
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.title}</option>
                ))}
              </select>
            ) : (
              <button type="button" onClick={() => setProjectModal('new')}>Создать</button>
            )}
            <span className="project-switcher__arrow">›</span>
          </div>

          <button className="avatar-button" type="button" onClick={() => project && setProjectModal(project)} aria-label="Параметры проекта">
            <span>{project?.title?.trim()?.[0] || 'Л'}</span>
          </button>
        </div>
      </header>

      <main id="knowledge">
        {project ? (
          <KnowledgePanel
            project={project}
            sources={sources}
            documents={documents}
            onAdd={addSource}
            onDelete={deleteSource}
            onSearch={searchSources}
            onImportOpenAlex={importOpenAlex}
            onUploadDocument={uploadDocument}
            onDeleteDocument={deleteDocument}
          />
        ) : (
          <section className="empty-project">
            <h1>База знаний</h1>
            <p>Создайте проект, чтобы загрузить статьи, отчёты и DOI-ссылки.</p>
            <button className="button button--primary" type="button" onClick={() => setProjectModal('new')}>Создать проект</button>
          </section>
        )}
      </main>

      <footer className="app-footer">
        <div className="app-footer__inner">
          <div className="footer-columns">
            <div>
              <h2>Документация</h2>
              <a href="#docs">Руководство пользователя</a>
              <a href="#api">API интеграция</a>
              <a href="#method">Методология AI</a>
            </div>
            <div>
              <h2>Инструменты</h2>
              <a href="#export">Экспорт данных</a>
              <a href="#graphs">Визуализация графов</a>
            </div>
            <div>
              <h2>Поддержка</h2>
              <a href="#contacts">Контакты</a>
              <a href="#status">Статус системы</a>
            </div>
          </div>

          <div className={`status-card ${llmOk === false ? 'status-card--warn' : ''}`}>
            <span className="status-card__icon">
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="2" />
                <path d="m8.5 12 2.2 2.2 4.8-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <strong>{systemState}</strong>
            <span>{systemHint}</span>
          </div>
        </div>
        <div className="app-footer__bottom">
          <span>© 2026 Layout Variations. All rights reserved.</span>
          <nav aria-label="Правовая информация">
            <a href="#terms">Terms</a>
            <a href="#privacy">Privacy</a>
            <a href="#cookies">Cookies</a>
          </nav>
        </div>
      </footer>

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
