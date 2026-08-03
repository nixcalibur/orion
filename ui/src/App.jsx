import React, { useEffect, useState, useCallback } from 'react'
import {
  checkHealth,
  listAssessments,
  getAssessment,
  uploadAssessment,
  startFromPath,
  submitReview,
} from './api.js'

const LEVEL_OPTIONS = ['APPROVE', 'CONDITIONAL', 'DEFER', 'REJECT']

const LEVEL_LABELS = {
  APPROVE: 'Approve',
  CONDITIONAL: 'Approve with conditions',
  DEFER: 'Defer',
  REJECT: 'Reject',
  PENDING: 'Pending',
}

const STAGE_LABELS = {
  starting: 'Starting…',
  ingest: 'Reading documents…',
  extract: 'Analyzing with AI…',
  score: 'Scoring risk…',
  deliver: 'Finalizing result…',
  complete: 'Done',
  error: 'Failed',
}

const REVIEW_STATUS_LABELS = {
  PENDING: 'Pending',
  ACCEPTED: 'Accepted',
  OVERRIDDEN: 'Overridden',
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString()
}

function Badge({ value, type = 'level' }) {
  const cls = `badge-${value}`
  const label = type === 'status'
    ? (REVIEW_STATUS_LABELS[value] || LEVEL_LABELS[value] || value)
    : (LEVEL_LABELS[value] || value)
  return <span className={`badge ${cls}`} title={value}>{label}</span>
}

