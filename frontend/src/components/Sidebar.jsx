import { useState, useEffect } from 'react'
import { Atom, GraduationCap, BookOpen } from 'lucide-react'

export default function Sidebar({ activePage, onNavigate }) {
  const [expanded, setExpanded] = useState(false)
  const [dbStatus, setDbStatus] = useState('unknown')
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/ingest/stats')
        setDbStatus(res.ok ? 'connected' : 'offline')
      } catch {
        setDbStatus('offline')
      }
    }
    check()
    const id = setInterval(check, 10000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const checkReviews = async () => {
      try {
        const res = await fetch('/api/sessions/review/count')
        if (res.ok) {
          const data = await res.json()
          setReviewCount(data.count || 0)
        }
      } catch {}
    }
    checkReviews()
    const id = setInterval(checkReviews, 30000)
    return () => clearInterval(id)
  }, [])

  const navItems = [
    { id: 'student', icon: GraduationCap, label: 'Student View' },
    { id: 'teacher', icon: BookOpen, label: 'Teacher Panel', badge: reviewCount },
  ]

  return (
    <div
      className={`flex flex-col bg-sidebar border-r border-border transition-all duration-200 ${expanded ? 'w-56' : 'w-16'} shrink-0`}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-border overflow-hidden">
        <Atom className="w-7 h-7 text-accent shrink-0" />
        {expanded && (
          <span className="text-white font-semibold text-sm whitespace-nowrap">PhysicsTA</span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 flex flex-col gap-1 px-2 py-4">
        {navItems.map(({ id, icon: Icon, label, badge }) => (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors overflow-hidden ${
              activePage === id
                ? 'bg-accent/10 text-accent'
                : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
            }`}
          >
            <span className="relative shrink-0">
              <Icon className="w-5 h-5" />
              {badge > 0 && (
                <span className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-red-500 rounded-full text-white text-[9px] font-bold flex items-center justify-center">
                  {badge > 9 ? '9' : badge}
                </span>
              )}
            </span>
            {expanded && <span className="text-sm font-medium whitespace-nowrap">{label}</span>}
            {expanded && badge > 0 && (
              <span className="ml-auto bg-red-500 text-white text-xs rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1 font-bold">
                {badge > 9 ? '9+' : badge}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* DB status */}
      <div className="px-3 pb-4 flex items-center gap-2 overflow-hidden">
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${
            dbStatus === 'connected' ? 'bg-green-400' : dbStatus === 'offline' ? 'bg-red-400' : 'bg-yellow-400'
          }`}
        />
        {expanded && (
          <span className="text-xs text-muted whitespace-nowrap">
            {dbStatus === 'connected' ? 'DB Connected' : dbStatus === 'offline' ? 'DB Offline' : 'Checking...'}
          </span>
        )}
      </div>
    </div>
  )
}
