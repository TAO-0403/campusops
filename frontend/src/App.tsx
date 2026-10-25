import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api } from './api'
import type { Department, PurchaseRequest, QuotationAttachment, RequestDetail, RequestDraft, RequestFilters, RequestOverview, RequestStatus, User } from './types'

type Navigate = (path: string) => void

const REQUEST_HISTORY_LABELS = {
  Created: 'Draft created',
  Updated: 'Request updated',
  Submitted: 'Request submitted',
  Returned: 'Request returned',
  Resubmitted: 'Request resubmitted',
  Approved: 'Request approved',
} as const

type RequestHistoryEvent = RequestDetail['events'][number] & {
  event_type: keyof typeof REQUEST_HISTORY_LABELS
}

function isRequestHistoryEvent(event: RequestDetail['events'][number]): event is RequestHistoryEvent {
  return Object.prototype.hasOwnProperty.call(REQUEST_HISTORY_LABELS, event.event_type)
}

function usePathname(): [string, Navigate] {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const navigate = useCallback<Navigate>((nextPath) => {
    if (window.location.pathname !== nextPath) window.history.pushState({}, '', nextPath)
    setPath(nextPath)
  }, [])
  return [path, navigate]
}

function App() {
  const [path, navigate] = usePathname()
  const [user, setUser] = useState<User | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    api.currentUser()
      .then(setUser)
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status !== 401) setAuthError(error instanceof Error ? error.message : 'Could not check your sign-in status.')
      })
      .finally(() => setAuthLoading(false))
  }, [])

  useEffect(() => {
    if (authLoading) return
    const protectedPath = path.startsWith('/workspace') || path.startsWith('/requests/')
    if (!user && protectedPath) navigate('/sign-in')
    if (user && path === '/sign-in') navigate('/workspace')
  }, [authLoading, navigate, path, user])

  const signOut = async () => {
    try {
      await api.logout()
      setUser(null)
      setAuthError('')
      navigate('/')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Could not sign out. Please try again.')
    }
  }

  if (authLoading) return <PageMessage message="Loading your workspace…" />
  if (!user) {
    if (path === '/sign-in' || path.startsWith('/workspace') || path.startsWith('/requests/')) {
      return <SignInPage navigate={navigate} onSignedIn={(signedInUser) => { setUser(signedInUser); setAuthError(''); navigate('/workspace') }} />
    }
    return <LandingPage navigate={navigate} authError={authError} />
  }
  if (path === '/sign-in') return <PageMessage message="Opening your workspace…" />

  const editMatch = path.match(/^\/requests\/(\d+)\/edit$/)
  const detailMatch = path.match(/^\/requests\/(\d+)$/)
  if (path === '/' || path === '/workspace') return <DashboardPage user={user} navigate={navigate} onSignOut={signOut} notice={authError} />
  if (path === '/requests/new' && user.role === 'requester') return <RequestFormPage user={user} navigate={navigate} onSignOut={signOut} />
  if (editMatch && user.role === 'requester') return <RequestFormPage user={user} requestId={Number(editMatch[1])} navigate={navigate} onSignOut={signOut} />
  if (detailMatch) return <RequestDetailPage user={user} requestId={Number(detailMatch[1])} navigate={navigate} onSignOut={signOut} />
  return <DashboardPage user={user} navigate={navigate} onSignOut={signOut} notice={authError} />
}

function Brand({ navigate }: { navigate: Navigate }) {
  return <a className="brand" href="/" onClick={(event) => { event.preventDefault(); navigate('/') }} aria-label="CampusOps home"><span className="brand-mark" aria-hidden="true">C</span><span>Campus<span className="brand-accent">Ops</span></span></a>
}

function TopBar({ navigate, user, onSignOut }: { navigate: Navigate; user?: User | null; onSignOut?: () => void }) {
  return (
    <nav className="topbar" aria-label="Main navigation">
      <Brand navigate={navigate} />
      {user ? <div className="topbar-actions"><a href="/workspace" className="nav-link" onClick={(event) => { event.preventDefault(); navigate('/workspace') }}>Workspace</a><span className="topbar-user">{user.full_name}</span><button className="text-button" onClick={onSignOut}>Sign out</button></div> : <><span className="topbar-label">PROCUREMENT WORKSPACE</span><a className="button button-small button-primary" href="/sign-in" onClick={(event) => { event.preventDefault(); navigate('/sign-in') }}>Sign in</a></>}
    </nav>
  )
}

