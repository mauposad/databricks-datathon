// Type-ahead over the broad care groups (backend /api/service-groups), in the browser: no request per keystroke.
// Mirrors backend/terms.py: a group matches on its label and description, its services' labels and aliases, and its
// everyday terms ("chest pain" -> Heart care / cath lab). A term that names one service preselects that service.

const norm = (s) => (s || '').toLowerCase().replace(/[’]/g, "'").replace(/\s+/g, ' ').trim()

export function buildVocab(groups, services) {
  const byKey = Object.fromEntries(services.map((s) => [s.key, s]))
  const out = []
  for (const g of groups) {
    out.push({ term: norm(g.label), group: g, service: null, kind: 'group' })
    for (const k of g.services) {
      const s = byKey[k]
      if (!s) continue
      out.push({ term: norm(s.label), group: g, service: k, kind: 'service' })
      for (const a of s.aliases || []) out.push({ term: norm(a), group: g, service: k, kind: 'alias' })
    }
    for (const t of g.terms || []) out.push({ term: norm(t.term), group: g, service: t.service || null, kind: 'term' })
  }
  return out
}

// How well `term` fits what the user typed: 4 exact, 3 prefix, 2 word prefix, 1 the typed text contains the term
// as whole words ("my child has a fever" contains "fever"), 0 no match.
function fit(term, q) {
  if (term === q) return 4
  if (term.startsWith(q)) return 3
  if (q.length >= 3 && (` ${term}`).includes(` ${q}`)) return 2
  if (term.length >= 3 && new RegExp(`(^|[^\\w-])${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\w-])`).test(q)) return 1
  return 0
}

// Ranked suggestions: [{ group, service, via }] where `via` is the everyday word that matched (shown as a hint).
export function suggest(query, groups, vocab, limit = 8) {
  const q = norm(query)
  if (!q) return groups.map((g) => ({ group: g, service: null, via: null }))
  const best = new Map()
  for (const v of vocab) {
    const f = fit(v.term, q)
    if (!f) continue
    // longer whole-word hits inside a sentence are more specific ("heart attack" over "heart")
    const score = f * 1000 + (f === 1 ? v.term.length : -v.term.length) + (v.service ? 1 : 0)
    const id = `${v.group.key}|${v.service || ''}`
    if (!best.has(id) || best.get(id).score < score) best.set(id, { ...v, score })
  }
  const rows = [...best.values()].sort((a, b) => b.score - a.score)
  // one row per group: its best match (a specific service if that matched best)
  const seen = new Set()
  const out = []
  for (const r of rows) {
    if (seen.has(r.group.key)) continue
    seen.add(r.group.key)
    const label = norm(r.group.label)
    out.push({ group: r.group, service: r.service, via: r.kind === 'group' || r.term === label ? null : r.term })
    if (out.length >= limit) break
  }
  return out
}
