import { useEffect, useRef, useState } from 'react'
import ScoreBreakdown from './ScoreBreakdown.jsx'
import * as api from '../api.js'

// ---------------------------------------------------------------------------
// Plain-language labels
// ---------------------------------------------------------------------------

const BADGE = {
  High: { cls: 'good', text: 'High confidence' },
  Medium: { cls: 'ok', text: 'Medium confidence' },
  Low: { cls: 'bad', text: 'Low confidence' },
  Probable: { cls: 'ok', text: 'Likely · call to confirm' },
  Unconfirmed: { cls: 'none', text: 'Unconfirmed' },
}

// Tags that are worth a "heads up" on the front of the card, in priority order, with plain wording.
// Several record-identity tags collapse into one message.
const HEADS_UP = [
  { tags: ['Reported not available'], text: 'A reviewer reported this service is not available here.', level: 'bad' },
  { tags: ['Identity not settled', 'Possible duplicate record', 'Possible merged record'], text: 'This record may be duplicated or mixed up with another facility.' },
  { tags: ['Not a hospital'], text: 'Not a hospital — may be a clinic or smaller centre.' },
  { tags: ['Location uncertain'], text: 'Map location is approximate.' },
  { tags: ['Farther option'], text: 'Farther than the usual travel time for this service.' },
]
// Minor data-quality tags: shown only in the details.
const MINOR = { 'Single source': 'Only one website or listing mentions this facility.', 'Has referral mentions': 'Some mentions only refer patients elsewhere; those were not counted.' }

const telHref = (phone) => `tel:${phone.replace(/[^+\d]/g, '')}`
const hostOf = (url) => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url } }
const withScheme = (url) => (url.startsWith('http') ? url : `https://${url}`)
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const fmtMin = (m) => (m < 1 ? 'Under 1 min' : `~${m} min`)
const fmtKm = (km) => (km < 1 ? 'under 1 km' : `${km} km`)
const tagNumber =(tags, word) => tags.map((t) => t.match(new RegExp(`^(\\d+) ${word}`))).find(Boolean)?.[1]

// Ask for an optional note, then record a reviewer decision in the verifications overlay.
async function recordVerification({ facilityId, serviceKey, checkKey, status, label, onVerified }) {
  const note = window.prompt(`${status === 'confirmed' ? 'Confirm' : 'Reject'}: ${label}\nOptional note (who you spoke to, source):`, '')
  if (note === null) return
  try {
    await api.verify({ facility_id: facilityId, service_key: serviceKey, check_key: checkKey, status, note: note || null })
    onVerified?.()
  } catch (e) { alert(`Could not save: ${e.message}`) }
}

function toRegex(pattern) {
  if (!pattern) return null
  try { return new RegExp(`(${pattern})`, 'gi') } catch { return null }
}

// Wrap the parts of `text` that matched the pipeline's own regex in <mark>.
function Highlight({ text, pattern }) {
  const re = toRegex(pattern)
  if (!re) return text
  return text.split(re).map((p, i) => (i % 2 === 1 && p ? <mark key={i}>{p}</mark> : p))
}

const CLAIM_LABEL = { direct: 'stated', list_dump: 'in a list', hedged: 'guess', third_party: 'other institution', negated: 'negative', verified: 'reviewer' }
const CLAIM_HELP = {
  direct: 'A plain statement in the record. Counts fully.',
  list_dump: 'Named only inside a long list of departments. Counts as moderate evidence at most.',
  hedged: 'A guess, e.g. from photos ("appears to be"). Counts as weak evidence only.',
  third_party: 'About another institution, a paper or a partner, not this facility. Not counted.',
  negated: 'A negative or referral-only mention. Not counted.',
  verified: 'Recorded by a reviewer (e.g. after a phone call). Overrides what the record says for this item.',
}
const STATUS_ICON = { found: '✓', unknown: '?', contradicted: '✗' }

// ---------------------------------------------------------------------------
// Detail sections
// ---------------------------------------------------------------------------

function VerifyButtons({ label, verify }) {
  return (
    <span className="verify">
      <button className="vbtn ok" title={`Confirm: ${label}`} onClick={() => verify('confirmed')}>✓ Confirm</button>
      <button className="vbtn no" title={`Reject: ${label}`} onClick={() => verify('rejected')}>✗ Reject</button>
    </span>
  )
}

