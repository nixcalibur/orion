const STYLES = {
  APPROVE:     { color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
  CONDITIONAL: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  DEFER:       { color: '#f97316', bg: 'rgba(249,115,22,0.12)' },
  REJECT:      { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
}

export default function Badge({ level }) {
  const style = STYLES[level] ?? { color: '#94a3b8', bg: 'rgba(148,163,184,0.12)' }
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide"
      style={{ color: style.color, background: style.bg }}
    >
      {level ?? '—'}
    </span>
  )
}
