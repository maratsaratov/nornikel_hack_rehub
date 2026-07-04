const JSON_HEADERS = { 'Content-Type': 'application/json' }
const AUTH_TOKEN_KEY = 'rehub.authToken'

let authToken = window.localStorage.getItem(AUTH_TOKEN_KEY) || ''

function authOpts(opts = {}) {
  if (!authToken) return opts
  return {
    ...opts,
    headers: {
      ...(opts.headers || {}),
      Authorization: `Bearer ${authToken}`,
    },
  }
}

function errorMessage(payload, fallback) {
  if (!payload || typeof payload !== 'object') return fallback
  return payload.error || payload.detail || fallback
}

async function req(url, opts = {}) {
  const response = await fetch(url, authOpts(opts))
  if (!response.ok) {
    let msg = `Ошибка ${response.status}`
    try {
      msg = errorMessage(await response.json(), msg)
    } catch (_) { /* ignore */ }
    throw new Error(msg)
  }
  if (response.status === 204) return null
  return response.json()
}

async function blobReq(url, opts = {}) {
  const response = await fetch(url, authOpts(opts))
  if (!response.ok) {
    let msg = `Ошибка ${response.status}`
    try {
      msg = errorMessage(await response.json(), msg)
    } catch (_) { /* ignore */ }
    throw new Error(msg)
  }
  return response
}

const body = (payload) => ({ headers: JSON_HEADERS, body: JSON.stringify(payload) })

export const api = {
  getToken: () => authToken,
  setToken: (token) => {
    authToken = token || ''
    if (authToken) window.localStorage.setItem(AUTH_TOKEN_KEY, authToken)
    else window.localStorage.removeItem(AUTH_TOKEN_KEY)
  },

  config: () => req('/api/config'),
  health: () => req('/api/health'),
  healthLlm: () => req('/api/health/llm'),

  register: (payload) => req('/api/auth/register', { method: 'POST', ...body(payload) }),
  login: (payload) => req('/api/auth/login', { method: 'POST', ...body(payload) }),
  me: () => req('/api/auth/me'),
  logout: () => req('/api/auth/logout', { method: 'POST' }),

  listProjects: () => req('/api/projects'),
  createProject: (payload) => req('/api/projects', { method: 'POST', ...body(payload) }),
  updateProject: (id, payload) => req(`/api/projects/${id}`, { method: 'PUT', ...body(payload) }),
  deleteProject: (id) => req(`/api/projects/${id}`, { method: 'DELETE' }),
  listProjectMembers: (id) => req(`/api/projects/${id}/members`),
  addProjectMember: (id, payload) => req(`/api/projects/${id}/members`, { method: 'POST', ...body(payload) }),
  deleteProjectMember: (id, userId) => req(`/api/projects/${id}/members/${userId}`, { method: 'DELETE' }),

  listSources: (id) => req(`/api/projects/${id}/sources`),
  addSource: (id, payload) => req(`/api/projects/${id}/sources`, { method: 'POST', ...body(payload) }),
  searchSources: (id, q, limit = 6) => (
    req(`/api/projects/${id}/sources/search?q=${encodeURIComponent(q)}&limit=${limit}`)
  ),
  importOpenAlex: (id, payload) => req(`/api/projects/${id}/sources/import-openalex`, { method: 'POST', ...body(payload) }),
  getSource: (id) => req(`/api/sources/${id}`),
  deleteSource: (id) => req(`/api/sources/${id}`, { method: 'DELETE' }),

  listDocuments: (id) => req(`/api/projects/${id}/documents`),
  getDocument: (id, raw = false) => req(`/api/documents/${id}?raw=${raw ? 'true' : 'false'}`),
  uploadDocument: (id, file, parse = true) => {
    const form = new FormData()
    form.append('file', file)
    return req(`/api/projects/${id}/documents?parse=${parse ? 'true' : 'false'}`, {
      method: 'POST',
      body: form,
    })
  },
  deleteDocument: (id) => req(`/api/documents/${id}`, { method: 'DELETE' }),

  generate: (id, payload) => req(`/api/projects/${id}/generate`, { method: 'POST', ...body(payload) }),
  listHypotheses: (id) => req(`/api/projects/${id}/hypotheses`),
  updateHypothesis: (id, payload) => req(`/api/hypotheses/${id}`, { method: 'PATCH', ...body(payload) }),
  deleteHypothesis: (id) => req(`/api/hypotheses/${id}`, { method: 'DELETE' }),
  exportHypotheses: (id, format, weights) => (
    blobReq(`/api/projects/${id}/hypotheses/export?format=${format}&weights=${encodeURIComponent(JSON.stringify(weights))}`)
  ),

  listRuns: (id) => req(`/api/projects/${id}/runs`),
}
