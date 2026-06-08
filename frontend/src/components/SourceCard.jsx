import { useState } from 'react'
import { BookOpen, ChevronDown, ChevronUp } from 'lucide-react'

const BADGE_STYLES = {
  textbook: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
  exam:     'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  notes:    'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30',
}

const DOC_LABELS = {
  textbook: 'Textbook',
  exam:     'Past Exam',
  notes:    'Lecture Notes',
}

export default function SourceCard({ fileName, docType, chunkIndex, pageStart, pageEnd, chapter, text }) {
  const [expanded, setExpanded] = useState(false)
  const badge = BADGE_STYLES[docType] || BADGE_STYLES.notes
  const label = DOC_LABELS[docType] || docType

  const pageLabel = pageStart != null
    ? (pageStart === pageEnd || pageEnd == null ? `Page ${pageStart}` : `Pages ${pageStart}–${pageEnd}`)
    : null

  return (
    <div className="flex flex-col gap-1.5 px-3 py-2.5 bg-base rounded-lg border border-border hover:border-accent/50 transition-colors">
      {/* Row 1: location info (most useful to student) + badge */}
      <div className="flex items-center gap-2">
        <BookOpen className="w-4 h-4 text-accent/60 shrink-0" />
        <div className="flex-1 min-w-0">
          {chapter ? (
            <span className="text-xs text-slate-200 font-medium truncate block" title={chapter}>
              {chapter}
            </span>
          ) : (
            <span className="text-xs text-muted truncate block" title={fileName}>{fileName}</span>
          )}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap shrink-0 ${badge}`}>
          {label}
        </span>
      </div>

      {/* Row 2: page + filename (secondary info) + view excerpt toggle */}
      <div className="flex items-center gap-2 pl-6">
        {pageLabel && (
          <span className="text-xs text-accent font-medium whitespace-nowrap">
            {pageLabel}
          </span>
        )}
        {pageLabel && chapter && (
          <span className="text-muted text-xs">·</span>
        )}
        {chapter && (
          <span className="text-xs text-muted truncate" title={fileName}>{fileName}</span>
        )}
        {!pageLabel && !chapter && (
          <span className="text-xs text-muted">chunk #{chunkIndex}</span>
        )}
        {text && (
          <button
            onClick={() => setExpanded(o => !o)}
            className="ml-auto flex items-center gap-0.5 text-xs text-accent/70 hover:text-accent transition-colors whitespace-nowrap shrink-0"
          >
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {expanded ? 'Hide' : 'View excerpt'}
          </button>
        )}
      </div>

      {/* Expanded chunk text */}
      {expanded && text && (
        <div className="mt-1 pl-6 pr-1">
          <div className="bg-card border border-border rounded-md px-3 py-2 max-h-40 overflow-y-auto">
            <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{text}</p>
          </div>
        </div>
      )}
    </div>
  )
}
