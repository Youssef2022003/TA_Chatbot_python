import { useState, useRef, useEffect, useCallback } from 'react'
import { Atom, Camera, SendHorizontal, X, PanelLeftClose, PanelLeft, GraduationCap, Square, CornerUpLeft } from 'lucide-react'
import ChatMessage from '../components/ChatMessage.jsx'
import ImageUpload from '../components/ImageUpload.jsx'
import SessionList from '../components/SessionList.jsx'
import { LEVELS, DEFAULT_LEVEL, normalizeLevel, levelName } from '../config/levels.js'

const LEVEL_STORAGE_KEY = 'physicsta_level'
function loadStoredLevel() {
  try { return normalizeLevel(localStorage.getItem(LEVEL_STORAGE_KEY)) } catch { return DEFAULT_LEVEL }
}

const WELCOME = {
  id: '0',
  role: 'assistant',
  content: "👋 Hi! I'm **PhysicsTA**, your AI physics assistant for this course.\n\nAsk me any physics question, or 📸 upload a photo of a problem you're working on. I'll answer using your course materials and cite every source.",
  sources: [],
  isStreaming: false,
}

export default function StudentChat() {
  const [messages, setMessages] = useState([WELCOME])
  const [input, setInput] = useState('')
  const [attachedImage, setAttachedImage] = useState(null)
  const [isLoading, setIsLoading] = useState(false)

  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [showSessions, setShowSessions] = useState(true)
  const [level, setLevel] = useState(loadStoredLevel)

  const [replyingTo, setReplyingTo] = useState(null)

  const bottomRef = useRef(null)
  const imageUploadRef = useRef(null)
  const textareaRef = useRef(null)
  const abortRef = useRef(null)

  // Load sessions on mount
  useEffect(() => {
    fetch('/api/sessions')
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setSessions(data)
          // Auto-select most recent session
          loadSession(data[0].id, data)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Poll the active session every 10s for teacher replies while not streaming
  useEffect(() => {
    if (!activeSessionId || isLoading) return
    const id = setInterval(async () => {
      try {
        const res = await fetch(`/api/sessions/${activeSessionId}/messages`)
        const msgs = await res.json()
        if (!Array.isArray(msgs) || msgs.length === 0) return
        setMessages(prev => {
          const prevCount = prev.filter(m => m.id !== '0').length
          if (msgs.length > prevCount) {
            return msgs.map(m => ({ ...m, sources: m.sources || [], isStreaming: false }))
          }
          return prev
        })
      } catch {}
    }, 10000)
    return () => clearInterval(id)
  }, [activeSessionId, isLoading])

  // Persist the chosen level locally so it survives reloads
  useEffect(() => {
    try { localStorage.setItem(LEVEL_STORAGE_KEY, String(level)) } catch {}
  }, [level])

  // Change the student level: update state and persist to the active session
  const changeLevel = useCallback((newLevelRaw, sessionId = activeSessionId) => {
    const newLevel = normalizeLevel(newLevelRaw)
    setLevel(newLevel)
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, level: newLevel } : s))
    if (sessionId) {
      fetch(`/api/sessions/${sessionId}/level`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: newLevel }),
      }).catch(() => {})
    }
    return newLevel
  }, [activeSessionId])

  const loadSession = useCallback(async (sessionId, sessionList) => {
    setActiveSessionId(sessionId)
    // Restore the level this session was last used with
    const sess = (sessionList || []).find(s => s.id === sessionId)
    if (sess && sess.level != null) setLevel(normalizeLevel(sess.level))
    try {
      const res = await fetch(`/api/sessions/${sessionId}/messages`)
      const msgs = await res.json()
      if (Array.isArray(msgs) && msgs.length > 0) {
        setMessages(msgs.map(m => ({
          ...m,
          sources: m.sources || [],
          isStreaming: false,
        })))
      } else {
        setMessages([WELCOME])
      }
    } catch {
      setMessages([WELCOME])
    }
  }, [])

  const handleNewChat = async () => {
    if (isLoading) return
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat', level }),
      })
      const session = await res.json()
      setSessions(prev => [session, ...prev])
      setActiveSessionId(session.id)
      setMessages([WELCOME])
      setInput('')
      setAttachedImage(null)
    } catch {}
  }

  const handleSelectSession = (sessionId) => {
    if (sessionId === activeSessionId || isLoading) return
    loadSession(sessionId, sessions)
  }

  const handleDeleteSession = async (sessionId) => {
    try {
      await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (sessionId === activeSessionId) {
        const remaining = sessions.filter(s => s.id !== sessionId)
        if (remaining.length > 0) {
          loadSession(remaining[0].id, remaining)
        } else {
          setActiveSessionId(null)
          setMessages([WELCOME])
        }
      }
    } catch {}
  }

  const handleSend = async () => {
    if ((!input.trim() && !attachedImage) || isLoading) return

    // Slash command: /set_level N  (also /setlevel N, /level N) — set level without calling the LLM
    const cmd = input.trim().match(/^\/(?:set_?level|level)\s+([1-5])\s*$/i)
    if (cmd) {
      const newLevel = changeLevel(parseInt(cmd[1], 10))
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `✅ Education level set to **${levelName(newLevel)}** (Level ${newLevel}). I'll tailor explanations and only use materials for this level.`,
        sources: [],
        isStreaming: false,
      }])
      setInput('')
      return
    }

    // Ensure a session exists before sending
    let currentSessionId = activeSessionId
    if (!currentSessionId) {
      try {
        const res = await fetch('/api/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: 'New Chat', level }),
        })
        const session = await res.json()
        currentSessionId = session.id
        setActiveSessionId(session.id)
        setSessions(prev => [session, ...prev])
      } catch {
        // Continue without a session — messages just won't persist
      }
    }

    const userText = input.trim()
    const img = attachedImage
    const reply = replyingTo

    const userMsg = {
      id: crypto.randomUUID(),
      role: 'user',
      content: userText,
      imagePreview: img?.preview || null,
      quotedText: reply ? reply.content : null,
      quotedRole: reply ? reply.role : null,
    }

    const assistantId = crypto.randomUUID()
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      content: '',
      sources: [],
      isStreaming: true,
      rewrittenQuery: null,
      originalQuery: userText,
      needsReview: false,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    if (img?._revokeUrl) URL.revokeObjectURL(img._revokeUrl)
    setAttachedImage(null)
    setReplyingTo(null)
    setIsLoading(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const history = messages
        .filter(m => m.id !== '0' && !m.isStreaming && m.content && m.content.trim() && m.role !== 'teacher')
        .slice(-6)
        .map(m => ({ role: m.role, content: m.content.trim() }))

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          message: userText,
          imageBase64: img?.base64 || null,
          mimeType: img?.mimeType || null,
          history,
          sessionId: currentSessionId,
          level,
          replyTo: reply ? { role: reply.role, content: reply.content } : null,
        }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') {
            setMessages(prev =>
              prev.map(m => m.id === assistantId ? { ...m, isStreaming: false } : m)
            )
            // Update session title in sidebar after first exchange
            if (currentSessionId) {
              setSessions(prev => prev.map(s =>
                s.id === currentSessionId ? { ...s, updatedAt: Date.now() } : s
              ))
              // Re-fetch sessions to get auto-generated title
              fetch('/api/sessions')
                .then(r => r.json())
                .then(data => { if (Array.isArray(data)) setSessions(data) })
                .catch(() => {})
            }
            setIsLoading(false)
            return
          }
          try {
            const event = JSON.parse(raw)
            setMessages(prev =>
              prev.map(m => {
                if (m.id !== assistantId) return m
                if (event.type === 'meta') {
                  return { ...m, sources: event.sources, rewrittenQuery: event.rewrittenQuery, needsReview: event.needsReview || false }
                }
                if (event.type === 'token') {
                  return { ...m, content: m.content + event.content }
                }
                if (event.type === 'review') {
                  return { ...m, needsReview: event.needsReview, sources: event.sources ?? m.sources }
                }
                if (event.type === 'error') {
                  return { ...m, content: event.message, isStreaming: false }
                }
                return m
              })
            )
          } catch {}
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // Student stopped the stream — keep whatever was already rendered.
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: (m.content || '') + (m.content ? '\n\n_(stopped)_' : '_(stopped)_'), isStreaming: false }
              : m
          )
        )
      } else {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: 'Connection error. Please try again.', isStreaming: false }
              : m
          )
        )
      }
    } finally {
      abortRef.current = null
      setIsLoading(false)
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaInput = (e) => {
    setInput(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  return (
    <div className="flex h-full bg-base overflow-hidden">
      {/* Session list panel */}
      {showSessions && (
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={handleSelectSession}
          onDelete={handleDeleteSession}
          onCreate={handleNewChat}
        />
      )}

      {/* Chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="h-16 flex items-center justify-between px-6 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSessions(o => !o)}
              className="p-1.5 rounded-lg text-muted hover:text-white hover:bg-white/10 transition-colors"
              title={showSessions ? 'Hide chat list' : 'Show chat list'}
            >
              {showSessions ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeft className="w-5 h-5" />}
            </button>
            <div className="flex items-center gap-2">
              <Atom className="w-6 h-6 text-accent" />
              <span className="text-xl font-semibold text-white">PhysicsTA</span>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-400" title="Choose your education level — answers and sources are tailored to it">
            <GraduationCap className="w-4 h-4 text-accent" />
            <span className="hidden sm:inline">Level</span>
            <select
              value={level}
              onChange={(e) => changeLevel(e.target.value)}
              className="bg-input border border-border rounded-lg px-2 py-1.5 text-white text-sm focus:outline-none focus:border-accent"
            >
              {LEVELS.map(l => (
                <option key={l.id} value={l.id}>{l.id} · {l.name}</option>
              ))}
            </select>
          </label>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.map(msg => (
            <ChatMessage
              key={msg.id}
              message={msg}
              onReply={msg.id !== '0' && !msg.isStreaming ? setReplyingTo : undefined}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="shrink-0 bg-card/80 backdrop-blur border-t border-border px-4 py-3">
          {replyingTo && (
            <div className="flex items-center gap-2 mb-2 bg-card border-l-2 border-accent rounded-r-xl px-3 py-2">
              <CornerUpLeft className="w-4 h-4 text-accent shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="text-[11px] text-accent font-medium">
                  Replying to {replyingTo.role === 'user' ? 'your message' : replyingTo.role === 'teacher' ? 'teacher' : 'PhysicsTA'}
                </span>
                <p className="text-xs text-slate-400 truncate">{replyingTo.content || '(image)'}</p>
              </div>
              <button onClick={() => setReplyingTo(null)} className="text-muted hover:text-slate-200 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
          {attachedImage && (
            <div className="flex items-center gap-2 mb-2 bg-card border border-border rounded-xl px-3 py-2">
              <img src={attachedImage.preview} alt="preview" className="w-10 h-10 object-cover rounded" />
              <span className="text-xs text-slate-300 flex-1 truncate">{attachedImage.name}</span>
              <button
                onClick={() => {
                  if (attachedImage?._revokeUrl) URL.revokeObjectURL(attachedImage._revokeUrl)
                  setAttachedImage(null)
                }}
                className="text-muted hover:text-slate-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          <div className="flex items-end gap-2">
            <button
              onClick={() => imageUploadRef.current?.triggerOpen()}
              className="p-2.5 text-muted hover:text-slate-200 hover:bg-white/5 rounded-xl transition-colors shrink-0"
              title="Attach image"
            >
              <Camera className="w-5 h-5" />
            </button>

            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaInput}
              onKeyDown={handleKeyDown}
              placeholder="Ask a physics question…"
              rows={1}
              className="flex-1 bg-input text-white placeholder-muted rounded-xl px-4 py-3 resize-none focus:outline-none focus:ring-1 focus:ring-accent text-sm leading-relaxed"
              style={{ minHeight: '48px', maxHeight: '120px' }}
            />

            {isLoading ? (
              <button
                onClick={handleStop}
                className="p-2.5 bg-red-500/90 hover:bg-red-600 text-white rounded-xl transition-colors shrink-0"
                title="Stop generating"
              >
                <Square className="w-5 h-5" fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim() && !attachedImage}
                className="p-2.5 bg-accent hover:bg-accent-dark disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl transition-colors shrink-0"
              >
                <SendHorizontal className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>

        <ImageUpload ref={imageUploadRef} onImage={setAttachedImage} />
      </div>
    </div>
  )
}
