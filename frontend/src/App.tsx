import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from './api'
import type { Department, PurchaseRequest, RequestDetail, RequestDraft, RequestStatus, User } from './types'

type Navigate = (path: string) => void

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
  if (path === '/' || path === '/workspace') return <WorkspacePage user={user} navigate={navigate} onSignOut={signOut} notice={authError} />
  if (path === '/requests/new' && user.role === 'requester') return <RequestFormPage user={user} navigate={navigate} onSignOut={signOut} />
  if (editMatch && user.role === 'requester') return <RequestFormPage user={user} requestId={Number(editMatch[1])} navigate={navigate} onSignOut={signOut} />
  if (detailMatch) return <RequestDetailPage user={user} requestId={Number(detailMatch[1])} navigate={navigate} onSignOut={signOut} />
  return <WorkspacePage user={user} navigate={navigate} onSignOut={signOut} notice={authError} />
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
      <section className="status-card" aria-labelledby="status-title" aria-live="polite">
        <div className="status-copy"><p className="section-kicker">DEVELOPMENT STATUS</p><h2 id="status-title">Local services</h2></div>
        <div className="status-list"><StatusItem label="API service" connected={health.backend} /><StatusItem label="PostgreSQL" connected={health.database} message={health.message} /></div>
      </section>
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

function WorkspacePage({ user, navigate, onSignOut, notice }: { user: User; navigate: Navigate; onSignOut: () => void; notice: string }) {
  const [requests, setRequests] = useState<PurchaseRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.listRequests().then((rows) => { if (active) setRequests(rows) }).catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load purchase requests.') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <section className="page-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> {user.role === 'admin' ? 'ADMIN WORKSPACE' : 'REQUESTER WORKSPACE'}</p><h1 className="page-title">Purchase requests</h1><p className="hero-copy">{user.role === 'admin' ? 'Review the request queue and open a request to see its history.' : 'Create a draft, refine the details, and submit when it is ready.'}</p></div>{user.role === 'requester' && <button className="button button-primary" onClick={() => navigate('/requests/new')}>New request <span aria-hidden="true">+</span></button>}</section>
      {notice && <p className="notice notice-error page-notice">{notice}</p>}
      <section className="table-card" aria-labelledby="request-list-title">
        <div className="table-heading"><div><p className="section-kicker">REQUEST REGISTER</p><h2 id="request-list-title">{requests.length} {requests.length === 1 ? 'request' : 'requests'}</h2></div><span className="table-role">{user.role === 'admin' ? 'All departments' : user.department_name ?? 'My requests'}</span></div>
        {loading ? <div className="state-block">Loading purchase requests…</div> : error ? <div className="state-block"><p className="notice notice-error">{error}</p><button className="button button-secondary" onClick={() => window.location.reload()}>Try again</button></div> : requests.length === 0 ? <div className="empty-state"><span className="empty-icon" aria-hidden="true">＋</span><h3>No requests yet</h3><p>{user.role === 'admin' ? 'Requests will appear here when applicants create them.' : 'Start with a draft. You can save it now and finish the details later.'}</p>{user.role === 'requester' && <button className="button button-primary" onClick={() => navigate('/requests/new')}>Create a request</button>}</div> : (
          <div className="table-scroll"><table className="request-table"><thead><tr><th>Request</th>{user.role === 'admin' && <th>Applicant</th>}<th>Department</th><th>Amount</th><th>Status</th><th>Updated</th><th><span className="sr-only">Open request</span></th></tr></thead><tbody>
            {requests.map((request) => <tr key={request.id}><td><span className="request-title">{request.title || 'Untitled draft'}</span><span className="request-subtitle">{request.vendor || 'Vendor not set'}</span></td>{user.role === 'admin' && <td>{request.requester_name}</td>}<td>{request.department_name ?? 'Not set'}</td><td className="amount-cell">{formatMoney(request.amount)}</td><td><StatusBadge status={request.status} /></td><td>{formatDate(request.updated_at)}</td><td><button className="row-link" onClick={() => navigate(`/requests/${request.id}`)}>View <span aria-hidden="true">→</span></button></td></tr>)}
          </tbody></table></div>
        )}
      </section>
      <footer className="footer"><span>CampusOps</span><span>Requests are stored in your local PostgreSQL database.</span></footer>
    </main>
  )
}