function LandingPage({ navigate, authError }: { navigate: Navigate; authError: string }) {
  const [health, setHealth] = useState({ backend: false, database: false, message: 'Checking database connection…' })
  useEffect(() => {
    let active = true
    fetch('http://127.0.0.1:8000/api/health')
      .then(async (response) => ({ response, data: await response.json() }))
      .then(({ data }) => { if (active) setHealth({ backend: data.backend === 'ok', database: data.database?.status === 'ok', message: data.database?.message ?? 'Database status is unavailable.' }) })
      .catch(() => { if (active) setHealth({ backend: false, database: false, message: 'Could not reach the API. Make sure the backend is running.' }) })
    return () => { active = false }
  }, [])

  return (
    <main className="page-shell">
      <TopBar navigate={navigate} />
      <section className="hero" aria-labelledby="hero-title">
        <p className="eyebrow"><span className="eyebrow-dot" /> CAMPUS PROCUREMENT</p>
        <h1 id="hero-title">Good decisions start<br />with a clear process.</h1>
        <p className="hero-copy">A thoughtful home for campus purchasing requests, approvals, and the people behind them.</p>
        <a className="button button-primary hero-action" href="/sign-in" onClick={(event) => { event.preventDefault(); navigate('/sign-in') }}>Sign in to CampusOps <span aria-hidden="true">→</span></a>
      </section>
      <section className="workspace-card" aria-labelledby="workspace-title">
        <div className="workspace-heading"><div><p className="section-kicker">YOUR WORKSPACE</p><h2 id="workspace-title">Everything in its right place.</h2></div><span className="workspace-icon" aria-hidden="true">✳</span></div>
        <div className="feature-grid">
          <article className="feature-card"><span className="feature-index">01</span><h3>Purchase requests</h3><p>Bring the details, purpose, and cost together in one clear request.</p></article>
          <article className="feature-card"><span className="feature-index">02</span><h3>Thoughtful review</h3><p>Give every decision a clear owner and a reliable next step.</p></article>
          <article className="feature-card"><span className="feature-index">03</span><h3>A complete record</h3><p>Keep a useful history of decisions, updates, and outcomes.</p></article>
        </div>
      </section>
      {authError && <p className="notice notice-error page-notice">{authError}</p>}
      <details className="development-details">
        <summary><span><strong>Development information</strong><small>Local API and database health</small></span><span className="development-summary-state">{health.backend && health.database ? 'Services connected' : 'Check service status'}</span></summary>
        <section className="status-card" aria-labelledby="status-title" aria-live="polite">
          <div className="status-copy"><p className="section-kicker">DEVELOPMENT STATUS</p><h2 id="status-title">Local services</h2></div>
          <div className="status-list"><StatusItem label="API service" connected={health.backend} /><StatusItem label="PostgreSQL" connected={health.database} message={health.message} /></div>
        </section>
      </details>
      <footer className="footer"><span>CampusOps</span><span>Built for better campus purchasing.</span></footer>
    </main>
  )
}

function StatusItem({ label, connected, message }: { label: string; connected: boolean; message?: string }) {
  return <div className="status-item" title={message}><span className={`status-dot ${connected ? 'status-ok' : 'status-error'}`} aria-hidden="true" /><span className="status-name">{label}</span><span className={`status-value ${connected ? 'status-text-ok' : 'status-text-error'}`}>{connected ? 'Connected' : 'Unavailable'}</span></div>
}

