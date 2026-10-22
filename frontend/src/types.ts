export type UserRole = 'requester' | 'admin'

export type User = {
  id: number
  email: string
  full_name: string
  role: UserRole
  department_id: number | null
  department_name: string | null
}

export type AuthResponse = { user: User; csrf_token: string }
export type Department = { id: number; code: string; name: string }
export type RequestStatus = 'Draft' | 'Submitted' | 'Approved' | 'Returned'

export type PurchaseRequest = {
  id: number
  title: string
  description?: string
  vendor: string
  department_id: number | null
  department_name: string | null
  amount: string
  currency: 'USD'
  requester_id: number
  requester_name: string
  status: RequestStatus
  created_at: string
  updated_at: string
}

export type RequestEvent = {
  id: number
  event_type: 'Created' | 'Updated' | 'Submitted' | 'Returned' | 'Resubmitted' | 'Approved'
  previous_status: RequestStatus | null
  new_status: RequestStatus
  details: Record<string, unknown>
  comment: string | null
  created_at: string
  actor_name: string
}

export type RequestDetail = PurchaseRequest & { events: RequestEvent[] }
export type RequestDraft = { title: string; description: string; vendor: string; department_id: number | null; amount: string }
export type RequestFilters = { search: string; status: RequestStatus | ''; department_id: number | ''; sort_by: 'created_at' | 'amount'; sort_order: 'asc' | 'desc'; page: number; page_size: 10 | 20 }
export type RequestPage = { items: PurchaseRequest[]; total: number; page: number; page_size: number }
export type RequestOverview = {
  total_requests: number
  pending_review: number
  changes_requested: number
  approved_amount: string
  requests_by_status: { status: RequestStatus; count: number }[]
  requests_by_department: { department_id: number | null; department_name: string | null; count: number }[]
}