// What the record shows for each key item, what it doesn't say, and what it contradicts.
function Checklist({ checks, pattern, verify }) {
  return (
    <ul className="checklist">
      {checks.map((c) => (
        <li key={c.key} className={`check check-${c.status}`}>
          <span className="icon" aria-label={c.status}>{STATUS_ICON[c.status] || '?'}</span>
          <div className="check-body">
            <div className="check-title">
              <span>{c.label}</span>
              {verify && <VerifyButtons label={c.label} verify={(status) => verify(c.key, status, c.label)} />}
            </div>
            {c.cited_text
              ? <div className="quote">
                  {c.claim_type && c.claim_type !== 'direct' &&
                    <span className={`claim claim-${c.claim_type}`} title={CLAIM_HELP[c.claim_type]}>{CLAIM_LABEL[c.claim_type]}</span>}
                  {c.status === 'contradicted' ? <s><q>{c.cited_text}</q></s> : <q><Highlight text={c.cited_text} pattern={pattern} /></q>}
                </div>
              : <div className="muted small">Not mentioned in the record.</div>}
          </div>
        </li>
      ))}
    </ul>
  )
}

function Quotes({ rec }) {
  if (rec.claims?.length > 0) {
    return (
      <ul className="evidence">
        {rec.claims.map((c, i) => {
          const struck = c.claim_type === 'third_party' || c.claim_type === 'negated'
          const quote = <q><Highlight text={c.text} pattern={rec.match_pattern} /></q>
          return (
            <li key={i} className={struck ? 'rejected' : ''}>
              <span className="field">{c.field}</span>
              {c.claim_type !== 'direct' &&
                <span className={`claim claim-${c.claim_type}`} title={CLAIM_HELP[c.claim_type]}>{CLAIM_LABEL[c.claim_type] || c.claim_type}</span>}
              {struck ? <s>{quote}</s> : quote}
            </li>
          )
        })}
      </ul>
    )
  }
  return (
    <>
      {rec.evidence.length === 0 && <p className="muted small">No direct mention of this service in the record.</p>}
      <ul className="evidence">
        {rec.evidence.map((e, i) => (
          <li key={i}><span className="field">{e.field}</span><q><Highlight text={e.text} pattern={rec.match_pattern} /></q></li>
        ))}
        {rec.rejected_evidence.map((t, i) => (
          <li key={`r${i}`} className="rejected"><span className="claim claim-negated">not counted</span><s>{t}</s></li>
        ))}
      </ul>
    </>
  )
}

