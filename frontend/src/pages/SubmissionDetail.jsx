import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, Cell, Tooltip, ResponsiveContainer,
} from 'recharts'
import { ArrowLeft, CheckCircle2, AlertTriangle } from 'lucide-react'
import api from '../api/client.js'
import Badge from '../components/Badge.jsx'

const DIM_LABELS = {
  ownership: 'Ownership',
  aml_present: 'AML/CFT Policy',
  regulatory_history: 'Regulatory History',
  cyber: 'Cyber Security',
  financial_health: 'Financial Health',
  privacy: 'Privacy',
  has_pep: 'PEP Exposure',
  has_criminal_flag: 'Criminal Flag',
  missing_docs: 'Missing Docs',
}

function fmt(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function ScoreBar({ score }) {
  const pct = Math.min(((score ?? 0) / 10) * 100, 100)
  const color = score < 2 ? '#22c55e' : score < 4.5 ? '#f59e0b' : score < 9 ? '#f97316' : '#ef4444'
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-slate-400">Composite Risk Score</span>
        <span className="font-bold text-white">{score?.toFixed(2)} / 10</span>
      </div>
      <div className="h-3 rounded-full overflow-hidden" style={{ background: '#2a2d3e' }}>
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>Low risk</span><span>High risk</span>
      </div>
    </div>
  )
}

