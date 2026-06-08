// Frontend mirror of backend/config/levels.js (labels only — the backend is the
// source of truth for retrieval/prompt behavior). Keep the ids in sync.

export const LEVELS = [
  { id: 1, name: 'Primary / Elementary', short: 'Primary' },
  { id: 2, name: 'Middle School', short: 'Middle' },
  { id: 3, name: 'High School', short: 'High School' },
  { id: 4, name: 'Undergraduate', short: 'Undergrad' },
  { id: 5, name: 'Postgraduate / Advanced', short: 'Postgrad' },
]

export const DEFAULT_LEVEL = 3

export function normalizeLevel(value) {
  const n = parseInt(value, 10)
  if (Number.isInteger(n) && n >= 1 && n <= 5) return n
  return DEFAULT_LEVEL
}

export function levelName(id) {
  const lvl = LEVELS.find(l => l.id === normalizeLevel(id))
  return lvl ? lvl.name : 'High School'
}

export function levelShort(id) {
  const lvl = LEVELS.find(l => l.id === normalizeLevel(id))
  return lvl ? lvl.short : 'High School'
}
