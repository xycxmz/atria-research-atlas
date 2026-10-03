const BASE = '/api'

// 结构化 API 错误：503 产物缺失/损坏带 missing 列表，供 DataState 显示「未就绪」而非「失败」（V2-011）
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `HTTP ${status}`)
    this.status = status
    this.kind = body?.kind || (status === 503 ? 'unavailable' : 'http')
    this.missing = body?.missing || []
    this.corrupt = body?.corrupt || []
    this.snapshot = body?.snapshot || null
  }
}

async function fetchJson(url, signal) {
  const resp = await fetch(url, signal ? { signal } : undefined)
  if (!resp.ok) {
    let body = null
    try {
      body = await resp.json()
    } catch (e) {
      body = null
    }
    throw new ApiError(resp.status, body)
  }
  return resp.json()
}

export function getAnalysis() {
  return fetchJson(`${BASE}/analysis`)
}

export function getAdvanced() {
  return fetchJson(`${BASE}/analysis/advanced`)
}

export function getNational() {
  return fetchJson(`${BASE}/national`)
}

export function getRecent() {
  return fetchJson(`${BASE}/recent`)
}

export function getProjects(params = {}, signal) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v != null)
  ).toString()
  return fetchJson(`${BASE}/projects?${qs}`, signal)
}

export function getConflicts(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v != null)
  ).toString()
  return fetchJson(`${BASE}/conflicts?${qs}`)
}

export function getProject(grantNo) {
  return fetchJson(`${BASE}/project/${encodeURIComponent(grantNo)}`)
}

export function getHealth() {
  return fetchJson(`${BASE}/health`)
}
