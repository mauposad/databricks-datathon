// Plain-language labels and the card logic, moved unchanged from the old ResultCard.jsx.
import * as api from '../../api.js'
import { toast } from '../ui/index.js'

export const BADGE = {
  High: { tone: 'success', text: 'High confidence' },
  Medium: { tone: 'warning', text: 'Medium confidence' },
  Low: { tone: 'danger', text: 'Low confidence' },
  Probable: { tone: 'warning', text: 'Likely · call to confirm' },
  Unconfirmed: { tone: 'neutral', text: 'Unconfirmed' },
}

// Tags that are worth a "heads up" on the front of the card, in priority order, with plain wording.
// Several record-identity tags collapse into one message.
export const HEADS_UP = [
  { tags: ['Reported not available'], text: 'A reviewer reported this service is not available here.', level: 'bad' },
  { tags: ['Identity not settled', 'Possible duplicate record', 'Possible merged record'], text: 'This record may be duplicated or mixed up with another facility.' },
  { tags: ['Not a hospital'], text: 'Not a hospital. It may be a clinic or a smaller centre.' },
  { tags: ['Location uncertain'], text: 'Map location is approximate.' },
  { tags: ['Farther option'], text: 'Farther than the usual travel time for this service.' },
]
// Minor data-quality tags: shown only in the details.
export const MINOR = { 'Single source': 'Only one website or listing mentions this facility.', 'Has referral mentions': 'Some mentions only refer patients elsewhere; those were not counted.' }

export const telHref = (phone) => `tel:${phone.replace(/[^+\d]/g, '')}`
export const hostOf = (url) => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url } }
export const withScheme = (url) => (url.startsWith('http') ? url : `https://${url}`)
export const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
export const fmtMin = (m) => (m < 1 ? 'Under 1 min' : `~${m} min`)
export const fmtKm = (km) => (km < 1 ? 'under 1 km' : `${km} km`)
export const tagNumber = (tags, word) => tags.map((t) => t.match(new RegExp(`^(\\d+) ${word}`))).find(Boolean)?.[1]
export const directionsHref = (rec) => `https://www.google.com/maps/dir/?api=1&destination=${rec.lat},${rec.lon}`

// Record a reviewer decision (with an optional note) in the verifications overlay, then re-run the search.
// The note is asked for in a popover next to the button (VerifyAction.jsx), not in a blocking prompt.
export async function saveVerification({ facilityId, serviceKey, checkKey, status, label, note, onVerified }) {
  await api.verify({ facility_id: facilityId, service_key: serviceKey, check_key: checkKey, status, note: note || null })
  toast.success(`Saved: ${status === 'confirmed' ? 'confirmed' : 'rejected'} "${label}"`, { description: 'Everyone sees this the next time the search runs.' })
  onVerified?.(facilityId)
}

// Explain why this facility ranks below #1, in one or two sentences.
export function rankReason(rec, top) {
  if (!top || rec.id === top.id) return null
  if (rec.score.mode === 'quality_first') {
    const dq = rec.score.match - top.score.match
    if (rec.ranking_band === 'unconfirmed') return 'Its evidence is weak, and weak evidence always comes after confirmed or probable options.'
    if (rec.ranking_band === 'farther option' && top.ranking_band === 'reachable')
      return `It is about ${rec.travel_min} min away, beyond the ${rec.travel_budget_min}-minute travel limit for this service, so it comes after every option within reach.`
    const confGroup = (l) => (l === 'High' ? 1 : l === 'Medium' ? 2 : 3)
    if (confGroup(rec.confidence.label) > confGroup(top.confidence.label))
      return `We are less sure about this one (${rec.confidence.label.toLowerCase()} confidence vs ${top.confidence.label.toLowerCase()} for #1), and a less certain facility is never ranked above a more certain one, whatever its quality score.`
    if (dq >= 0) return `Its quality score is ${dq === 0 ? 'the same as' : `${dq} points higher than`} #1's, but the options above it are within 10 points and closer.`
    if (rec.points_below_best != null && rec.points_below_best > 0)
      return `Quality ${rec.score.match} vs ${top.score.match} for #1. It is within 10 points of the best remaining option and closer, so it is not lower still.`
    return `Quality ${rec.score.match} vs ${top.score.match} for #1: more than 10 points lower, so being closer does not move it up.`
  }
  const band = (t) => (t === 'weak' ? 2 : t === 'probable' ? 1 : 0)
  if (band(rec.confidence.tier) > band(top.confidence.tier))
    return `${rec.confidence.tier === 'weak' ? 'Weak' : 'Probable'} evidence is never ranked above ${top.confidence.tier === 'probable' ? 'probable' : 'strong or moderate'} evidence, whatever the distance.`
  return `Match score ${rec.score.match} vs ${top.score.match} for #1 (60% evidence and data quality, 40% distance).`
}

// Everything the card front and the details both need, derived once.
export function describe(rec, top) {
  const address = [rec.address, rec.city, rec.district, rec.state, rec.pincode].filter(Boolean)
  const uniqueAddress = address.filter((v, i) => address.findIndex((w) => String(w).toLowerCase() === String(v).toLowerCase()) === i).join(', ')
  // Header badge: a reviewer's decision outranks the computed confidence.
  const badge = rec.verified_service === 'rejected' ? { tone: 'danger', text: 'Reported unavailable' }
    : BADGE[rec.confidence.label] || BADGE.Unconfirmed
  const beds = tagNumber(rec.tags, 'beds')
  const doctors = tagNumber(rec.tags, 'doctor')
  const kind = [rec.operator_type, rec.facility_type].filter(Boolean).join(' ')
  const facts = [cap(kind), beds && `${beds} beds`, doctors && `${doctors} doctor${doctors === '1' ? '' : 's'}`].filter(Boolean)
  const headsUp = HEADS_UP.filter((h) => h.tags.some((t) => rec.tags.includes(t)))
  const minor = Object.keys(MINOR).filter((t) => rec.tags.includes(t))
  return {
    uniqueAddress, badge, facts, headsUp, minor, reason: rankReason(rec, top),
    found: rec.checks?.filter((c) => c.status === 'found').length ?? 0,
    total: rec.checks?.length ?? 0,
    beyond: rec.ranking_band === 'farther option',
  }
}