const EMPTY_DRAFT: RequestDraft = { title: '', description: '', vendor: '', department_id: null, amount: '0.00' }

function RequestFormPage({ user, navigate, onSignOut, requestId }: { user: User; navigate: Navigate; onSignOut: () => void; requestId?: number }) {
  const [draft, setDraft] = useState<RequestDraft>({ ...EMPTY_DRAFT, department_id: user.department_id })
  const [departments, setDepartments] = useState<Department[]>([])
  const [savedId, setSavedId] = useState<number | null>(requestId ?? null)
  const [loading, setLoading] = useState(Boolean(requestId))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  useEffect(() => {
    let active = true
    Promise.all([api.listDepartments(), requestId ? api.getRequest(requestId) : Promise.resolve(null)])
      .then(([rows, existing]) => {
        if (!active) return
        setDepartments(rows)
        if (existing) {
          if (existing.requester_id !== user.id || existing.status !== 'Draft') setError('Only your own draft requests can be edited.')
          else setDraft({ title: existing.title, description: existing.description ?? '', vendor: existing.vendor, department_id: existing.department_id, amount: existing.amount })
        }
      })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load the request form.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [requestId, user.id])

  const setField = <Key extends keyof RequestDraft>(key: Key, value: RequestDraft[Key]) => { setDraft((current) => ({ ...current, [key]: value })); setSuccess('') }
  const saveDraft = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('')
    try {
      const payload = { ...draft, amount: draft.amount || '0.00' }
      const saved = savedId ? await api.updateRequest(savedId, payload) : await api.createRequest(payload)
      setSavedId(saved.id); setSuccess('Draft saved successfully.')
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not save the draft.') }
    finally { setSaving(false) }
  }

  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <div className="breadcrumb"><button className="back-link" onClick={() => navigate('/workspace')}>← Back to requests</button></div>
      <section className="page-heading form-page-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> {savedId ? 'DRAFT REQUEST' : 'NEW REQUEST'}</p><h1 className="page-title">{savedId ? 'Edit purchase request' : 'Start a purchase request'}</h1><p className="hero-copy">Save a draft at any point. Required details are checked when you submit.</p></div></section>
      {loading ? <div className="table-card state-block">Loading request details…</div> : <form className="form-card request-form" onSubmit={saveDraft}>
        <div className="form-section-heading"><h2>Request details</h2><span className="required-note">Required before submission</span></div>
        {error && <p className="notice notice-error" role="alert">{error}</p>}{success && <p className="notice notice-success" role="status">{success} {savedId && <button type="button" className="inline-link" onClick={() => navigate(`/requests/${savedId}`)}>View request</button>}</p>}
        <div className="form-grid">
          <div className="form-field form-field-wide"><label className="field-label" htmlFor="request-title">Request title</label><input id="request-title" className="text-input" maxLength={160} value={draft.title} onChange={(event) => setField('title', event.target.value)} placeholder="For example, Laboratory safety supplies" /></div>
          <div className="form-field"><label className="field-label" htmlFor="vendor">Vendor</label><input id="vendor" className="text-input" maxLength={200} value={draft.vendor} onChange={(event) => setField('vendor', event.target.value)} placeholder="Vendor name" /></div>
          <div className="form-field"><label className="field-label" htmlFor="department">Department</label><select id="department" className="text-input" value={draft.department_id ?? ''} onChange={(event) => setField('department_id', event.target.value ? Number(event.target.value) : null)}><option value="">Choose a department</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></div>
          <div className="form-field"><label className="field-label" htmlFor="amount">Estimated amount (USD)</label><div className="amount-input-wrap"><span aria-hidden="true">$</span><input id="amount" className="text-input" type="number" min="0" step="0.01" value={draft.amount} onChange={(event) => setField('amount', event.target.value)} /></div></div>
          <div className="form-field form-field-wide"><label className="field-label" htmlFor="description">Purpose and description</label><textarea id="description" className="text-input text-area" maxLength={5000} rows={5} value={draft.description} onChange={(event) => setField('description', event.target.value)} placeholder="Describe what you need and how it will support campus work." /></div>
        </div>
        <div className="form-actions"><button className="button button-secondary" type="button" onClick={() => navigate('/workspace')}>Cancel</button><button className="button button-primary" type="submit" disabled={saving || Boolean(error && requestId)}>{saving ? 'Saving…' : 'Save draft'}</button></div>
      </form>}
      <footer className="footer"><span>CampusOps</span><span>Drafts remain private to their applicant.</span></footer>
    </main>
  )
}

