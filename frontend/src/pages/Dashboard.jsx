import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import { FileCheck2, AlertTriangle, Clock, XCircle } from 'lucide-react'
import api from '../api/client.js'
import Badge from '../components/Badge.jsx'

const LEVEL_COLORS = {
  APPROVE: '#22c55e',
  CONDITIONAL: '#f59e0b',
  DEFER: '#f97316',
  REJECT: '#ef4444',
  unknown: '#475569',
}

function StatCard({ icon: Icon, label, value, iconColor }) {
  return (
    <div
      className="rounded-xl p-5 flex items-center gap-4"
      style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}
    >
      <div className="rounded-lg p-2.5" style={{ background: 'rgba(255,255,255,0.05)' }}>
        <Icon size={20} style={{ color: iconColor }} />
      </div>
      <div>
        <p className="text-xs text-slate-400 mb-0.5">{label}</p>
        <p className="text-2xl font-bold text-white">{value ?? '—'}</p>
      </div>
    </div>
  )
}

function fmt(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.get('/stats'), api.get('/submissions')])
      .then(([s, sub]) => {
        setStats(s.data)
        setSubmissions(sub.data.slice(0, 8))
      })
      .finally(() => setLoading(false))
  }, [])

  const pieData = stats
    ? Object.entries(stats.by_level)
        .filter(([k]) => k !== 'unknown')
        .map(([name, { count }]) => ({ name, value: count }))
    : []

  const barData = stats?.recent_7d ?? []

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-slate-500">Loading…</div>
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-white">Dashboard</h1>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon={FileCheck2} label="Total Submissions" value={stats?.total} iconColor="#60a5fa" />
        <StatCard icon={AlertTriangle} label="Avg Risk Score" value={stats?.avg_score?.toFixed(2)} iconColor="#f59e0b" />
        <StatCard icon={Clock} label="Pending Review" value={stats?.pending_review} iconColor="#f97316" />
        <StatCard icon={XCircle} label="Rejection Rate" value={stats ? `${stats.rejection_rate}%` : '—'} iconColor="#ef4444" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
          <h2 className="text-sm font-medium text-slate-300 mb-4">Authorization Breakdown</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} innerRadius="52%" outerRadius="72%" paddingAngle={3} dataKey="value">
                {pieData.map((entry) => (
                  <Cell key={entry.name} fill={LEVEL_COLORS[entry.name] ?? '#475569'} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: '#1a1d2e', border: '1px solid #2a2d3e', borderRadius: 8 }}
                itemStyle={{ color: '#e2e8f0' }}
              />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
          <h2 className="text-sm font-medium text-slate-300 mb-4">Submissions — Last 7 Days</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={barData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3e" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: '#1a1d2e', border: '1px solid #2a2d3e', borderRadius: 8 }}
                labelStyle={{ color: '#94a3b8', fontSize: 12 }}
                itemStyle={{ color: '#e2e8f0' }}
              />
              <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
        <div className="px-5 py-4 border-b" style={{ borderColor: '#2a2d3e' }}>
          <h2 className="text-sm font-medium text-slate-300">Recent Submissions</h2>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 uppercase tracking-wide" style={{ borderBottom: '1px solid #2a2d3e' }}>
              <th className="px-5 py-3 text-left font-medium">Applicant</th>
              <th className="px-5 py-3 text-left font-medium">Jurisdiction</th>
              <th className="px-5 py-3 text-left font-medium">Score</th>
              <th className="px-5 py-3 text-left font-medium">Level</th>
              <th className="px-5 py-3 text-left font-medium">Date</th>
              <th className="px-5 py-3 text-left font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {submissions.map((s, i) => (
              <tr
                key={s.submission_id}
                style={{ borderTop: i > 0 ? '1px solid #2a2d3e' : undefined }}
                className="hover:bg-white/[0.02]"
              >
                <td className="px-5 py-3 text-white font-medium">{s.applicant_name ?? s.submission_id}</td>
                <td className="px-5 py-3 text-slate-400">{s.jurisdiction ?? '—'}</td>
                <td className="px-5 py-3 text-slate-300">
                  {s.composite_score != null ? s.composite_score.toFixed(2) : '—'}
                </td>
                <td className="px-5 py-3"><Badge level={s.authorization_level} /></td>
                <td className="px-5 py-3 text-slate-400">{fmt(s.assessed_at)}</td>
                <td className="px-5 py-3">
                  <Link to={`/submissions/${s.submission_id}`} className="text-blue-400 hover:text-blue-300 text-xs font-medium">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
            {submissions.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-slate-500">No submissions yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
