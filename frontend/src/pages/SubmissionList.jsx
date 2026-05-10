import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, Loader2 } from 'lucide-react'
import api from '../api/client.js'
import Badge from '../components/Badge.jsx'

const LEVELS = ['ALL', 'APPROVE', 'CONDITIONAL', 'DEFER', 'REJECT']

function fmt(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export default function SubmissionList() {
  const [submissions, setSubmissions] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('ALL')

  useEffect(() => {
    api.get('/submissions')
      .then((r) => setSubmissions(r.data))
      .finally(() => setLoading(false))
  }, [])

  const filtered = submissions.filter((s) => {
    const matchesLevel = filter === 'ALL' || s.authorization_level === filter
    const q = search.toLowerCase()
    const matchesSearch =
      !q ||
      (s.applicant_name ?? '').toLowerCase().includes(q) ||
      (s.submission_id ?? '').toLowerCase().includes(q) ||
      (s.jurisdiction ?? '').toLowerCase().includes(q)
    return matchesLevel && matchesSearch
  })

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-white">Submissions</h1>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search by applicant, ID, or jurisdiction…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg text-sm text-white placeholder-slate-500 outline-none focus:ring-1 focus:ring-blue-500"
            style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {LEVELS.map((l) => (
            <button
              key={l}
              onClick={() => setFilter(l)}
              className={[
                'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                filter === l ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white',
              ].join(' ')}
              style={filter !== l ? { background: '#1a1d2e', border: '1px solid #2a2d3e' } : {}}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
        {loading ? (
          <div className="flex items-center justify-center py-16 text-slate-500 gap-2">
            <Loader2 size={16} className="animate-spin" /> Loading…
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 uppercase tracking-wide" style={{ borderBottom: '1px solid #2a2d3e' }}>
                <th className="px-5 py-3 text-left font-medium">Applicant</th>
                <th className="px-5 py-3 text-left font-medium">ID</th>
                <th className="px-5 py-3 text-left font-medium">Jurisdiction</th>
                <th className="px-5 py-3 text-left font-medium">Score</th>
                <th className="px-5 py-3 text-left font-medium">Level</th>
                <th className="px-5 py-3 text-left font-medium">Date</th>
                <th className="px-5 py-3 text-left font-medium">Status</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s, i) => (
                <tr
                  key={s.submission_id}
                  style={{ borderTop: i > 0 ? '1px solid #2a2d3e' : undefined }}
                  className="hover:bg-white/[0.02]"
                >
                  <td className="px-5 py-3 text-white font-medium">{s.applicant_name ?? '—'}</td>
                  <td className="px-5 py-3 text-slate-400 font-mono text-xs">{s.submission_id}</td>
                  <td className="px-5 py-3 text-slate-400">{s.jurisdiction ?? '—'}</td>
                  <td className="px-5 py-3 text-slate-300">
                    {s.composite_score != null ? s.composite_score.toFixed(2) : '—'}
                  </td>
                  <td className="px-5 py-3">
                    {s.status === 'processing'
                      ? <span className="flex items-center gap-1.5 text-xs text-slate-400"><Loader2 size={12} className="animate-spin" /> Processing</span>
                      : <Badge level={s.authorization_level} />
                    }
                  </td>
                  <td className="px-5 py-3 text-slate-400">{fmt(s.assessed_at)}</td>
                  <td className="px-5 py-3">
                    {s.status === 'error' && <span className="text-xs text-red-400 font-medium">Error</span>}
                    {s.status === 'complete' && <span className="text-xs text-green-500 font-medium">Complete</span>}
                    {s.status === 'processing' && <span className="text-xs text-amber-400 font-medium">In progress</span>}
                  </td>
                  <td className="px-5 py-3">
                    <Link to={`/submissions/${s.submission_id}`} className="text-blue-400 hover:text-blue-300 text-xs font-medium">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-5 py-10 text-center text-slate-500">
                    {search || filter !== 'ALL' ? 'No matches found.' : 'No submissions yet.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