export default function App() {
  const [view, setView] = useState('upload')
  const [assessments, setAssessments] = useState([])
  const [current, setCurrent] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [apiOk, setApiOk] = useState(true)

  const refreshList = useCallback(async () => {
    try {
      const rows = await listAssessments()
      setAssessments(rows)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    checkHealth().then(() => setApiOk(true)).catch(() => setApiOk(false))
    refreshList()
  }, [refreshList])

  function Error({ message }) {
    return message ? <div className="error">{message}</div> : null
  }

  function UploadView() {
    const [files, setFiles] = useState([])
    const [path, setPath] = useState('')
    const [showAdvanced, setShowAdvanced] = useState(false)
    const [submitting, setSubmitting] = useState(false)

    async function start(job) {
      setError(null)
      setSubmitting(true)
      try {
        setView('detail')
        setCurrent({ submission_id: job.submission_id, status: 'running', stage: job.stage || 'starting' })
        refreshList()
      } catch (e) {
        setError(e.message)
      } finally {
        setSubmitting(false)
      }
    }

    async function handleSubmit(e) {
      e.preventDefault()
      setError(null)
      setSubmitting(true)
      try {
        let job
        if (path.trim()) {
          job = await startFromPath(path.trim())
        } else if (files.length) {
          const form = new FormData()
          const first = files[0]
          const isJson = first.name.toLowerCase().endsWith('.json')
          if (isJson) {
            form.append('submission', first)
            files.slice(1).forEach((f) => form.append('docs', f))
          } else {
            files.forEach((f) => form.append('docs', f))
          }
          job = await uploadAssessment(form)
        } else {
          throw new Error('Upload a submission or use the sample button.')
        }
        await start(job)
      } catch (e) {
        setError(e.message)
      } finally {
        setSubmitting(false)
      }
    }

    async function trySample() {
      setError(null)
      setSubmitting(true)
      try {
        const job = await startFromPath('dataset/e272b3cb/submission.json')
        await start(job)
      } catch (e) {
        setError(e.message)
        setSubmitting(false)
      }
    }

    return (
      <div>
        <div className="card">
          <h2>Start a review</h2>
          <p className="hint">Upload a submission and supporting documents, or try a sample.</p>

          <div className="form-row">
            <label>Upload files</label>
            <input
              type="file"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files))}
            />
            <p className="hint">
              A JSON submission plus its documents, or a single PDF/DOCX/XLSX/TXT file.
              You can also drop several loose documents at once.
            </p>
          </div>

          <div className="actions">
            <button className="primary" disabled={submitting} onClick={handleSubmit}>
              {submitting && <span className="spinner" />} Run assessment
            </button>
            <button className="secondary" disabled={submitting} onClick={trySample}>
              Try a sample submission
            </button>
          </div>

          <div className="form-row" style={{ marginTop: 20 }}>
            <button type="button" className="small" onClick={() => setShowAdvanced(!showAdvanced)}>
              {showAdvanced ? 'Hide advanced' : 'Advanced: use a local path'}
            </button>
            {showAdvanced && (
              <div style={{ marginTop: 10 }}>
                <input
                  type="text"
                  placeholder="dataset/e272b3cb/submission.json"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                />
                <p className="hint">For demos only. The API server must be able to read this path.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  function QueueView() {
    return (
      <div>
        <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>Assessment queue</h2>
          <button className="secondary" onClick={refreshList}>Refresh</button>
        </div>
        {assessments.length === 0 ? (
          <div className="card empty">
            No assessments yet. Upload a submission or try the sample to get started.
          </div>
        ) : (
          <ul className="list card">
            {assessments.map((a) => (
              <li key={a.submission_id} className="list-row" onClick={() => { setCurrent(null); setView('detail'); loadAssessment(a.submission_id) }}>
                <div>
                  <strong>{a.applicant_name || a.submission_id}</strong>
                  <div className="small" style={{ color: '#6b7280' }}>
                    {formatDate(a.assessed_at)} · risk score <span className="score-value">{a.composite_score ?? '—'}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Badge value={a.authorization_level || 'PENDING'} />
                  <Badge value={a.review_status || 'PENDING'} type="status" />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  async function loadAssessment(id) {
    setLoading(true)
    setError(null)
    try {
      const data = await getAssessment(id)
      setCurrent(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function DetailView() {
    const id = current?.submission_id
    const [polling, setPolling] = useState(current?.status === 'running')
    const [reviewerId, setReviewerId] = useState('')
    const [overrideLevel, setOverrideLevel] = useState('')
    const [notes, setNotes] = useState('')

    useEffect(() => {
      if (!id) return
      if (!polling) return
      const interval = setInterval(async () => {
        try {
          const data = await getAssessment(id)
          setCurrent(data)
          if (data.status === 'error' || data.status !== 'running') {
            setPolling(false)
            refreshList()
          }
        } catch (e) {
          setError('Could not check assessment progress. Please retry.')
          setPolling(false)
        }
      }, 1500)
      return () => clearInterval(interval)
    }, [id, polling])

    async function handleAccept() {
      if (!reviewerId.trim()) return setError('Please enter your name.')
      setError(null)
      try {
        await submitReview(id, { status: 'ACCEPTED', reviewer_id: reviewerId.trim(), notes: notes || undefined })
        const data = await getAssessment(id)
        setCurrent(data)
        refreshList()
      } catch (e) {
        setError(e.message)
      }
    }

    async function handleOverride() {
      if (!reviewerId.trim()) return setError('Please enter your name.')
      if (!overrideLevel) return setError('Choose an override decision.')
      setError(null)
      try {
        await submitReview(id, {
          status: 'OVERRIDDEN',
          reviewer_id: reviewerId.trim(),
          override_level: overrideLevel,
          notes: notes || undefined,
        })
        const data = await getAssessment(id)
        setCurrent(data)
        refreshList()
      } catch (e) {
        setError(e.message)
      }
    }

    if (!current) {
      return <div className="card empty">Select an assessment from the queue to review it.</div>
    }

    if (current.status === 'running') {
      const stageLabel = STAGE_LABELS[current.stage] || STAGE_LABELS.starting
      const stages = ['starting', 'ingest', 'extract', 'score', 'deliver']
      const stageIndex = stages.indexOf(current.stage)
      return (
        <div className="card empty">
          <div style={{ marginBottom: 12 }}>
            <span className="spinner" style={{ width: 24, height: 24, marginRight: 12 }} />
            <strong>{stageLabel}</strong>
          </div>
          <div className="progress">
            {stages.map((s, i) => (
              <div key={s} className={`progress-step ${i <= stageIndex ? 'active' : ''}`} />
            ))}
          </div>
          <p className="hint">This usually takes 10–30 seconds. The result will appear automatically.</p>
        </div>
      )
    }

    if (current.status === 'error') {
      return (
        <div className="card empty">
          <h2 style={{ marginTop: 0, color: '#991b1b' }}>Assessment failed</h2>
          <p className="hint">Something went wrong while running this assessment. The details below are for support.</p>
          <div className="error" style={{ textAlign: 'left' }}>
            <strong>{current.detail || 'Unknown error'}</strong>
          </div>
          <div className="actions" style={{ justifyContent: 'center' }}>
            <button className="secondary" onClick={() => setView('queue')}>Back to queue</button>
            <button className="primary" onClick={() => setView('upload')}>Try again</button>
          </div>
        </div>
      )
    }

    const review = current.review || {}
    const decided = review.status === 'ACCEPTED' || review.status === 'OVERRIDDEN'

    return (
      <div>
        <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2 style={{ marginTop: 0 }}>{current.applicant_name || current.submission_id}</h2>
            <div className="summary">{current.summary}</div>
            <div className="score-pill">
              Recommendation <Badge value={current.recommendation} /> · risk score <span className="score-value">{current.composite_score}</span>
              <span className="hint" style={{ marginLeft: 8 }}>(0 = low risk, 10 = high risk)</span>
            </div>
            <div className="hint" style={{ marginTop: 8, fontStyle: 'italic' }}>
              AI extracts facts from the documents; deterministic rules compute the score; you make the final decision.
            </div>
          </div>
          {decided && <Badge value={review.status} type="status" />}
        </div>

        {(current.fail_closed_reasons?.length > 0) && (
          <div className="warning" style={{ borderLeft: '4px solid #dc2626' }}>
            <strong>Fail-closed rule matched:</strong> {current.fail_closed_reasons.join(', ')}.
            This recommendation is driven by a mandatory rule, not the numeric score.
          </div>
        )}

        {current.warnings?.length > 0 && (
          <div>
            {current.warnings.map((w, i) => (
              <div key={i} className="warning">⚠ {w}</div>
            ))}
          </div>
        )}

        <div className="card">
          <h2>Top concerns</h2>
          {current.top_concerns?.length ? (
            <ul>
              {current.top_concerns.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          ) : (
            <p className="hint">No major concerns flagged.</p>
          )}
        </div>

        <div className="card">
          <h2>Evidence</h2>
          <p className="hint">Excerpts below were matched against the uploaded documents before being used.</p>
          {current.evidence_list?.length ? (
            current.evidence_list.map((e, i) => (
              <div key={i} className="evidence">
                <div className="source">{e.dimension} · {e.source}</div>
                <div className="excerpt">“{e.excerpt}”</div>
                {e.supporting_details && <div className="small">{e.supporting_details}</div>}
              </div>
            ))
          ) : (
            <p className="hint">No verified evidence excerpts.</p>
          )}
        </div>

        <div className="card">
          <h2>Follow-up questions</h2>
          {current.followup_questions?.length ? (
            <ol>
              {current.followup_questions.map((q, i) => <li key={i}>{q}</li>)}
            </ol>
          ) : (
            <p className="hint">No follow-ups generated.</p>
          )}
        </div>

        <div className="card">
          <h2>Reviewer decision</h2>
          {decided ? (
            <div>
              <p><Badge value={review.status} type="status" /> by <strong>{review.reviewer_id}</strong> on {formatDate(review.reviewed_at)}</p>
              {review.override_level && (
                <p>Override decision: <strong>{LEVEL_LABELS[review.override_level] || review.override_level}</strong></p>
              )}
              {review.notes && <p className="hint">{review.notes}</p>}
            </div>
          ) : (
            <>
              <div className="form-row">
                <label>Your name *</label>
                <input type="text" value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="e.g. Alice Smith" />
              </div>
              <div className="form-row">
                <label>Notes</label>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional rationale" />
              </div>
              <div className="form-row">
                <label>Override decision (choose only if overriding)</label>
                <select value={overrideLevel} onChange={(e) => setOverrideLevel(e.target.value)}>
                  <option value="">—</option>
                  {LEVEL_OPTIONS.map((l) => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                </select>
              </div>
              <div className="actions">
                <button className="primary" onClick={handleAccept}>Accept recommendation</button>
                <button className="danger" onClick={handleOverride} disabled={!overrideLevel}>Override</button>
              </div>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="container">
      <header>
        <h1><span>ORION</span> Reviewer</h1>
        <nav>
          <button className={view === 'upload' ? 'active' : ''} onClick={() => setView('upload')}>Upload</button>
          <button className={view === 'queue' ? 'active' : ''} onClick={() => setView('queue')}>Queue</button>
          <button className={view === 'detail' ? 'active' : ''} onClick={() => setView('detail')}>Detail</button>
        </nav>
      </header>
      {!apiOk && <div className="error">Cannot reach the ORION backend. Please make sure the API server is running.</div>}
      <Error message={error} />
      {view === 'upload' && <UploadView />}
      {view === 'queue' && <QueueView />}
      {view === 'detail' && <DetailView />}
    </div>
  )
}
