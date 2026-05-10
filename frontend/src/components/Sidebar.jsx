import { NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, PlusCircle, Shield } from 'lucide-react'

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/submissions', icon: FileText, label: 'Submissions' },
  { to: '/submit', icon: PlusCircle, label: 'New Submission' },
]

export default function Sidebar() {
  return (
    <aside
      className="flex flex-col w-56 flex-shrink-0 border-r"
      style={{ background: '#1a1d2e', borderColor: '#2a2d3e' }}
    >
      <div className="flex items-center gap-2 px-5 py-5 border-b" style={{ borderColor: '#2a2d3e' }}>
        <Shield size={20} className="text-blue-400" />
        <span className="text-white font-bold tracking-widest text-sm">ORION</span>
      </div>

      <nav className="flex flex-col gap-1 p-3 flex-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-blue-600/20 text-blue-400 font-medium'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white',
              ].join(' ')
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t text-xs text-slate-600" style={{ borderColor: '#2a2d3e' }}>
        Operational Risk &amp; Integrity
      </div>
    </aside>
  )
}