function SignInPage({ onSignedIn, navigate }: { onSignedIn: (user: User) => void; navigate: Navigate }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    try { onSignedIn(await api.login(email, password)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in failed. Please try again.') }
    finally { setSubmitting(false) }
  }

  return (
    <main className="page-shell">
      <TopBar navigate={navigate} />
      <section className="auth-layout">
        <div className="auth-intro"><p className="eyebrow"><span className="eyebrow-dot" /> WELCOME BACK</p><h1 className="auth-title">A clearer way<br />to move work forward.</h1><p className="hero-copy">Sign in to manage campus purchase requests and keep every next step in view.</p></div>
        <form className="form-card sign-in-card" onSubmit={onSubmit}>
          <div className="form-heading"><p className="section-kicker">CAMPUSOPS ACCOUNT</p><h2>Sign in</h2><p>Use your assigned demo account to continue.</p></div>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <label className="field-label" htmlFor="email">Email address</label><input id="email" className="text-input" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <label className="field-label" htmlFor="password">Password</label><input id="password" className="text-input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          <button className="button button-primary button-full" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button>
          <a className="back-link" href="/" onClick={(event) => { event.preventDefault(); navigate('/') }}>Back to home</a>
        </form>
      </section>
      <footer className="footer"><span>CampusOps</span><span>Secure campus procurement workspace.</span></footer>
    </main>
  )
}

function DashboardPage({ user, navigate, onSignOut, notice }: { user: User; navigate: Navigate; onSignOut: () => void; notice: string }) {
  const [requests, setRequests] = useState<PurchaseRequest[]>([])
  const [overview, setOverview] = useState<RequestOverview | null>(null)
  const [departments, setDepartments] = useState<Department[]>([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<RequestStatus | ''>('')
  const [departmentFilter, setDepartmentFilter] = useState<number | ''>('')
  const [sortValue, setSortValue] = useState('created_at:desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<10 | 20>(10)
  const [total, setTotal] = useState(0)
  const [listLoading, setListLoading] = useState(true)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [overviewError, setOverviewError] = useState('')
  const [exportLoading, setExportLoading] = useState(false)
  const [exportError, setExportError] = useState('')
  const filterValues = useMemo(() => ({ search, status: statusFilter, department_id: departmentFilter }), [search, statusFilter, departmentFilter])
  const [sortBy, sortOrder] = sortValue.split(':') as [RequestFilters['sort_by'], RequestFilters['sort_order']]

  useEffect(() => { api.listDepartments().then(setDepartments).catch(() => setListError('Could not load department filters.')) }, [])
  useEffect(() => {
    let active = true
    setListLoading(true); setListError('')
    api.searchRequests({ ...filterValues, sort_by: sortBy, sort_order: sortOrder, page, page_size: pageSize })
      .then((result) => { if (active) { setRequests(result.items); setTotal(result.total) } })
      .catch((failure: unknown) => { if (active) setListError(failure instanceof Error ? failure.message : 'Could not load purchase requests.') })
      .finally(() => { if (active) setListLoading(false) })
    return () => { active = false }
  }, [filterValues, sortBy, sortOrder, page, pageSize])
  useEffect(() => {
    let active = true
    setOverviewLoading(true); setOverviewError('')
    api.requestOverview(filterValues)
      .then((result) => { if (active) setOverview(result) })
      .catch((failure: unknown) => { if (active) setOverviewError(failure instanceof Error ? failure.message : 'Could not load request overview.') })
      .finally(() => { if (active) setOverviewLoading(false) })
    return () => { active = false }
  }, [filterValues])

  const filtersActive = Boolean(search.trim() || statusFilter || departmentFilter !== '')
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const clearFilters = () => { setSearch(''); setStatusFilter(''); setDepartmentFilter(''); setSortValue('created_at:desc'); setPage(1) }
  const resetPage = () => setPage(1)
  const exportCsv = async () => {
    setExportLoading(true); setExportError('')
    try {
      const { blob, filename } = await api.exportRequests({ ...filterValues, sort_by: sortBy, sort_order: sortOrder })
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (failure) {
      setExportError(failure instanceof Error ? `Could not export requests: ${failure.message}` : 'Could not export requests. Please try again.')
    } finally {
      setExportLoading(false)
    }
  }

  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <section className="page-heading workspace-page-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> {user.role === 'admin' ? 'ADMIN WORKSPACE' : 'REQUESTER WORKSPACE'}</p><h1 className="page-title">Purchase requests</h1><p className="hero-copy">{user.role === 'admin' ? 'Review the request queue and open a request to see its history.' : 'Create a draft, refine the details, and submit when it is ready.'}</p></div>{user.role === 'requester' && <button className="button button-primary" onClick={() => navigate('/requests/new')}>New request <span aria-hidden="true">+</span></button>}</section>
      {notice && <p className="notice notice-error page-notice">{notice}</p>}
      <section className="overview-section" aria-labelledby="overview-title">
        <div className="overview-heading"><div><p className="section-kicker">REQUEST OVERVIEW</p><h2 id="overview-title">At a glance</h2></div><span className="overview-scope">All matching requests · independent of page and sort</span></div>
        {overviewLoading ? <div className="overview-loading" aria-live="polite">Updating overview…</div> : overviewError ? <p className="notice notice-error" role="alert">{overviewError}</p> : overview && <>
          <div className="metric-grid"><MetricCard label="Total requests" value={String(overview.total_requests)} loading={overviewLoading} /><MetricCard label="Pending review" value={String(overview.pending_review)} loading={overviewLoading} /><MetricCard label="Changes requested" value={String(overview.changes_requested)} loading={overviewLoading} /><MetricCard label="Approved amount · USD" value={formatMoney(overview.approved_amount)} loading={overviewLoading} /></div>
          <div className="chart-grid"><BreakdownChart title="Requests by status" rows={overview.requests_by_status.map((row) => ({ label: row.status, count: row.count, color: chartColor(row.status) }))} total={overview.total_requests} /><BreakdownChart title="Requests by department" rows={overview.requests_by_department.map((row) => ({ label: row.department_name ?? 'No department', count: row.count, color: '#438c83' }))} total={overview.total_requests} /></div>
        </>}
      </section>
      <section className="table-card request-register" aria-labelledby="request-list-title">
        <div className="table-heading"><div><p className="section-kicker">REQUEST REGISTER</p><h2 id="request-list-title">{total} {total === 1 ? 'request' : 'requests'}</h2></div><div className="table-heading-actions"><span className="table-role">{user.role === 'admin' ? 'All departments' : user.department_name ? `Your department: ${user.department_name}` : 'My requests'}</span>{user.role === 'admin' && <button className="button button-secondary export-button" type="button" onClick={() => void exportCsv()} disabled={exportLoading}>{exportLoading ? 'Exporting…' : 'Export CSV'}</button>}</div></div>
        {exportError && <p className="notice notice-error export-error" role="alert">{exportError}</p>}
        <div className="filter-bar" aria-label="Search and filter requests">
          <label className="filter-field search-filter"><span>Search title</span><input className="text-input" type="search" maxLength={120} placeholder="Search by keyword" value={search} onChange={(event) => { setSearch(event.target.value); resetPage() }} /></label>
          <label className="filter-field"><span>Status</span><select className="text-input" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as RequestStatus | ''); resetPage() }}><option value="">All statuses</option>{(['Draft', 'Submitted', 'Returned', 'Approved'] as RequestStatus[]).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label className="filter-field"><span>Department</span><select className="text-input" value={departmentFilter} onChange={(event) => { setDepartmentFilter(event.target.value ? Number(event.target.value) : ''); resetPage() }}><option value="">All departments</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
          <label className="filter-field sort-filter"><span>Sort by</span><select className="text-input" value={sortValue} onChange={(event) => { setSortValue(event.target.value); resetPage() }}><option value="created_at:desc">Newest created</option><option value="created_at:asc">Oldest created</option><option value="amount:desc">Amount: high to low</option><option value="amount:asc">Amount: low to high</option></select></label>
          <button className="text-button clear-filters" onClick={clearFilters} disabled={!filtersActive && sortValue === 'created_at:desc'}>Clear filters</button>
        </div>
        {listError ? <div className="state-block"><p className="notice notice-error" role="alert">{listError}</p><button className="button button-secondary" onClick={() => window.location.reload()}>Try again</button></div> : listLoading ? <div className="state-block" aria-live="polite">Loading purchase requests…</div> : requests.length === 0 ? <div className="empty-state"><span className="empty-icon" aria-hidden="true">＋</span><h3>{filtersActive ? 'No matching requests' : 'No requests yet'}</h3><p>{filtersActive ? 'Try changing your search or filters.' : user.role === 'admin' ? 'Requests will appear here when applicants create them.' : 'Start with a draft. You can save it now and finish the details later.'}</p>{filtersActive ? <button className="button button-secondary" onClick={clearFilters}>Clear filters</button> : user.role === 'requester' && <button className="button button-primary" onClick={() => navigate('/requests/new')}>Create a request</button>}</div> : <>
          <div className="table-scroll"><table className="request-table"><thead><tr><th>Request</th>{user.role === 'admin' && <th>Applicant</th>}<th>Department</th><th>Amount (USD)</th><th>Status</th><th>Created</th><th><span className="sr-only">Open request</span></th></tr></thead><tbody>{requests.map((request) => <tr key={request.id}><td><span className="request-title">{request.title || 'Untitled draft'}</span><span className="request-subtitle">{request.vendor || 'Vendor not set'}</span></td>{user.role === 'admin' && <td>{request.requester_name}</td>}<td>{request.department_name ?? 'Not set'}</td><td className="amount-cell">{formatMoney(request.amount)}</td><td><StatusBadge status={request.status} /></td><td>{formatDate(request.created_at)}</td><td><button className="row-link" onClick={() => navigate(`/requests/${request.id}`)}>View <span aria-hidden="true">→</span></button></td></tr>)}</tbody></table></div>
          <div className="pagination"><span className="pagination-range">Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span><label className="page-size-label">Rows <select className="page-size-select" value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value) as 10 | 20); resetPage() }}><option value={10}>10</option><option value={20}>20</option></select></label><div className="pagination-controls"><button className="button button-secondary" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}>Previous</button><span>Page {page} of {totalPages}</span><button className="button button-secondary" onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={page >= totalPages}>Next</button></div></div>
        </>}
      </section>
      <footer className="footer"><span>CampusOps</span><span>Amounts are shown in USD. Overview metrics cover all matching requests.</span></footer>
    </main>
  )
}