// Explain why this facility ranks below #1, in one or two sentences.
function rankReason(rec, top) {
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

// "How solid is this pick?" (#1 only): a one-line verdict, with the double-checks behind it on request.
function CheckRow({ c }) {
  const result = c.still_first === true ? <span className="still">✓ Still #1</span>
    : c.still_first === false ? <span className="moves">→ {c.winner} would be #1</span>
    : <span className="muted">No facility passes this check</span>
  return <li><span className="check-label">{c.label}</span>{result}</li>
}

function PickStrength({ rec }) {
  const solid = rec.pick_strength === 'Solid'
  const data = rec.double_checks.filter((c) => c.kind === 'data')
  const situation = rec.double_checks.filter((c) => c.kind === 'situation')
  return (
    <div className={`pick ${solid ? 'solid' : 'shaky'}`} onClick={(e) => e.stopPropagation()}>
      <p className="pick-line"><span aria-hidden>{solid ? '🛡' : '⚠'}</span> {rec.pick_strength_note}</p>
      {data.length > 0 && (
        <details className="pick-checks">
          <summary>See the {data.length} double-checks</summary>
          <p className="small muted">
            We re-ran the ranking {data.length} more times, each time doubting one part of the data. If #1 stays on top
            every time, it is a solid pick. If not, the facility that takes its place is the one to call second.
          </p>
          <ul>{data.map((c) => <CheckRow key={c.label} c={c} />)}</ul>
          {situation.length > 0 && (
            <>
              <p className="pick-sub">If your situation is different</p>
              <ul>{situation.map((c) => <CheckRow key={c.label} c={c} />)}</ul>
            </>
          )}
        </details>
      )}
    </div>
  )
}

function Section({ title, defaultOpen = false, children }) {
  return (
    <details className="section" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="section-body">{children}</div>
    </details>
  )
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export default function ResultCard({ rec, top, selected, onSelect, serviceKey, onVerified }) {
  const verify = serviceKey
    ? (checkKey, status, label) => recordVerification({ facilityId: rec.id, serviceKey, checkKey, status, label, onVerified })
    : null
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => { if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [selected])

  const address = [rec.address, rec.city, rec.district, rec.state, rec.pincode].filter(Boolean)
  const uniqueAddress = address.filter((v, i) => address.findIndex((w) => String(w).toLowerCase() === String(v).toLowerCase()) === i).join(', ')

  // Header badge: a reviewer's decision outranks the computed confidence.
  const badge = rec.verified_service === 'rejected' ? { cls: 'bad', text: 'Reported unavailable' }
    : BADGE[rec.confidence.label] || BADGE.Unconfirmed

  // Facility facts in one line: "Private hospital · 100 beds · 75 doctors"
  const beds = tagNumber(rec.tags, 'beds')
  const doctors = tagNumber(rec.tags, 'doctor')
  const kind = [rec.operator_type, rec.facility_type].filter(Boolean).join(' ')
  const facts = [cap(kind), beds && `${beds} beds`, doctors && `${doctors} doctor${doctors === '1' ? '' : 's'}`].filter(Boolean)

  // Key stats
  const found = rec.checks?.filter((c) => c.status === 'found').length ?? 0
  const total = rec.checks?.length ?? 0
  const beyond = rec.ranking_band === 'farther option'

  // At most two heads-up messages on the front; the rest live in the details.
  const headsUp = HEADS_UP.filter((h) => h.tags.some((t) => rec.tags.includes(t)))
  const minor = Object.keys(MINOR).filter((t) => rec.tags.includes(t))
  const reason = rankReason(rec, top)
  const stop = (e) => e.stopPropagation()

  return (
    <article ref={ref} className={`card ${selected ? 'selected' : ''}`} onClick={onSelect}>
      <header className="card-head">
        <span className="rank" aria-label={`Rank ${rec.rank}`}>{rec.rank}</span>
        <div className="title">
          <h3>{rec.name}</h3>
          {facts.length > 0 && <p className="facts">{facts.join(' · ')}</p>}
        </div>
        <div className="badges">
          <span className={`badge ${badge.cls}`}>{badge.text}</span>
          {rec.verified_service === 'confirmed' && <span className="badge good">✓ Confirmed by phone</span>}
          {rec.is_nearest_alternative && <span className="badge info">Closest option</span>}
        </div>
      </header>

      <div className="stats">
        <div className="stat">
          <span className="stat-label">Travel</span>
          <span className="stat-value">{rec.travel_min != null ? fmtMin(rec.travel_min) : rec.distance_km != null ? fmtKm(rec.distance_km) : '—'}</span>
          <span className={`stat-sub ${beyond ? 'warn-text' : ''}`}>
            {rec.travel_min != null && rec.distance_km != null ? fmtKm(rec.distance_km) : ''}
            {rec.travel_budget_min != null && ` · ${beyond ? 'beyond' : 'within'} ${rec.travel_budget_min} min limit`}
          </span>
        </div>
        {total > 0 ? (
          <div className="stat">
            <span className="stat-label">Key items found</span>
            <span className="stat-value">{found} <span className="of">of {total}</span></span>
            <span className="meter" aria-hidden>
              {rec.checks.map((c) => <i key={c.key} className={`m-${c.status}`} />)}
            </span>
          </div>
        ) : (
          <div className="stat">
            <span className="stat-label">Evidence</span>
            <span className="stat-value">{cap(rec.confidence.tier) || '—'}</span>
            <span className="stat-sub">in the facility's record</span>
          </div>
        )}
        <div className="stat">
          <span className="stat-label">{rec.score.mode === 'quality_first' ? 'Quality score' : 'Match score'}</span>
          <span className="stat-value">{Math.round(rec.score.match)} <span className="of">/ 100</span></span>
          <span className="meter bar-meter" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, rec.score.match))}%` }} /></span>
        </div>
      </div>

      {(rec.is_nearest_alternative || rec.is_better_farther) && rec.tradeoff_note && (
        <p className="tradeoff">{rec.tradeoff_note}</p>
      )}

      {rec.pick_strength_note && <PickStrength rec={rec} />}
      {rec.tip_note && <p className="tip"><span aria-hidden>💡</span> {rec.tip_note}</p>}

      {headsUp.length > 0 && (
        <ul className={`heads-up ${headsUp.some((h) => h.level === 'bad') ? 'bad' : ''}`}>
          {headsUp.slice(0, 2).map((h) => <li key={h.text}>{h.text}</li>)}
          {headsUp.length > 2 && <li className="more">+{headsUp.length - 2} more in details</li>}
        </ul>
      )}

      {rec.call_to_confirm && (
        <p className="ask"><span aria-hidden>💬</span> <b>Before you go:</b> {rec.call_to_confirm}</p>
      )}

      <div className="actions" onClick={stop}>
        {rec.phone
          ? <a className="btn primary-btn" href={telHref(rec.phone)}>📞 Call {rec.phone}</a>
          : <span className="btn disabled">No phone listed</span>}
        {rec.website && <a className="btn" href={withScheme(rec.website)} target="_blank" rel="noreferrer">Website</a>}
        {rec.lat != null && (
          <a className="btn" href={`https://www.google.com/maps/dir/?api=1&destination=${rec.lat},${rec.lon}`} target="_blank" rel="noreferrer">Directions</a>
        )}
        <button className="details-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? 'Hide details' : 'Details'} <span aria-hidden>{open ? '▴' : '▾'}</span>
        </button>
      </div>

      {open && (
        <div className="details" onClick={stop}>
          <p className="address"><span className="muted">Address:</span> {uniqueAddress || 'Not listed'}</p>

          {rec.checks?.length > 0 && (
            <Section title="What their record says" defaultOpen>
              <Checklist checks={rec.checks} pattern={rec.match_pattern} verify={verify} />
            </Section>
          )}

          <Section title="Exact quotes from the record" defaultOpen={!rec.checks?.length}>
            <Quotes rec={rec} />
          </Section>

          {(rec.caveats.length > 0 || headsUp.length > 0 || minor.length > 0) && (
            <Section title="Things to double-check" defaultOpen={headsUp.length > 2}>
              <ul className="caveats">
                {headsUp.slice(2).map((h) => <li key={h.text}>{h.text}</li>)}
                {rec.caveats.map((c, i) => <li key={i}>{c}</li>)}
                {minor.map((t) => <li key={t}>{MINOR[t]}</li>)}
              </ul>
            </Section>
          )}

          {(reason || rec.counterfactual_note || (rec.tradeoff_note && !rec.is_nearest_alternative && !rec.is_better_farther)) && (
            <Section title={rec.rank === 1 ? 'Why this is #1' : `Why this is #${rec.rank}`}>
              {reason && <p>{reason}</p>}
              {rec.tradeoff_note && !rec.is_nearest_alternative && !rec.is_better_farther && <p>{rec.tradeoff_note}</p>}
              {rec.counterfactual_note && <p>{rec.counterfactual_note}</p>}
            </Section>
          )}

          <Section title="How the score is calculated">
            <ScoreBreakdown score={rec.score} confidence={rec.confidence} distanceKm={rec.distance_km} rec={rec} />
          </Section>

          {verify && (
            <Section title="Record what you learned by phone">
              <p className="small muted">Saved for everyone and reflected the next time this search runs.</p>
              <div className="verify-service">
                <button className="vbtn ok" onClick={() => verify('service', 'confirmed', 'they offer this service')}>✓ They offer this service</button>
                <button className="vbtn no" onClick={() => verify('service', 'rejected', 'they do not offer this service')}>✗ Not available</button>
              </div>
            </Section>
          )}

          {(rec.sources.length > 0 || rec.email || rec.facebook) && (
            <Section title="Sources and other contacts">
              <div className="sources">
                {rec.email && <a href={`mailto:${rec.email}`}>✉ {rec.email}</a>}
                {rec.facebook && <a href={withScheme(rec.facebook)} target="_blank" rel="noreferrer">Facebook</a>}
                {rec.sources.filter((s, i, all) => all.findIndex((t) => hostOf(t) === hostOf(s)) === i).slice(0, 8).map((s) => (
                  <a key={s} href={s} target="_blank" rel="noreferrer">{hostOf(s)}</a>
                ))}
              </div>
              <details className="raw">
                <summary>Plain-text explanation</summary>
                <p>{rec.why}</p>
                <p className="mono">{rec.how}</p>
              </details>
            </Section>
          )}
        </div>
      )}
    </article>
  )
}
