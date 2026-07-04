const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function req(url, opts = {}) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let msg = `Ошибка ${r.status}`
    try {
      const e = await r.json()
      msg = e.error || msg
    } catch (_) { /* ignore */ }
    throw new Error(msg)
  }
  if (r.status === 204) return null
  return r.json()
}

const body = (b) => ({ headers: JSON_HEADERS, body: JSON.stringify(b) })

export const api = {
  config: () => req('/api/config'),
  health: () => req('/api/health'),
  healthLlm: () => req('/api/health/llm'),

  listProjects: () => req('/api/projects'),
  createProject: (b) => req('/api/projects', { method: 'POST', ...body(b) }),
  updateProject: (id, b) => req(`/api/projects/${id}`, { method: 'PUT', ...body(b) }),
  deleteProject: (id) => req(`/api/projects/${id}`, { method: 'DELETE' }),

  listSources: (id) => req(`/api/projects/${id}/sources`),
  addSource: (id, b) => req(`/api/projects/${id}/sources`, { method: 'POST', ...body(b) }),
  searchSources: (id, q, limit = 6) => (
    req(`/api/projects/${id}/sources/search?q=${encodeURIComponent(q)}&limit=${limit}`)
  ),
  importOpenAlex: (id, b) => req(`/api/projects/${id}/sources/import-openalex`, { method: 'POST', ...body(b) }),
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

  generate: (id, b) => req(`/api/projects/${id}/generate`, { method: 'POST', ...body(b) }),
  listHypotheses: (id) => req(`/api/projects/${id}/hypotheses`),
  updateHypothesis: (id, b) => req(`/api/hypotheses/${id}`, { method: 'PATCH', ...body(b) }),
  deleteHypothesis: (id) => req(`/api/hypotheses/${id}`, { method: 'DELETE' }),

  listRuns: (id) => req(`/api/projects/${id}/runs`),
}
