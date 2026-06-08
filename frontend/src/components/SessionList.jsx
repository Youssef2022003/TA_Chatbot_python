import { MessageSquarePlus, Trash2, MessageSquare } from 'lucide-react'

function timeAgo(ts) {
  const diff = Date.now() - ts
  const m = Math.floor(diff / 60000)
  const h = Math.floor(diff / 3600000)
  const d = Math.floor(diff / 86400000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  if (h < 24) return `${h}h ago`
  if (d < 7) return `${d}d ago`
  return new Date(ts).toLocaleDateString()
}

export default function SessionList({ sessions, activeSessionId, onSelect, onDelete, onCreate }) {
  return (
    <div className="flex flex-col h-full bg-sidebar border-r border-border w-64 shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-16 border-b border-border shrink-0">
        <span className="text-sm font-semibold text-white">Chats</span>
        <button
          onClick={onCreate}
          title="New chat"
          className="p-1.5 rounded-lg text-muted hover:text-white hover:bg-white/10 transition-colors"
        >
          <MessageSquarePlus className="w-4 h-4" />
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {sessions.length === 0 && (
          <p className="text-xs text-muted text-center mt-8 px-4">
            No chats yet. Ask a question to get started.
          </p>
        )}
        {sessions.map(s => (
          <div
            key={s.id}
            className={`group flex items-start gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
              s.id === activeSessionId
                ? 'bg-accent/10 border border-accent/20'
                : 'hover:bg-white/5 border border-transparent'
            }`}
            onClick={() => onSelect(s.id)}
          >
            <MessageSquare className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${s.id === activeSessionId ? 'text-accent' : 'text-muted'}`} />
            <div className="flex-1 min-w-0">
              <p className={`text-xs font-medium truncate leading-tight ${s.id === activeSessionId ? 'text-white' : 'text-slate-300'}`}>
                {s.title}
              </p>
              <p className="text-xs text-muted mt-0.5">{timeAgo(s.updatedAt)}</p>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(s.id) }}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-muted hover:text-red-400 transition-all shrink-0"
              title="Delete chat"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
