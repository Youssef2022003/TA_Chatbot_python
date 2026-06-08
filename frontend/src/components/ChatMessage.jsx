import { useState } from 'react'
import { Atom, ChevronDown, ChevronUp, AlertTriangle, GraduationCap, CornerUpLeft } from 'lucide-react'
import katex from 'katex'
import TypingIndicator from './TypingIndicator.jsx'
import SourceCard from './SourceCard.jsx'

// C1 — While streaming, an unterminated "$" makes KaTeX flicker/garble. Hide a
// trailing unclosed math delimiter until its closing "$" arrives.
function clipStreamingMath(text) {
  if (!text) return text
  const dollars = (text.match(/\$/g) || []).length
  if (dollars % 2 === 1) return text.slice(0, text.lastIndexOf('$'))
  return text
}

function KatexInline({ expr }) {
  try {
    const html = katex.renderToString(expr, { throwOnError: false, displayMode: false })
    return <span dangerouslySetInnerHTML={{ __html: html }} />
  } catch {
    return <span>{expr}</span>
  }
}

function KatexDisplay({ expr }) {
  try {
    const html = katex.renderToString(expr, { throwOnError: false, displayMode: true })
    return (
      <div className="my-2 overflow-x-auto text-center"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  } catch {
    return <div className="my-2 font-mono text-sm">{expr}</div>
  }
}

function renderContent(text) {
  if (!text) return null

  const lines = text.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Display math block: $$expr$$ on one line, or $$ ... $$ spanning multiple lines
    if (/^\s*\$\$/.test(line)) {
      if (/^\s*\$\$(.+)\$\$\s*$/.test(line)) {
        // Single-line display math: $$expr$$
        const raw = line.replace(/^\s*\$\$/, '').replace(/\$\$\s*$/, '')
        elements.push(<KatexDisplay key={`dm-${i}`} expr={raw} />)
        i++
      } else {
        // Multi-line: collect lines until closing $$
        const mathLines = [line.replace(/^\s*\$\$\s*/, '')]
        let j = i + 1
        while (j < lines.length && !lines[j].trimEnd().endsWith('$$')) {
          mathLines.push(lines[j])
          j++
        }
        if (j < lines.length) j++ // skip closing $$ line
        elements.push(<KatexDisplay key={`dm-${i}`} expr={mathLines.join('\n').trim()} />)
        i = j
      }
      continue
    }

    // Numbered list item
    if (/^\d+\.\s/.test(line)) {
      const startIdx = i
      const listItems = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\d+\.\s/, ''))
        i++
      }
      elements.push(
        <ol key={`ol-${startIdx}`} className="list-decimal list-inside space-y-1 my-2">
          {listItems.map((item, j) => (
            <li key={j}>{renderInline(item)}</li>
          ))}
        </ol>
      )
      continue
    }

    // Bullet list item
    if (/^[-•]\s/.test(line)) {
      const startIdx = i
      const listItems = []
      while (i < lines.length && /^[-•]\s/.test(lines[i])) {
        listItems.push(lines[i].replace(/^[-•]\s/, ''))
        i++
      }
      elements.push(
        <ul key={`ul-${startIdx}`} className="list-disc list-inside space-y-1 my-2">
          {listItems.map((item, j) => (
            <li key={j}>{renderInline(item)}</li>
          ))}
        </ul>
      )
      continue
    }

    // Key point line
    if (line.startsWith('💡 Key Point:')) {
      elements.push(
        <div
          key={`kp-${i}`}
          className="border-l-4 border-yellow-400 pl-3 bg-yellow-400/5 py-2 rounded-r mt-3"
        >
          {renderInline(line)}
        </div>
      )
      i++
      continue
    }

    // Empty line
    if (line.trim() === '') {
      elements.push(<div key={`br-${i}`} className="h-2" />)
      i++
      continue
    }

    // Regular paragraph (may contain inline math)
    elements.push(
      <p key={`p-${i}`} className="leading-relaxed">
        {renderInline(line)}
      </p>
    )
    i++
  }

  return elements
}

