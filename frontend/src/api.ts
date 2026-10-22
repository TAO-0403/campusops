import type { AuthResponse, Department, PurchaseRequest, RequestDetail, RequestDraft, RequestFilters, RequestOverview, RequestPage } from './types'

const API_ROOT = 'http://127.0.0.1:8000/api'
let csrfToken = ''

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

function detailMessage(payload: unknown): string {
  if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      return (detail[0] as { msg?: string }).msg ?? 'Please check the submitted information.'
    }
  }
  return 'The request could not be completed. Please try again.'
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (csrfToken && init.method && init.method !== 'GET') headers.set('X-CSRF-Token', csrfToken)

  let response: Response
  try {
    response = await fetch(`${API_ROOT}${path}`, { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError('Could not reach CampusOps. Check that the backend is running.', 0)
  }

  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(detailMessage(payload), response.status)
  return payload as T
}

export const api = {
  login(email: string, password: string) {
    return apiRequest<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }).then((result) => {
      csrfToken = result.csrf_token
      return result.user
    })
  },
  async currentUser() {
    const result = await apiRequest<AuthResponse>('/auth/me')
    csrfToken = result.csrf_token
    return result.user
  },
  async logout() {
    try { await apiRequest<void>('/auth/logout', { method: 'POST' }) } finally { csrfToken = '' }
  },
  listDepartments: () => apiRequest<Department[]>('/departments'),
  searchRequests(filters: RequestFilters) {
    const params = new URLSearchParams()
    if (filters.search.trim()) params.set('search', filters.search.trim())
    if (filters.status) params.set('status', filters.status)
    if (filters.department_id !== '') params.set('department_id', String(filters.department_id))
    params.set('sort_by', filters.sort_by)
    params.set('sort_order', filters.sort_order)
    params.set('page', String(filters.page))
    params.set('page_size', String(filters.page_size))
    return apiRequest<RequestPage>(`/requests?${params.toString()}`)
  },
  requestOverview(filters: Pick<RequestFilters, 'search' | 'status' | 'department_id'>) {
    const params = new URLSearchParams()
    if (filters.search.trim()) params.set('search', filters.search.trim())
    if (filters.status) params.set('status', filters.status)
    if (filters.department_id !== '') params.set('department_id', String(filters.department_id))
    return apiRequest<RequestOverview>(`/requests/overview?${params.toString()}`)
  },
  getRequest: (id: number) => apiRequest<RequestDetail>(`/requests/${id}`),
  createRequest: (draft: RequestDraft) => apiRequest<PurchaseRequest>('/requests', { method: 'POST', body: JSON.stringify(draft) }),
  updateRequest: (id: number, draft: RequestDraft) => apiRequest<PurchaseRequest>(`/requests/${id}`, { method: 'PUT', body: JSON.stringify(draft) }),
  submitRequest: (id: number) => apiRequest<PurchaseRequest>(`/requests/${id}/submit`, { method: 'POST' }),
  resubmitRequest: (id: number, comment: string) => apiRequest<PurchaseRequest>(`/requests/${id}/resubmit`, { method: 'POST', body: JSON.stringify({ comment }) }),
  approveRequest: (id: number, comment: string) => apiRequest<PurchaseRequest>(`/requests/${id}/approve`, { method: 'POST', body: JSON.stringify({ comment }) }),
  returnRequest: (id: number, reason: string) => apiRequest<PurchaseRequest>(`/requests/${id}/return`, { method: 'POST', body: JSON.stringify({ reason }) }),
}
