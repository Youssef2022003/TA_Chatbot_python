import { useRef, useState } from 'react'
import { FileText, Upload, Loader2 } from 'lucide-react'
import { LEVELS } from '../config/levels.js'

export default function UploadDropzone({
  onFileSelected,
  selectedFile,
  docType,
  onDocTypeChange,
  level,
  onLevelChange,
  onUpload,
  isUploading,
  result,
  error,
}) {
  const inputRef = useRef(null)
  const [dragActive, setDragActive] = useState(false)

  const handleDragOver = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragActive(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    const file = e.dataTransfer.files?.[0]
    if (file && file.type === 'application/pdf') onFileSelected(file)
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
          dragActive ? 'border-accent bg-accent/5' : 'border-border hover:border-accent'
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) onFileSelected(file)
            e.target.value = ''
          }}
        />
        {selectedFile ? (
          <div className="flex items-center justify-center gap-2 text-slate-300">
            <FileText className="w-5 h-5 text-accent" />
            <span className="text-sm font-medium">{selectedFile.name}</span>
          </div>
        ) : (
          <div className="space-y-2">
            <Upload className="w-8 h-8 text-muted mx-auto" />
            <p className="text-sm text-muted">Drag & drop a PDF, or click to browse</p>
          </div>
        )}
      </div>

      {/* Doc type + Education level */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm text-muted mb-1.5">Document Type</label>
          <select
            value={docType}
            onChange={(e) => onDocTypeChange(e.target.value)}
            className="bg-input border border-border rounded-xl px-4 py-2 w-full text-white text-sm focus:outline-none focus:border-accent"
          >
            <option value="textbook">Textbook</option>
            <option value="exam">Past Exam</option>
            <option value="notes">Lecture Notes</option>
          </select>
        </div>
        <div>
          <label className="block text-sm text-muted mb-1.5">Education Level</label>
          <select
            value={level}
            onChange={(e) => onLevelChange(e.target.value)}
            className="bg-input border border-border rounded-xl px-4 py-2 w-full text-white text-sm focus:outline-none focus:border-accent"
          >
            {LEVELS.map(l => (
              <option key={l.id} value={l.id}>{l.id} · {l.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Upload button */}
      <button
        onClick={onUpload}
        disabled={!selectedFile || isUploading}
        className="w-full bg-accent hover:bg-accent-dark disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl py-3 font-medium transition-colors flex items-center justify-center gap-2"
      >
        {isUploading ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Indexing…
          </>
        ) : (
          <>
            <Upload className="w-4 h-4" />
            Upload & Index
          </>
        )}
      </button>

      {/* Result / error */}
      {result && (
        <div className="flex items-center gap-2 text-green-400 bg-green-400/10 border border-green-400/20 rounded-xl px-4 py-3 text-sm">
          <span className="font-medium">{result.fileName}</span>
          <span className="text-green-400/70">— {result.chunksAdded} chunks indexed</span>
        </div>
      )}
      {error && (
        <div className="text-red-400 bg-red-400/10 border border-red-400/20 rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}
    </div>
  )
}