function renderInline(text) {
  // Split on **bold**, `code`, [Source N], $$display$$, $inline$
  // Order matters: $$ must be matched before $ to avoid partial matches
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[Source \d+\]|\$\$[^$]+\$\$|\$[^$\n]+\$)/g)
  return parts.map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>
    }
    if (/^`[^`]+`$/.test(part)) {
      return (
        <code key={i} className="bg-base px-1.5 py-0.5 rounded text-sm font-mono text-accent">
          {part.slice(1, -1)}
        </code>
      )
    }
    if (/^\[Source \d+\]$/.test(part)) {
      return (
        <span key={i} className="text-xs text-accent/70 font-mono">
          {part}
        </span>
      )
    }
    // Display math inside inline context (e.g., model put $$ inside a sentence)
    if (/^\$\$[^$]+\$\$$/.test(part)) {
      return <KatexDisplay key={i} expr={part.slice(2, -2)} />
    }
    // Inline math $...$
    if (/^\$[^$\n]+\$$/.test(part)) {
      return <KatexInline key={i} expr={part.slice(1, -1)} />
    }
    return part
  })
}

function ReplyButton({ onReply, payload, className = '' }) {
  if (!onReply) return null
  return (
    <button
      onClick={() => onReply(payload)}
      className={`flex items-center gap-1 text-xs text-muted hover:text-accent transition-colors ${className}`}
      title="Reply to this message"
    >
      <CornerUpLeft className="w-3 h-3" /> Reply
    </button>
  )
}

// A compact quote of the message being replied to, shown inside the user bubble.
function QuotedPreview({ text, role, light }) {
  if (!text && role == null) return null
  const who = role === 'user' ? 'You' : role === 'teacher' ? 'Teacher' : 'PhysicsTA'
  return (
    <div className={`mb-2 border-l-2 pl-2 py-1 rounded-r text-xs ${light ? 'border-white/40 bg-white/10' : 'border-accent bg-base/40'}`}>
      <span className={`block font-medium ${light ? 'text-white/80' : 'text-accent'}`}>↪ {who}</span>
      <span className={`line-clamp-2 ${light ? 'text-white/70' : 'text-slate-400'}`}>{text || '(image)'}</span>
    </div>
  )
}

export default function ChatMessage({ message, onReply }) {
  const { role, content, sources = [], rewrittenQuery, isStreaming, imagePreview, originalQuery, needsReview, quotedText, quotedRole } = message
  const [sourcesOpen, setSourcesOpen] = useState(false)

  const replyPayload = { id: message.id, role, content: content || (imagePreview ? '(image)' : '') }

  if (role === 'teacher') {
    return (
      <div className="flex gap-3 mb-4 max-w-[80%] group">
        <div className="w-7 h-7 bg-green-500/20 rounded-full flex items-center justify-center shrink-0 mt-1">
          <GraduationCap className="w-4 h-4 text-green-400" />
        </div>
        <div className="flex-1 bg-card border border-green-500/20 rounded-2xl rounded-tl-sm px-4 py-3">
          <p className="text-xs text-green-400 font-semibold mb-1.5">Teacher</p>
          <div className="text-sm text-slate-200 space-y-1">{renderContent(content)}</div>
          <div className="mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <ReplyButton onReply={onReply} payload={replyPayload} />
          </div>
        </div>
      </div>
    )
  }

  if (role === 'user') {
    return (
      <div className="flex flex-col items-end mb-4 group">
        <div className="max-w-[75%] bg-gradient-to-br from-accent to-accent-dark text-white rounded-2xl rounded-tr-sm px-4 py-3">
          {(quotedText || quotedRole) && <QuotedPreview text={quotedText} role={quotedRole} light />}
          {imagePreview && (
            <img
              src={imagePreview}
              alt="uploaded"
              className="rounded-lg max-h-40 object-cover mb-2 w-full"
            />
          )}
          {content && <p className="text-sm leading-relaxed">{content}</p>}
        </div>
        <div className="mt-1 mr-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <ReplyButton onReply={onReply} payload={replyPayload} />
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="flex gap-3 mb-4 max-w-[80%] group">
      <div className="w-7 h-7 bg-accent/20 rounded-full flex items-center justify-center shrink-0 mt-1">
        <Atom className="w-4 h-4 text-accent" />
      </div>
      <div className="flex-1 bg-card border border-border/50 rounded-2xl rounded-tl-sm px-4 py-3">
        {/* Content */}
        {isStreaming && !content ? (
          <TypingIndicator />
        ) : (
          <div className="text-sm text-slate-200 space-y-1">
            {renderContent(isStreaming ? clipStreamingMath(content) : content)}
            {isStreaming && content && (
              <span className="cursor-blink inline-block w-0.5 h-4 bg-slate-300 ml-0.5 align-middle" />
            )}
          </div>
        )}

        {/* Rewritten query pill */}
        {rewrittenQuery && originalQuery && rewrittenQuery !== originalQuery && (
          <p className="mt-2 text-xs text-muted italic">
            🔍 Searched for: "{rewrittenQuery}"
          </p>
        )}

        {/* Teacher review notice */}
        {needsReview && !isStreaming && (
          <div className="mt-3 flex items-start gap-2 bg-yellow-400/5 border border-yellow-400/20 rounded-xl px-3 py-2.5">
            <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
            <p className="text-xs text-yellow-300/80 leading-relaxed">
              This topic wasn't found in the course materials. Your teacher has been notified and will follow up.
            </p>
          </div>
        )}

        {/* Sources toggle */}
        {sources.length > 0 && (
          <div className="mt-3">
            <button
              onClick={() => setSourcesOpen(o => !o)}
              className="flex items-center gap-1.5 text-xs text-muted hover:text-slate-300 transition-colors"
            >
              {sourcesOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              📚 Sources ({sources.length})
            </button>
            {sourcesOpen && (
              <div className="mt-2 grid gap-1.5">
                {sources.map((s, i) => (
                  <SourceCard key={i} {...s} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Reply action */}
        {!isStreaming && content && (
          <div className="mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <ReplyButton onReply={onReply} payload={replyPayload} />
          </div>
        )}
      </div>
    </div>
  )
}
