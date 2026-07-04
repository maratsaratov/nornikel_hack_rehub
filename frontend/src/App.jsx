import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { Toast } from './components/ui.jsx'
import KnowledgePanel from './components/KnowledgePanel.jsx'
import ProjectModal from './components/ProjectModal.jsx'
import GenerationPanel from './components/GenerationPanel.jsx'
import TargetPanel from './components/TargetPanel.jsx'
import { readStorage, writeStorage } from './storage.js'

const SELECTED_PROJECT_SCOPE = 'selected-project'

function selectedProjectStorageKey(user) {
  if (!user?.id) return ''
  return `rehub:${SELECTED_PROJECT_SCOPE}:${user.id}`
}

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

function AuthScreen({ onSubmit }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: '', display_name: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const isRegister = mode === 'register'

  const update = (key) => (event) => {
    setForm((prev) => ({ ...prev, [key]: event.target.value }))
    setError('')
  }

  async function submit(event) {
    event.preventDefault()
    if (!form.username.trim() || !form.password) return
    setBusy(true)
    setError('')
    try {
      await onSubmit(mode, form)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit}>
        <span className="auth-card__eyebrow">Re Hub accounts</span>
        <h1>{isRegister ? 'Создать аккаунт' : 'Войти в аккаунт'}</h1>
        <p>Проекты видны только владельцу и приглашенным участникам.</p>

        <label>
          <span>Логин/ник</span>
          <input
            value={form.username}
            onChange={update('username')}
            autoComplete="username"
            placeholder="user_1"
          />
        </label>

        {isRegister && (
          <label>
            <span>Отображаемое имя</span>
            <input
              value={form.display_name}
              onChange={update('display_name')}
              autoComplete="name"
              placeholder="Иван"
            />
          </label>
        )}

        <label>
          <span>Пароль</span>
          <input
            type="password"
            value={form.password}
            onChange={update('password')}
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            placeholder="Минимум 6 символов"
          />
        </label>

        {error && <div className="auth-card__error">{error}</div>}

        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? 'Подождите...' : isRegister ? 'Зарегистрироваться' : 'Войти'}
        </button>

        <button
          className="auth-card__switch"
          type="button"
          onClick={() => {
            setMode(isRegister ? 'login' : 'register')
            setError('')
          }}
        >
          {isRegister ? 'Уже есть аккаунт? Войти' : 'Нет аккаунта? Создать'}
        </button>
      </form>
    </div>
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
  const [authChecked, setAuthChecked] = useState(false)
  const [currentUser, setCurrentUser] = useState(null)
  const [currentRoute, setCurrentRoute] = useState(window.location.hash || '#knowledge')

  const flash = (msg, type = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }

  useEffect(() => {
    api.config().then(setConfig).catch(() => {})
    api.healthLlm().then((r) => setLlmOk(r.ok)).catch(() => setLlmOk(false))
  }, [])

  useEffect(() => {
    let active = true
    if (!api.getToken()) {
      setAuthChecked(true)
      return () => { active = false }
    }

    api.me()
      .then((user) => {
        if (active) setCurrentUser(user)
      })
      .catch(() => {
        api.setToken('')
      })
      .finally(() => {
        if (active) setAuthChecked(true)
      })

    return () => { active = false }
  }, [])

  useEffect(() => {
    const onHashChange = () => setCurrentRoute(window.location.hash || '#knowledge')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const project = useMemo(
    () => projects.find((p) => p.id === currentId) || null,
    [projects, currentId],
  )
  const selectedProjectKey = useMemo(
    () => selectedProjectStorageKey(currentUser),
    [currentUser],
  )
  const canManageProject = Boolean(project?.can_manage_project || project?.current_user_role === 'owner')
  const canManageMembers = Boolean(project?.can_manage_members || project?.current_user_role === 'owner')

  async function loadProjects() {
    const list = await api.listProjects()
    setProjects(list)
    setCurrentId((prev) => {
      if (list.some((item) => item.id === prev)) return prev
      const storedId = Number(readStorage(selectedProjectStorageKey(currentUser), null))
      if (list.some((item) => item.id === storedId)) return storedId
      return list[0]?.id || null
    })
  }

  useEffect(() => {
    if (!authChecked || !currentUser) return
    loadProjects().catch((e) => flash(e.message, 'err'))
  }, [authChecked, currentUser])

  useEffect(() => {
    if (!selectedProjectKey || !currentId) return
    writeStorage(selectedProjectKey, currentId)
  }, [currentId, selectedProjectKey])

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

  async function handleAuth(mode, form) {
    const payload = {
      username: form.username.trim(),
      password: form.password,
    }
    if (mode === 'register') {
      payload.display_name = form.display_name.trim()
    }

    const result = mode === 'register'
      ? await api.register(payload)
      : await api.login(payload)
    api.setToken(result.token)
    setCurrentUser(result.user)
    flash(mode === 'register' ? 'Аккаунт создан' : 'Вход выполнен')
  }

  async function logout() {
    try {
      await api.logout()
    } catch (_) {
      // Local logout should still succeed if the session is already invalid.
    } finally {
      api.setToken('')
      setCurrentUser(null)
      setProjects([])
      setCurrentId(null)
      setSources([])
      setDocuments([])
      setProjectModal(null)
    }
  }

  async function saveProject(form) {
    if (form.id) {
      if (!canManageProject) {
        flash('Свойства проекта может менять только owner', 'err')
        return null
      }
      const saved = await api.updateProject(form.id, form)
      setProjects((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
      flash('Проект обновлен')
      return saved
    }

    const created = await api.createProject(form)
    setProjects((prev) => [created, ...prev])
    setCurrentId(created.id)
    flash('Проект создан')
    return created
  }

  async function saveTarget(payload) {
    if (!project) return null
    if (!canManageProject) {
      flash('Целевые свойства проекта может менять только owner', 'err')
      return null
    }
    const saved = await api.updateProject(project.id, { ...project, ...payload })
    setProjects((prev) => prev.map((item) => (item.id === saved.id ? saved : item)))
    flash('Целевой показатель сохранен')
    return saved
  }

  async function addSource(data) {
    await api.addSource(currentId, data)
    await reloadKnowledge()
    flash('Источник добавлен')
  }

  async function deleteSource(id) {
    try {
      await api.deleteSource(id)
      setSources((prev) => prev.filter((source) => source.id !== id))
      flash('Источник удален')
      return true
    } catch (error) {
      flash(error.message, 'err')
      await reloadKnowledge()
      return false
    }
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
    flash('Файл удален')
  }

  async function loadProjectMembers(projectId) {
    return api.listProjectMembers(projectId)
  }

  async function inviteProjectMember(projectId, username) {
    const member = await api.addProjectMember(projectId, { username })
    flash('Участник добавлен')
    await loadProjects()
    return member
  }

  async function removeProjectMember(projectId, userId) {
    await api.deleteProjectMember(projectId, userId)
    flash('Участник удален')
    await loadProjects()
  }

  const systemState = llmOk === null ? 'Проверка модулей' : llmOk ? 'Система активна' : 'Модель недоступна'
  const systemHint = llmOk === false ? (config?.model || 'Проверьте настройки LLM') : 'Все модули работают в штатном режиме'

  if (!authChecked) {
    return (
      <div className="knowledge-app">
        <div className="auth-screen">
          <div className="auth-card">
            <span className="auth-card__eyebrow">ReHub accounts</span>
            <h1>Проверяем сессию</h1>
            <p>Секунду, поднимаем рабочее пространство.</p>
          </div>
        </div>
      </div>
    )
  }

  if (!currentUser) {
    return (
      <>
        <AuthScreen onSubmit={handleAuth} />
        <Toast toast={toast} />
      </>
    )
  }

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
            <a className={currentRoute === '#target' ? 'is-active' : ''} href="#target">
              <Icon name="target" />Целевой показатель
            </a>
            <a className={currentRoute === '#knowledge' || currentRoute === '' ? 'is-active' : ''} href="#knowledge">
              <Icon name="knowledge" />База знаний
            </a>
            <a className={currentRoute === '#generation' ? 'is-active' : ''} href="#generation">
              <Icon name="generation" />Генерация
            </a>
          </nav>

          <div className="project-switcher">
            <button
              type="button"
              className="project-switcher__create"
              onClick={() => setProjectModal('new')}
              aria-label="Создать новый проект"
              title="Создать новый проект"
            >
              Проект
            </button>
            <span>Проект</span>
            {projects.length > 0 ? (
              <select value={currentId || ''} onChange={(event) => setCurrentId(Number(event.target.value))} aria-label="Выбор проекта">
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>{item.title}</option>
                ))}
              </select>
            ) : (
              <button type="button" onClick={() => setProjectModal('new')}>Создать</button>
            )}
            <span className="project-switcher__arrow">›</span>
          </div>

          <div className="account-actions">
            <span className="account-actions__user">
              {currentUser.display_name || currentUser.username}
            </span>
            <button className="account-actions__logout" type="button" onClick={logout}>
              Выйти
            </button>
            <button
              className="avatar-button"
              type="button"
              disabled={!project || !canManageProject}
              onClick={() => project && canManageProject && setProjectModal(project)}
              aria-label="Параметры проекта"
              title={canManageProject ? 'Параметры проекта' : 'Настройки доступны только owner'}
            >
              <span>{project?.title?.trim()?.[0] || currentUser.username?.[0] || 'U'}</span>
            </button>
          </div>
        </div>
      </header>

      <main>
        {project ? (
          <>
            {(currentRoute === '#knowledge' || currentRoute === '') && (
              <KnowledgePanel
                project={project}
                sources={sources}
                documents={documents}
                documentTypes={config?.supported_document_types}
                maxUploadMb={config?.max_upload_mb}
                onAdd={addSource}
                onDelete={deleteSource}
                onSearch={searchSources}
                onImportOpenAlex={importOpenAlex}
                onUploadDocument={uploadDocument}
                onDeleteDocument={deleteDocument}
              />
            )}
            {currentRoute === '#generation' && (
              <GenerationPanel
                project={project}
                flash={flash}
                onDeleteSource={deleteSource}
                onDeleteDocument={deleteDocument}
                sources={sources}
                documents={documents}
              />
            )}
            {currentRoute === '#target' && (
              <TargetPanel project={project} onSave={saveTarget} canEdit={canManageProject} />
            )}
          </>
        ) : (
          <section className="empty-project">
            <h1>База знаний</h1>
            <p>Создайте проект, чтобы загружать статьи, отчеты и DOI-ссылки.</p>
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
          currentUser={currentUser}
          canManageMembers={projectModal !== 'new' && canManageMembers}
          onClose={() => setProjectModal(null)}
          onSave={saveProject}
          onLoadMembers={loadProjectMembers}
          onInviteMember={inviteProjectMember}
          onRemoveMember={removeProjectMember}
        />
      )}

      <Toast toast={toast} />
    </div>
  )
}