function RequestDetailPage({ user, requestId, navigate, onSignOut }: { user: User; requestId: number; navigate: Navigate; onSignOut: () => void }) {
  const [request, setRequest] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const loadRequest = useCallback(async () => {
    setLoading(true); setError('')
    try { setRequest(await api.getRequest(requestId)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not load this request.') }
    finally { setLoading(false) }
  }, [requestId])
  useEffect(() => { void loadRequest() }, [loadRequest])
  const submit = async () => {
    if (!window.confirm('Submit this purchase request for review? You will not be able to edit it afterwards.')) return
    setSubmitting(true); setError(''); setSuccess('')
    try { await api.submitRequest(requestId); setRequest(await api.getRequest(requestId)); setSuccess('Purchase request submitted successfully.') }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not submit this request.') }
    finally { setSubmitting(false) }
  }
  const canEdit = Boolean(request && user.role === 'requester' && request.requester_id === user.id && request.status === 'Draft')

  return (
    <main className="page-shell app-shell">
      <TopBar navigate={navigate} user={user} onSignOut={onSignOut} />
      <div className="breadcrumb"><button className="back-link" onClick={() => navigate('/workspace')}>← Back to requests</button></div>
      {loading ? <div className="table-card state-block">Loading request details…</div> : error && !request ? <section className="table-card state-block"><p className="notice notice-error">{error}</p><button className="button button-secondary" onClick={() => navigate('/workspace')}>Return to requests</button></section> : request ? <>
        <section className="detail-heading"><div className="detail-title-group"><p className="eyebrow"><span className="eyebrow-dot" /> PURCHASE REQUEST #{request.id}</p><h1 className="page-title">{request.title || 'Untitled draft'}</h1><div className="detail-status"><StatusBadge status={request.status} /><span>Updated {formatDate(request.updated_at)}</span></div></div>{canEdit && <div className="detail-actions"><button className="button button-secondary" onClick={() => navigate(`/requests/${request.id}/edit`)}>Edit draft</button><button className="button button-primary" onClick={submit} disabled={submitting}>{submitting ? 'Submitting…' : 'Submit for review'}</button></div>}</section>
        {error && <p className="notice notice-error page-notice" role="alert">{error}</p>}{success && <p className="notice notice-success page-notice" role="status">{success}</p>}
        <div className="detail-grid">
          <section className="table-card detail-card" aria-labelledby="detail-information-title"><div className="table-heading"><div><p className="section-kicker">REQUEST INFORMATION</p><h2 id="detail-information-title">Purchase details</h2></div></div><dl className="detail-list"><div><dt>Vendor</dt><dd>{request.vendor || 'Not set'}</dd></div><div><dt>Department</dt><dd>{request.department_name ?? 'Not set'}</dd></div><div><dt>Estimated amount</dt><dd className="amount-cell">{formatMoney(request.amount)}</dd></div><div><dt>Applicant</dt><dd>{request.requester_name}</dd></div><div><dt>Created</dt><dd>{formatDate(request.created_at)}</dd></div><div className="detail-description"><dt>Purpose and description</dt><dd>{request.description || 'No description provided.'}</dd></div></dl></section>
          <section className="table-card history-card" aria-labelledby="history-title"><div className="table-heading"><div><p className="section-kicker">AUDIT TRAIL</p><h2 id="history-title">Activity history</h2></div></div>{request.events.length === 0 ? <p className="muted-copy">No activity recorded yet.</p> : <ol className="timeline">{request.events.map((event) => <li className="timeline-item" key={event.id}><span className={`timeline-dot ${event.event_type === 'Submitted' ? 'timeline-dot-active' : ''}`} aria-hidden="true" /><div><strong>{event.event_type === 'Submitted' ? 'Request submitted' : event.event_type === 'Created' ? 'Draft created' : 'Draft updated'}</strong><p>{event.actor_name} · {formatDate(event.created_at)}</p></div></li>)}</ol>}</section>
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

export default App