function MetricCard({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return <article className="metric-card"><p>{label}</p><strong>{loading ? 'Updating…' : value}</strong></article>
}

function BreakdownChart({ title, rows, total }: { title: string; rows: { label: string; count: number; color: string }[]; total: number }) {
  const max = Math.max(1, ...rows.map((row) => row.count))
  return <section className="chart-card" aria-label={title}><div className="chart-heading"><h3>{title}</h3><span>{total} total</span></div>{total === 0 || rows.length === 0 ? <div className="chart-empty">No matching requests</div> : <div className="bar-list">{rows.map((row) => <div className="bar-row" key={row.label}><span className="bar-label">{row.label}</span><span className="bar-track"><span className="bar-fill" style={{ width: `${(row.count / max) * 100}%`, backgroundColor: row.color }} /></span><strong className="bar-count">{row.count}</strong></div>)}</div>}</section>
}

function chartColor(status: RequestStatus) {
  return ({ Draft: '#8797a1', Submitted: '#397095', Returned: '#c2854f', Approved: '#438c6a' })[status]
}


const EMPTY_DRAFT: RequestDraft = { title: '', description: '', vendor: '', department_id: null, amount: '0.00' }

function RequestFormPage({ user, navigate, onSignOut, requestId }: { user: User; navigate: Navigate; onSignOut: () => void; requestId?: number }) {
  const [draft, setDraft] = useState<RequestDraft>({ ...EMPTY_DRAFT, department_id: user.department_id })
  const [departments, setDepartments] = useState<Department[]>([])
  const [savedId, setSavedId] = useState<number | null>(requestId ?? null)
  const [savedAttachment, setSavedAttachment] = useState<QuotationAttachment | null>(null)
  const [selectedAttachment, setSelectedAttachment] = useState<File | null>(null)
  const [removeAttachment, setRemoveAttachment] = useState(false)
  const [loading, setLoading] = useState(Boolean(requestId))
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editingStatus, setEditingStatus] = useState<'Draft' | 'Returned'>('Draft')
  useEffect(() => {
    let active = true
    Promise.all([api.listDepartments(), requestId ? api.getRequest(requestId) : Promise.resolve(null)])
      .then(([rows, existing]) => {
        if (!active) return
        setDepartments(rows)
        if (existing) {
          if (existing.requester_id !== user.id || !['Draft', 'Returned'].includes(existing.status)) setLoadError('Only your own draft or returned requests can be edited.')
          else {
            setEditingStatus(existing.status as 'Draft' | 'Returned')
            setDraft({ title: existing.title, description: existing.description ?? '', vendor: existing.vendor, department_id: existing.department_id, amount: existing.amount })
            setSavedAttachment(existing.attachment)
          }
        }
      })
      .catch((failure: unknown) => { if (active) setLoadError(failure instanceof Error ? failure.message : 'Could not load the request form.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [requestId, user.id])

  const setField = <Key extends keyof RequestDraft>(key: Key, value: RequestDraft[Key]) => { setDraft((current) => ({ ...current, [key]: value })); setError(''); setSuccess('') }
  const chooseAttachment = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setSelectedAttachment(file)
    setRemoveAttachment(false)
    setError(''); setSuccess('')
  }
  const saveDraft = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setSuccess('')
    if (selectedAttachment && selectedAttachment.size > 5 * 1024 * 1024) {
      setError('PDF files must be 5 MB or smaller. Clear the selection or choose a smaller PDF.')
      return
    }
    setSaving(true)
    try {
      const payload = { ...draft, amount: draft.amount || '0.00' }
      const saved = savedId ? await api.updateRequest(savedId, payload) : await api.createRequest(payload)
      setSavedId(saved.id)

      if (selectedAttachment) {
        try {
          const uploaded = await api.uploadAttachment(saved.id, selectedAttachment)
          setSavedAttachment(uploaded)
          setSelectedAttachment(null)
          setRemoveAttachment(false)
        } catch (failure) {
          const reason = failure instanceof Error ? failure.message : 'Please try again.'
          const partialSave = requestId === undefined && savedId === null
            ? `Draft was saved, but the quotation could not be uploaded: ${reason} The selected PDF is retained. Save again to retry; the existing draft will be reused.`
            : `Request details were saved, but the quotation could not be ${savedAttachment ? 'replaced' : 'uploaded'}: ${reason} The selected PDF is retained${savedAttachment ? ', and the existing quotation remains unchanged' : ''}. Save again to retry.`
          setError(partialSave)
          return
        }
      } else if (removeAttachment && savedAttachment) {
        try {
          await api.deleteAttachment(saved.id)
          setSavedAttachment(null)
          setRemoveAttachment(false)
        } catch (failure) {
          const reason = failure instanceof Error ? failure.message : 'Please try again.'
          setError(`Request details were saved, but the quotation could not be removed: ${reason} The existing quotation remains available. Save again to retry.`)
          return
        }
      }

      setSuccess(editingStatus === 'Returned' ? 'Returned request updated. Resubmit it when ready.' : 'Draft saved successfully.')
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not save the draft.') }
    finally { setSaving(false) }
  }

  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <div className="breadcrumb"><button className="back-link" onClick={() => navigate('/workspace')}>← Back to requests</button></div>
      <section className="page-heading form-page-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> {savedId ? `${editingStatus.toUpperCase()} REQUEST` : 'NEW REQUEST'}</p><h1 className="page-title">{savedId ? 'Edit purchase request' : 'Start a purchase request'}</h1><p className="hero-copy">{editingStatus === 'Returned' ? 'Save your changes, then resubmit the request for review.' : 'Save a draft at any point. Required details are checked when you submit.'}</p></div></section>
      {loading ? <div className="table-card state-block">Loading request details…</div> : <form className="form-card request-form" onSubmit={saveDraft}>
        <div className="form-section-heading"><h2>Request details</h2><span className="required-note">Required before submission</span></div>
        {loadError && <p className="notice notice-error" role="alert">{loadError}</p>}{error && <p className="notice notice-error" role="alert">{error}</p>}{success && <p className="notice notice-success" role="status">{success} {savedId && <button type="button" className="inline-link" onClick={() => navigate(`/requests/${savedId}`)}>View request</button>}</p>}
        <div className="form-grid">
          <div className="form-field form-field-wide"><label className="field-label" htmlFor="request-title">Request title</label><input id="request-title" className="text-input" maxLength={160} value={draft.title} onChange={(event) => setField('title', event.target.value)} placeholder="For example, Laboratory safety supplies" /></div>
          <div className="form-field"><label className="field-label" htmlFor="vendor">Vendor</label><input id="vendor" className="text-input" maxLength={200} value={draft.vendor} onChange={(event) => setField('vendor', event.target.value)} placeholder="Vendor name" /></div>
          <div className="form-field"><label className="field-label" htmlFor="department">Department</label><select id="department" className="text-input" value={draft.department_id ?? ''} onChange={(event) => setField('department_id', event.target.value ? Number(event.target.value) : null)}><option value="">Choose a department</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></div>
          <div className="form-field"><label className="field-label" htmlFor="amount">Estimated amount (USD)</label><div className="amount-input-wrap"><span aria-hidden="true">$</span><input id="amount" className="text-input" type="number" min="0" step="0.01" value={draft.amount} onChange={(event) => setField('amount', event.target.value)} /></div></div>
          <div className="form-field form-field-wide"><label className="field-label" htmlFor="description">Purpose and description</label><textarea id="description" className="text-input text-area" maxLength={5000} rows={5} value={draft.description} onChange={(event) => setField('description', event.target.value)} placeholder="Describe what you need and how it will support campus work." /></div>
        </div>
        <section className="form-attachment-section" aria-labelledby="form-quotation-title">
          <div className="attachment-form-heading"><div><p className="section-kicker">QUOTATION ATTACHMENT</p><h2 id="form-quotation-title">PDF quotation</h2><p className="attachment-hint">Optional · PDF only · Max 5 MB</p></div><label className="attachment-picker"><span className="button button-secondary">{selectedAttachment ? 'Choose another PDF' : savedAttachment && !removeAttachment ? 'Replace PDF' : 'Choose PDF'}</span><input type="file" accept=".pdf,application/pdf" onChange={chooseAttachment} disabled={saving || Boolean(loadError && requestId)} /></label></div>
          {savedAttachment ? <div className={`attachment-file form-saved-attachment ${removeAttachment ? 'attachment-pending-removal' : ''}`}><div><strong>{savedAttachment.original_filename}</strong><span>{formatFileSize(savedAttachment.file_size)} · Uploaded {formatDate(savedAttachment.uploaded_at)}{removeAttachment ? ' · Will be removed when you save' : ' · Current quotation'}</span></div><div className="attachment-links"><a className="button button-secondary" href={api.quotationAttachmentUrl(savedId ?? requestId ?? 0)} target="_blank" rel="noreferrer">View PDF</a><a className="button button-secondary" href={api.quotationAttachmentUrl(savedId ?? requestId ?? 0, true)}>Download</a></div></div> : !selectedAttachment && <p className="attachment-empty">No quotation has been attached.</p>}
          {selectedAttachment && <div className="attachment-file attachment-staged-file"><div><strong>{selectedAttachment.name}</strong><span>{formatFileSize(selectedAttachment.size)} · Selected for this save{savedAttachment ? ' · Will replace the current quotation' : ''}</span></div><button className="text-button" type="button" onClick={() => { setSelectedAttachment(null); setError(''); setSuccess('') }} disabled={saving}>Clear selection</button></div>}
          {savedAttachment && !selectedAttachment && !removeAttachment && <button className="text-button attachment-remove-action" type="button" onClick={() => { setRemoveAttachment(true); setError(''); setSuccess('') }} disabled={saving}>Remove current quotation on save</button>}
          {removeAttachment && <button className="text-button attachment-remove-action" type="button" onClick={() => { setRemoveAttachment(false); setError(''); setSuccess('') }} disabled={saving}>Undo removal</button>}
          {selectedAttachment && selectedAttachment.size > 5 * 1024 * 1024 && <p className="notice notice-error attachment-size-error" role="alert">This file is over the 5 MB limit. Clear the selection or choose a smaller PDF.</p>}
        </section>
        <div className="form-actions"><button className="button button-secondary" type="button" onClick={() => navigate('/workspace')} disabled={saving}>Cancel</button><button className="button button-primary" type="submit" disabled={saving || Boolean(loadError && requestId)}>{saving ? 'Saving…' : savedId && requestId ? 'Save changes' : editingStatus === 'Returned' ? 'Save changes' : 'Save draft'}</button></div>
      </form>}
      <footer className="footer"><span>CampusOps</span><span>Drafts remain private to their applicant.</span></footer>
    </main>
  )
}

function RequestDetailPage({ user, requestId, navigate, onSignOut }: { user: User; requestId: number; navigate: Navigate; onSignOut: () => void }) {
  const [request, setRequest] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [approvalComment, setApprovalComment] = useState('')
  const [returnReason, setReturnReason] = useState('')
  const [resubmitComment, setResubmitComment] = useState('')
  const loadRequest = useCallback(async () => {
    setLoading(true); setError('')
    try { setRequest(await api.getRequest(requestId)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not load this request.') }
    finally { setLoading(false) }
  }, [requestId])
  useEffect(() => { void loadRequest() }, [loadRequest])
  const perform = async (action: () => Promise<unknown>, message: string) => {
    setProcessing(true); setError(''); setSuccess('')
    try { await action(); setRequest(await api.getRequest(requestId)); setSuccess(message) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'The request could not be completed. Please try again.') }
    finally { setProcessing(false) }
  }
  const isOwner = Boolean(request && user.role === 'requester' && request.requester_id === user.id)
  const canEdit = Boolean(isOwner && (request?.status === 'Draft' || request?.status === 'Returned'))
  const canReview = Boolean(user.role === 'admin' && request?.status === 'Submitted')
  const historyEvents = request?.events.filter(isRequestHistoryEvent) ?? []
  const submit = () => {
    if (!window.confirm('Submit this purchase request for review? You will not be able to edit it afterwards.')) return
    void perform(() => api.submitRequest(requestId), 'Purchase request submitted successfully.')
  }
  const resubmit = () => {
    if (!window.confirm('Resubmit this purchase request for review? You will not be able to edit it afterwards.')) return
    void perform(() => api.resubmitRequest(requestId, resubmitComment), 'Purchase request resubmitted successfully.')
  }
  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <div className="breadcrumb"><button className="back-link" onClick={() => navigate('/workspace')}>← Back to requests</button></div>
      {loading ? <div className="table-card state-block">Loading request details…</div> : error && !request ? <section className="table-card state-block"><p className="notice notice-error">{error}</p><button className="button button-secondary" onClick={() => navigate('/workspace')}>Return to requests</button></section> : request ? <>
        <section className="detail-heading"><div className="detail-title-group"><p className="eyebrow"><span className="eyebrow-dot" /> PURCHASE REQUEST #{request.id}</p><h1 className="page-title">{request.title || 'Untitled draft'}</h1><div className="detail-status"><StatusBadge status={request.status} /><span>Updated {formatDate(request.updated_at)}</span></div></div>{canEdit && <div className="detail-actions"><button className="button button-secondary" onClick={() => navigate(`/requests/${request.id}/edit`)}>{request.status === 'Returned' ? 'Edit returned request' : 'Edit draft'}</button>{request.status === 'Draft' ? <button className="button button-primary" onClick={submit} disabled={processing}>{processing ? 'Submitting…' : 'Submit for review'}</button> : null}</div>}</section>
        {error && <p className="notice notice-error page-notice" role="alert">{error}</p>}{success && <p className="notice notice-success page-notice" role="status">{success}</p>}
        {request.status === 'Returned' && isOwner && <section className="review-panel"><div><p className="section-kicker">NEXT STEP</p><h2>Update and resubmit</h2><p className="muted-copy">Save edits first. The request stays returned until you resubmit it.</p></div><label className="review-field"><span>Resubmission note (optional)</span><textarea className="text-input text-area" rows={3} maxLength={2000} value={resubmitComment} onChange={(event) => setResubmitComment(event.target.value)} /></label><button className="button button-primary" onClick={resubmit} disabled={processing}>{processing ? 'Resubmitting…' : 'Resubmit for review'}</button></section>}
        {canReview && <section className="review-panel"><div><p className="section-kicker">ADMIN REVIEW</p><h2>Review this request</h2><p className="muted-copy">Choose a decision. A return reason is required.</p></div><div className="review-fields"><label className="review-field"><span>Approval comment (optional)</span><textarea className="text-input text-area" rows={3} maxLength={2000} value={approvalComment} onChange={(event) => setApprovalComment(event.target.value)} /></label><label className="review-field"><span>Return reason (required)</span><textarea className="text-input text-area" rows={3} maxLength={2000} value={returnReason} onChange={(event) => setReturnReason(event.target.value)} /></label></div><div className="review-actions"><button className="button button-secondary" onClick={() => void perform(() => api.returnRequest(requestId, returnReason), 'Request returned to the applicant.')} disabled={processing || !returnReason.trim()}>{processing ? 'Processing…' : 'Return for changes'}</button><button className="button button-primary" onClick={() => void perform(() => api.approveRequest(requestId, approvalComment), 'Purchase request approved.')} disabled={processing}>{processing ? 'Processing…' : 'Approve'}</button></div></section>}
        <div className="detail-grid">
          <section className="table-card detail-card" aria-labelledby="detail-information-title">
            <div className="table-heading"><div><p className="section-kicker">REQUEST INFORMATION</p><h2 id="detail-information-title">Purchase details</h2></div></div>
            <div className="detail-card-scroll" role="region" aria-label="Purchase details and quotation" tabIndex={0}>
              <dl className="detail-list"><div><dt>Vendor</dt><dd>{request.vendor || 'Not set'}</dd></div><div><dt>Department</dt><dd>{request.department_name ?? 'Not set'}</dd></div><div><dt>Estimated amount</dt><dd className="amount-cell">{formatMoney(request.amount)}</dd></div><div><dt>Applicant</dt><dd>{request.requester_name}</dd></div><div><dt>Created</dt><dd>{formatDate(request.created_at)}</dd></div><div className="detail-description"><dt>Purpose and description</dt><dd>{request.description || 'No description provided.'}</dd></div></dl>
              <section className="detail-quotation" aria-labelledby="detail-quotation-title">
                <div className="detail-quotation-heading"><p className="section-kicker">QUOTATION ATTACHMENT</p><h3 id="detail-quotation-title">PDF quotation</h3></div>
                {request.attachment ? <div className="attachment-file"><div><strong>{request.attachment.original_filename}</strong><span>{formatFileSize(request.attachment.file_size)} · Uploaded {formatDate(request.attachment.uploaded_at)}</span></div><div className="attachment-links"><a className="button button-secondary" href={api.quotationAttachmentUrl(requestId)} target="_blank" rel="noreferrer">View PDF</a><a className="button button-secondary" href={api.quotationAttachmentUrl(requestId, true)}>Download</a></div></div> : <p className="attachment-empty">No quotation has been attached.</p>}
                {canEdit && <p className="attachment-manage-hint">Use Edit above to add, replace, or remove the quotation. Changes are saved with the request.</p>}
              </section>
            </div>
          </section>
          <section className="table-card history-card" aria-labelledby="history-title">
            <div className="table-heading"><div><p className="section-kicker">AUDIT TRAIL</p><h2 id="history-title">Activity history</h2></div></div>
            <div className="history-card-scroll" role="region" aria-label="Request activity history" tabIndex={0}>
              {historyEvents.length === 0 ? <p className="history-empty">No request activity has been recorded yet.</p> : <ol className="timeline">{historyEvents.map((event) => <li className="timeline-item" key={event.id}><span className={`timeline-dot ${['Submitted', 'Resubmitted', 'Approved'].includes(event.event_type) ? 'timeline-dot-active' : ''}`} aria-hidden="true" /><div><strong>{REQUEST_HISTORY_LABELS[event.event_type]}</strong><p>{event.actor_name} · {formatDate(event.created_at)}{event.previous_status !== event.new_status && ` · ${event.previous_status ?? 'New'} → ${event.new_status}`}</p>{event.comment && <p className="event-comment">{event.comment}</p>}</div></li>)}</ol>}
            </div>
          </section>
        </div>
      </> : null}
      <footer className="footer"><span>CampusOps</span><span>Request history is saved with each status change.</span></footer>
    </main>
  )
}

function StatusBadge({ status }: { status: RequestStatus }) { return <span className={`status-badge status-badge-${status.toLowerCase()}`}>{status}</span> }
function PageMessage({ message }: { message: string }) { return <main className="page-shell loading-screen"><span className="brand-mark" aria-hidden="true">C</span><p>{message}</p></main> }
function formatMoney(amount: string) { const value = Number(amount); return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number.isFinite(value) ? value : 0) }
function formatDate(value: string) { return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
function formatFileSize(bytes: number) { return bytes < 1024 * 1024 ? `${bytes.toLocaleString('en-US')} bytes` : `${(bytes / (1024 * 1024)).toFixed(2)} MB` }

export default App