function ProfileField({ label, value }) {
  const display = value === true ? 'Yes' : value === false ? 'No' : (value ?? '—')
  const isRisk = value === true || ['opaque', 'major_issues', 'inadequate', 'distressed', 'non_compliant'].includes(value)
  return (
    <div className="rounded-lg px-4 py-3" style={{ background: '#0f1117', border: '1px solid #2a2d3e' }}>
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-sm font-medium ${isRisk ? 'text-red-400' : 'text-slate-200'}`}>
        {String(display).replace(/_/g, ' ')}
      </p>
    </div>
  )
}

function ReviewPanel({ submissionId, existing, authLevel }) {
  const [action, setAction] = useState('accept')
  const [reviewerId, setReviewerId] = useState('')
  const [overrideLevel, setOverrideLevel] = useState(authLevel ?? 'APPROVE')
  const [notes, setNotes] = useState('')
  const [saved, setSaved] = useState(existing)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!reviewerId.trim()) { setErr('Reviewer ID required'); return }
    setSaving(true); setErr('')
    try {
      const body = { action, reviewer_id: reviewerId, notes }
      if (action === 'override') body.override_level = overrideLevel
      const r = await api.post(`/submissions/${submissionId}/review`, body)
      setSaved(r.data)
    } catch {
      setErr('Failed to save review.')
    } finally {
      setSaving(false)
    }
  }

  if (saved) {
    return (
      <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
        <div className="flex items-center gap-2 text-green-400 mb-3">
          <CheckCircle2 size={16} />
          <span className="text-sm font-medium">Review recorded</span>
        </div>
        <div className="space-y-1.5 text-sm">
          <div><span className="text-slate-500">Status: </span><span className="text-white">{saved.status}</span></div>
          <div><span className="text-slate-500">Reviewer: </span><span className="text-white">{saved.reviewer_id}</span></div>
          {saved.override_level && (
            <div className="flex items-center gap-2"><span className="text-slate-500">Override: </span><Badge level={saved.override_level} /></div>
          )}
          {saved.notes && <div><span className="text-slate-500">Notes: </span><span className="text-slate-300">{saved.notes}</span></div>}
        </div>
        <button onClick={() => setSaved(null)} className="mt-3 text-xs text-blue-400 hover:text-blue-300">
          Update review
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
      <h3 className="text-sm font-medium text-white mb-4">Reviewer Action</h3>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex gap-2">
          {['accept', 'override'].map((a) => (
            <button
              key={a} type="button" onClick={() => setAction(a)}
              className={['flex-1 py-2 rounded-lg text-sm font-medium transition-colors capitalize',
                action === a ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'].join(' ')}
              style={action !== a ? { background: '#0f1117', border: '1px solid #2a2d3e' } : {}}
            >
              {a}
            </button>
          ))}
        </div>

        {action === 'override' && (
          <div>
            <label className="text-xs text-slate-400 block mb-1.5">Override to level</label>
            <select
              value={overrideLevel} onChange={(e) => setOverrideLevel(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm text-white outline-none"
              style={{ background: '#0f1117', border: '1px solid #2a2d3e' }}
            >
              {['APPROVE', 'CONDITIONAL', 'DEFER', 'REJECT'].map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="text-xs text-slate-400 block mb-1.5">Reviewer ID *</label>
          <input
            value={reviewerId} onChange={(e) => setReviewerId(e.target.value)}
            placeholder="e.g. john.doe"
            className="w-full px-3 py-2 rounded-lg text-sm text-white placeholder-slate-600 outline-none focus:ring-1 focus:ring-blue-500"
            style={{ background: '#0f1117', border: '1px solid #2a2d3e' }}
          />
        </div>

        <div>
          <label className="text-xs text-slate-400 block mb-1.5">Notes</label>
          <textarea
            value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
            placeholder="Optional rationale…"
            className="w-full px-3 py-2 rounded-lg text-sm text-white placeholder-slate-600 outline-none resize-none focus:ring-1 focus:ring-blue-500"
            style={{ background: '#0f1117', border: '1px solid #2a2d3e' }}
          />
        </div>

        {err && <p className="text-xs text-red-400">{err}</p>}

        <button
          type="submit" disabled={saving}
          className="w-full py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving…' : action === 'accept' ? 'Accept Assessment' : 'Submit Override'}
        </button>
      </form>
    </div>
  )
}

export default function SubmissionDetail() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    api.get(`/submissions/${id}`)
      .then((r) => setData(r.data))
      .catch((e) => { if (e.response?.status === 404) setNotFound(true) })
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="flex items-center justify-center h-64 text-slate-500">Loading…</div>
  if (notFound) return (
    <div className="text-center py-20">
      <p className="text-slate-400 mb-4">Submission not found.</p>
      <Link to="/submissions" className="text-blue-400 hover:text-blue-300 text-sm">← Back to list</Link>
    </div>
  )

  const profile = data.extracted_profile ?? {}
  const dimData = Object.entries(data.dimension_scores ?? {}).map(([key, val]) => ({
    name: DIM_LABELS[key] ?? key,
    value: val,
  }))

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Link to="/submissions" className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white">
        <ArrowLeft size={14} /> Submissions
      </Link>

      {/* Header */}
      <div className="rounded-xl p-6" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white">{data.applicant_name ?? data.submission_id}</h1>
            <p className="text-slate-400 text-sm mt-1">
              ID: <span className="font-mono text-slate-300">{data.submission_id}</span>
              {data.jurisdiction && <> · {data.jurisdiction}</>}
              {data.incorporation_date && <> · Est. {data.incorporation_date}</>}
            </p>
            <p className="text-xs text-slate-500 mt-1">Assessed {fmt(data.timestamp)}</p>
          </div>
          <Badge level={data.authorization_level} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Score gauge */}
          <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
            <ScoreBar score={data.composite_score} />
          </div>

          {/* Dimension scores */}
          {dimData.length > 0 && (
            <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
              <h2 className="text-sm font-medium text-slate-300 mb-4">Dimension Scores</h2>
              <ResponsiveContainer width="100%" height={dimData.length * 36 + 20}>
                <BarChart layout="vertical" data={dimData} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                  <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} domain={[0, 'dataMax + 0.5']} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#94a3b8' }} width={130} />
                  <Tooltip
                    contentStyle={{ background: '#1a1d2e', border: '1px solid #2a2d3e', borderRadius: 8 }}
                    itemStyle={{ color: '#e2e8f0' }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {dimData.map((entry) => (
                      <Cell key={entry.name} fill={entry.value === 0 ? '#22c55e' : entry.value <= 1 ? '#f59e0b' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Risk profile */}
          <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
            <h2 className="text-sm font-medium text-slate-300 mb-4">Risk Profile</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <ProfileField label="Ownership" value={profile.ownership} />
              <ProfileField label="AML/CFT Policy" value={profile.aml_present} />
              <ProfileField label="Regulatory History" value={profile.regulatory_history} />
              <ProfileField label="Cyber Security" value={profile.cyber} />
              <ProfileField label="Financial Health" value={profile.financial_health} />
              <ProfileField label="Privacy" value={profile.privacy} />
              <ProfileField label="PEP Exposure" value={profile.has_pep} />
              <ProfileField label="Criminal Flag" value={profile.has_criminal_flag} />
            </div>
          </div>

          {/* Key findings */}
          {data.key_findings?.length > 0 && (
            <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
              <h2 className="text-sm font-medium text-slate-300 mb-3">Key Findings</h2>
              <ul className="space-y-2">
                {data.key_findings.map((f, i) => (
                  <li key={i} className="flex gap-2 text-sm text-slate-300">
                    <span className="text-blue-400 mt-0.5 flex-shrink-0">•</span>{f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Follow-up questions */}
          {data.followup_questions?.length > 0 && (
            <div className="rounded-xl p-5" style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.2)' }}>
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle size={14} className="text-amber-400" />
                <h2 className="text-sm font-medium text-amber-400">Follow-up Questions Required</h2>
              </div>
              <ol className="space-y-3">
                {data.followup_questions.map((q, i) => (
                  <li key={i} className="flex gap-3 text-sm text-amber-100/80">
                    <span className="text-amber-500 font-semibold flex-shrink-0">{i + 1}.</span>{q}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Activities */}
          <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
            <h2 className="text-sm font-medium text-slate-300 mb-4">Activities</h2>
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: 'Declared', items: data.declared_activities, color: '#60a5fa' },
                { label: 'Verified', items: data.activities_verified, color: '#22c55e' },
                { label: 'Undeclared', items: data.activities_undeclared, color: '#ef4444' },
              ].map(({ label, items, color }) => (
                <div key={label}>
                  <p className="text-xs font-semibold mb-2" style={{ color }}>{label}</p>
                  {items?.length > 0
                    ? items.map((a, i) => <p key={i} className="text-xs text-slate-400 py-0.5">{a}</p>)
                    : <p className="text-xs text-slate-600">None</p>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Reviewer panel */}
        <div>
          <ReviewPanel submissionId={id} existing={data.review} authLevel={data.authorization_level} />
        </div>
      </div>
    </div>
  )
}
