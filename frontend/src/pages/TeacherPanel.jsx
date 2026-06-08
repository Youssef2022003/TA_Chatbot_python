import { useState, useEffect } from 'react'
import {
  BookOpen, Database, Upload, Trash2, FileText,
  AlertTriangle, CheckCircle, ChevronDown, ChevronUp, Eye, Send
} from 'lucide-react'
import UploadDropzone from '../components/UploadDropzone.jsx'
import { LEVELS, DEFAULT_LEVEL, levelShort } from '../config/levels.js'

const BADGE_STYLES = {
  textbook: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  exam:     'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  notes:    'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30',
}
const DOC_LABELS = { textbook: 'Textbook', exam: 'Past Exam', notes: 'Lecture Notes' }

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

// ─── Mini chat thread for review queue ────────────────────────────────────────
function ReviewThread({ messages }) {
  if (!messages?.length) return <p className="text-xs text-muted">No messages recorded.</p>
  return (
    <div className="space-y-2 mt-2 max-h-64 overflow-y-auto pr-1">
      {messages.map((m, i) => (
        <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs ${
            m.role === 'user'
              ? 'bg-accent/20 text-slate-200'
              : m.role === 'teacher'
              ? 'bg-green-500/10 border border-green-500/20 text-green-200'
              : 'bg-card border border-border text-slate-300'
          }`}>
            {m.role === 'teacher' && (
              <span className="block font-semibold text-green-400 mb-0.5">Teacher</span>
            )}
            {m.hasImage && <span className="text-muted italic">[Image attached] </span>}
            <span className="leading-relaxed whitespace-pre-wrap">{m.content || '(image only)'}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Knowledge Base tab ────────────────────────────────────────────────────────
function KnowledgeBaseTab() {
  const [stats, setStats] = useState(null)
  const [uploadFile, setUploadFile] = useState(null)
  const [docType, setDocType] = useState('textbook')
  const [level, setLevel] = useState(DEFAULT_LEVEL)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [error, setError] = useState(null)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [deletingDoc, setDeletingDoc] = useState(null)

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/ingest/stats')
      if (res.ok) setStats(await res.json())
    } catch {}
  }

  useEffect(() => { fetchStats() }, [])

  const handleUpload = async () => {
    if (!uploadFile || isUploading) return
    setIsUploading(true)
    setUploadResult(null)
    setError(null)
    const form = new FormData()
    form.append('document', uploadFile)
    form.append('docType', docType)
    form.append('level', String(level))
    try {
      const res = await fetch('/api/ingest', { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Upload failed')
      setUploadResult(data)
      setUploadFile(null)
      fetchStats()
    } catch (err) {
      setError(err.message)
    } finally {
      setIsUploading(false)
    }
  }

  const handleDeleteDoc = async (fileName) => {
    setDeletingDoc(fileName)
    try {
      const res = await fetch(`/api/ingest/document/${encodeURIComponent(fileName)}`, { method: 'DELETE' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to delete')
      }
      fetchStats()
    } catch (err) {
      setError(err.message)
    } finally {
      setDeletingDoc(null)
    }
  }

  const handleClear = async () => {
    try {
      const res = await fetch('/api/ingest/clear', { method: 'DELETE' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to clear knowledge base')
      }
      setStats(null)
      setUploadResult(null)
      setShowClearConfirm(false)
      fetchStats()
    } catch (err) {
      setError(err.message)
      setShowClearConfirm(false)
    }
  }

  const documents = stats?.documents || []

  // Per-level coverage: how many documents target each education level
  const levelCounts = LEVELS.reduce((acc, l) => ({ ...acc, [l.id]: 0 }), {})
  let legacyCount = 0
  for (const d of documents) {
    if (d.level == null) legacyCount++
    else if (levelCounts[d.level] != null) levelCounts[d.level]++
  }

  return (
    <div className="space-y-6">
      {/* Upload */}
      <div className="bg-card rounded-2xl border border-border p-6">
        <div className="flex items-center gap-2 mb-4">
          <Upload className="w-5 h-5 text-accent" />
          <h2 className="text-base font-semibold text-white">Upload Course Material</h2>
        </div>
        <UploadDropzone
          onFileSelected={(f) => { setUploadFile(f); setUploadResult(null); setError(null) }}
          selectedFile={uploadFile}
          docType={docType}
          onDocTypeChange={setDocType}
          level={level}
          onLevelChange={setLevel}
          onUpload={handleUpload}
          isUploading={isUploading}
          result={uploadResult}
          error={error}
        />
      </div>

      {/* Document list */}
      <div className="bg-card rounded-2xl border border-border p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-accent" />
            <h2 className="text-base font-semibold text-white">Knowledge Base</h2>
          </div>
          {stats && (
            <span className="text-xs text-muted">{stats.totalChunks} chunks total</span>
          )}
        </div>

        {/* Per-level coverage */}
        {stats && (
          <div className="mb-4">
            <p className="text-xs text-muted mb-2">Coverage by level</p>
            <div className="grid grid-cols-5 gap-2">
              {LEVELS.map(l => {
                const n = levelCounts[l.id]
                return (
                  <div
                    key={l.id}
                    title={`${l.name}: ${n} document${n === 1 ? '' : 's'}`}
                    className={`rounded-lg px-2 py-1.5 text-center border ${
                      n === 0
                        ? 'border-red-500/30 bg-red-500/5'
                        : 'border-green-500/30 bg-green-500/5'
                    }`}
                  >
                    <div className="text-[10px] text-muted truncate">L{l.id} · {l.short}</div>
                    <div className={`text-sm font-semibold ${n === 0 ? 'text-red-400' : 'text-green-400'}`}>{n}</div>
                  </div>
                )
              })}
            </div>
            {legacyCount > 0 && (
              <p className="text-[11px] text-yellow-400/80 mt-2">
                {legacyCount} document{legacyCount === 1 ? '' : 's'} have no level (shown to all levels) — re-upload to tag them.
              </p>
            )}
          </div>
        )}

        {!stats ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : documents.length === 0 ? (
          <p className="text-sm text-muted mb-4">No materials uploaded yet.</p>
        ) : (
          <div className="space-y-2 mb-4">
            {documents.map((doc, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2.5 bg-base rounded-lg border border-border">
                <FileText className="w-4 h-4 text-muted shrink-0" />
                <span className="text-sm text-slate-300 flex-1 truncate" title={doc.name}>{doc.name}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${BADGE_STYLES[doc.docType] || BADGE_STYLES.notes}`}>
                  {DOC_LABELS[doc.docType] || doc.docType}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  {doc.level != null ? levelShort(doc.level) : 'Any level'}
                </span>
                <span className="text-xs text-muted whitespace-nowrap">{doc.chunks} chunks</span>
                <button
                  onClick={() => handleDeleteDoc(doc.name)}
                  disabled={deletingDoc === doc.name}
                  className="p-1.5 text-muted hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors disabled:opacity-40"
                  title="Remove from knowledge base"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {!showClearConfirm ? (
          <button
            onClick={() => setShowClearConfirm(true)}
            className="text-sm text-red-400 border border-red-400/30 hover:bg-red-400/10 rounded-xl px-4 py-2 transition-colors"
          >
            Clear Entire Knowledge Base
          </button>
        ) : (
          <div className="flex items-center gap-3 bg-red-400/5 border border-red-400/20 rounded-xl px-4 py-3">
            <span className="text-sm text-red-300 flex-1">Are you sure? This deletes everything.</span>
            <button onClick={handleClear} className="text-sm bg-red-500 hover:bg-red-600 text-white rounded-lg px-3 py-1.5 transition-colors">
              Confirm
            </button>
            <button onClick={() => setShowClearConfirm(false)} className="text-sm text-muted hover:text-slate-300 transition-colors">
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Review Queue tab ──────────────────────────────────────────────────────────
function ReviewQueueTab() {
  const [queue, setQueue] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState({})
  const [marking, setMarking] = useState(null)
  const [replyText, setReplyText] = useState({})
  const [sending, setSending] = useState(null)

  const fetchQueue = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/sessions/review')
      const data = await res.json()
      setQueue(Array.isArray(data) ? data : [])
    } catch {
      setQueue([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchQueue()
    const id = setInterval(fetchQueue, 30000)
    return () => clearInterval(id)
  }, [])

  const handleMarkReviewed = async (sessionId) => {
    setMarking(sessionId)
    try {
      await fetch(`/api/sessions/${sessionId}/review`, { method: 'PATCH' })
      setQueue(prev => prev.filter(s => s.id !== sessionId))
    } catch {}
    finally {
      setMarking(null)
    }
  }

  const toggleExpand = (id) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const handleReply = async (sessionId) => {
    const text = (replyText[sessionId] || '').trim()
    if (!text || sending === sessionId) return
    setSending(sessionId)
    try {
      const res = await fetch(`/api/sessions/${sessionId}/teacher-reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      })
      if (res.ok) {
        setReplyText(prev => ({ ...prev, [sessionId]: '' }))
        setQueue(prev => prev.filter(s => s.id !== sessionId))
      }
    } catch {}
    finally { setSending(null) }
  }

  // Find the first unanswered question in the session
  const getUnansweredQuestion = (session) => {
    const msgs = session.messages || []
    for (let i = 0; i < msgs.length; i++) {
      if (msgs[i].role === 'assistant' && msgs[i].needsReview) {
        // Return the preceding user message
        const userMsg = msgs[i - 1]
        return userMsg?.content || (userMsg?.hasImage ? '[Image question]' : null)
      }
    }
    return null
  }

  if (loading) {
    return <p className="text-sm text-muted">Loading review queue…</p>
  }

  if (queue.length === 0) {
    return (
      <div className="bg-card rounded-2xl border border-border p-8 text-center">
        <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-3" />
        <p className="text-white font-medium">All clear!</p>
        <p className="text-sm text-muted mt-1">No student questions need your attention right now.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {queue.length} session{queue.length > 1 ? 's' : ''} need your review — these questions weren't fully covered by the course materials.
      </p>

      {queue.map(session => {
        const unanswered = getUnansweredQuestion(session)
        const isExpanded = expanded[session.id]

        return (
          <div key={session.id} className="bg-card rounded-2xl border border-red-400/20 p-5">
            {/* Session header */}
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">{session.title}</p>
                <p className="text-xs text-muted mt-0.5">{timeAgo(session.updatedAt)}</p>
                {unanswered && (
                  <p className="text-xs text-yellow-300/80 mt-1.5 italic">
                    Unanswered: "{unanswered.length > 100 ? unanswered.slice(0, 100) + '…' : unanswered}"
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => toggleExpand(session.id)}
                  className="flex items-center gap-1 text-xs text-muted hover:text-slate-300 transition-colors"
                >
                  <Eye className="w-3.5 h-3.5" />
                  {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                <button
                  onClick={() => handleMarkReviewed(session.id)}
                  disabled={marking === session.id}
                  className="flex items-center gap-1.5 text-xs bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/20 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-40"
                >
                  <CheckCircle className="w-3.5 h-3.5" />
                  Mark reviewed
                </button>
              </div>
            </div>

            {/* Expandable chat thread + reply */}
            {isExpanded && (
              <div className="mt-4 border-t border-border pt-4 space-y-3">
                <ReviewThread messages={session.messages} />
                <div className="flex gap-2 pt-1">
                  <textarea
                    value={replyText[session.id] || ''}
                    onChange={e => setReplyText(prev => ({ ...prev, [session.id]: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleReply(session.id) } }}
                    placeholder="Type your answer to the student… (Enter to send)"
                    rows={2}
                    className="flex-1 bg-base border border-border rounded-xl px-3 py-2 text-sm text-white placeholder-muted resize-none focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  <button
                    onClick={() => handleReply(session.id)}
                    disabled={!replyText[session.id]?.trim() || sending === session.id}
                    className="p-2.5 bg-accent hover:bg-accent-dark disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl transition-colors self-end shrink-0"
                    title="Send reply"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Main Teacher Panel ────────────────────────────────────────────────────────
export default function TeacherPanel() {
  const [activeTab, setActiveTab] = useState('kb')
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/sessions/review/count')
        const data = await res.json()
        setReviewCount(data.count || 0)
      } catch {}
    }
    check()
    const id = setInterval(check, 30000)
    return () => clearInterval(id)
  }, [])

  const tabs = [
    { id: 'kb', label: 'Knowledge Base', icon: Database },
    { id: 'review', label: 'Review Queue', icon: AlertTriangle, badge: reviewCount },
  ]

  return (
    <div className="bg-base overflow-y-auto h-full p-8">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-2">
          <BookOpen className="w-7 h-7 text-accent" />
          <div>
            <h1 className="text-2xl font-semibold text-white">Teacher Dashboard</h1>
            <p className="text-sm text-muted">Manage course materials and review student questions</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-card rounded-xl p-1 border border-border">
          {tabs.map(({ id, label, icon: Icon, badge }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === id
                  ? 'bg-accent/10 text-accent border border-accent/20'
                  : 'text-muted hover:text-slate-300 hover:bg-white/5'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
              {badge > 0 && (
                <span className="bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center font-bold">
                  {badge > 9 ? '9+' : badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'kb' ? <KnowledgeBaseTab /> : <ReviewQueueTab />}
      </div>
    </div>
  )
}
