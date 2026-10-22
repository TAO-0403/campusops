import { useEffect, useState } from 'react'

type HealthResponse = {
  status: 'ok' | 'degraded'
  backend: 'ok'
  database: {
    status: 'ok' | 'error'
    message: string
  }
}

type CheckState = 'checking' | 'ok' | 'error'

function App() {
  const [backendStatus, setBackendStatus] = useState<CheckState>('checking')
  const [databaseStatus, setDatabaseStatus] = useState<CheckState>('checking')
  const [databaseMessage, setDatabaseMessage] = useState('Checking database connection…')

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/health')
        const health = (await response.json()) as HealthResponse
        setBackendStatus(health.backend === 'ok' ? 'ok' : 'error')
        setDatabaseStatus(health.database.status === 'ok' ? 'ok' : 'error')
        setDatabaseMessage(health.database.message)
      } catch {
        setBackendStatus('error')
        setDatabaseStatus('error')
        setDatabaseMessage('Could not reach the API. Make sure the backend is running.')
      }
    }

    void checkHealth()
  }, [])

  return (
    <main className="page-shell">
      <nav className="topbar" aria-label="Main navigation">
        <a className="brand" href="/" aria-label="CampusOps home">
          <span className="brand-mark" aria-hidden="true">C</span>
          <span>Campus<span className="brand-accent">Ops</span></span>
        </a>
        <span className="topbar-label">PROCUREMENT WORKSPACE</span>
      </nav>

      <section className="hero" aria-labelledby="hero-title">
        <p className="eyebrow"><span className="eyebrow-dot" /> CAMPUS PROCUREMENT</p>
        <h1 id="hero-title">Good decisions start<br />with a clear process.</h1>
        <p className="hero-copy">
          A thoughtful home for campus purchasing requests, approvals, and the people behind them.
        </p>
      </section>

      <section className="workspace-card" aria-labelledby="workspace-title">
        <div className="workspace-heading">
          <div>
            <p className="section-kicker">YOUR WORKSPACE</p>
            <h2 id="workspace-title">Everything in its right place.</h2>
          </div>
          <span className="workspace-icon" aria-hidden="true">✳</span>
        </div>
        <div className="feature-grid">
          <article className="feature-card">
            <span className="feature-index">01</span>
            <h3>Purchase requests</h3>
            <p>Bring the details, purpose, and cost together in one clear request.</p>
          </article>
          <article className="feature-card">
            <span className="feature-index">02</span>
            <h3>Thoughtful review</h3>
            <p>Give every decision a clear owner and a reliable next step.</p>
          </article>
          <article className="feature-card">
            <span className="feature-index">03</span>
            <h3>A complete record</h3>
            <p>Keep a useful history of decisions, updates, and outcomes.</p>
          </article>
        </div>
      </section>

      <section className="status-card" aria-labelledby="status-title" aria-live="polite">
        <div className="status-copy">
          <p className="section-kicker">DEVELOPMENT STATUS</p>
          <h2 id="status-title">Local services</h2>
        </div>
        <div className="status-list">
          <StatusItem label="API service" status={backendStatus} />
          <StatusItem label="PostgreSQL" status={databaseStatus} message={databaseMessage} />
        </div>
      </section>

      <footer className="footer">
        <span>CampusOps</span>
        <span>Built for better campus purchasing.</span>
      </footer>
    </main>
  )
}

function StatusItem({ label, status, message }: { label: string; status: CheckState; message?: string }) {
  const statusLabel = status === 'checking' ? 'Checking' : status === 'ok' ? 'Connected' : 'Unavailable'

  return (
    <div className="status-item" title={message}>
      <span className={`status-dot status-${status}`} aria-hidden="true" />
      <span className="status-name">{label}</span>
      <span className={`status-value status-text-${status}`}>{statusLabel}</span>
    </div>
  )
}

export default App
