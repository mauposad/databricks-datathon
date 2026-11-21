import { useEffect, useRef, useState } from 'react'
import ScoreBreakdown from './ScoreBreakdown.jsx'

const CONF_CLASS = { High: 'conf-high', Medium: 'conf-med', Low: 'conf-low', Probable: 'conf-low', Unconfirmed: 'conf-none' }
// Ranking bands used by find_care: strong/moderate, then probable, then weak
const tierBand = (t) => (t === 'weak' ? 2 : t === 'probable' ? 1 : 0)
const WARN_TAGS = ['Single source', 'Possible merged record', 'Not a hospital', 'Has referral mentions', 'Location uncertain', 'Weak evidence', 'Farther option', 'Possible duplicate record', 'Identity not settled']

function toRegex(pattern) {
  if (!pattern) return null
  try { return new RegExp(`(${pattern})`, 'gi') } catch { return null }
}

// Wrap the parts of `text` that matched the pipeline's own regex in <mark>.
function Highlight({ text, pattern }) {
  const re = toRegex(pattern)
  if (!re) return text
  const parts = text.split(re)
  return parts.map((p, i) => (i % 2 === 1 && p ? <mark key={i}>{p}</mark> : p))
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

function Contact({ icon, label, value, href }) {
  return (
    <div className={value ? 'contact' : 'contact missing'}>
      <span aria-hidden>{icon}</span>
      {value
        ? <a href={href || value} target="_blank" rel="noreferrer">{label || value}</a>
        : <span>{label ? `${label}: ` : ''}Not listed</span>}
    </div>
  )
}

// Explain, component by component, why this facility ranks below #1.
function Comparison({ rec, top }) {
  if (!top || rec.id === top.id) return null
  const dTrust = rec.score.trust - top.score.trust
  const dDist = rec.score.distance - top.score.distance
  const byKey = Object.fromEntries(top.score.parts.map((p) => [p.key, p.points]))
  const diffs = rec.score.parts
    .map((p) => ({ label: p.label, d: p.points - (byKey[p.key] ?? 0) }))
    .concat(top.score.parts.filter((p) => !rec.score.parts.some((q) => q.key === p.key)).map((p) => ({ label: p.label, d: -p.points })))
    .filter((x) => x.d !== 0)
  const sign = (n) => (n > 0 ? `+${n}` : `${n}`)
  if (rec.score.mode === 'quality_first') {
    const dq = rec.score.match - top.score.match
    let reason
    if (rec.ranking_band === 'unconfirmed') reason = 'Its evidence is weak, and weak evidence always comes after confirmed or probable options.'
    else if (rec.ranking_band === 'farther option' && top.ranking_band === 'reachable')
      reason = `It is about ${rec.travel_min} min away, beyond the ${rec.travel_budget_min}-minute travel budget for this service, so it comes after every reachable option.`
    else if (dq >= 0) reason = `Its Quality is ${dq === 0 ? 'the same as' : `${dq} points higher than`} #1's, but facilities ranked above it are within 10 points of the best remaining option and closer.`
    else if (rec.points_below_best != null && rec.points_below_best > 0)
      reason = `Quality ${rec.score.match} vs ${top.score.match} (${dq}). When it was ranked, the best remaining Quality was ${rec.score.match + rec.points_below_best}; it is within 10 points of that and closer, which is why it is not lower still.`
    else reason = `Quality ${rec.score.match} vs ${top.score.match} (${dq}): more than 10 points lower, so being closer does not move it up.`
    return (
      <div className="compare">
        <h5>Why #{rec.rank} is below #1</h5>
        <p>{reason}</p>
        {diffs.length > 0 && (
          <ul className="diffs">
            {diffs.map((x) => <li key={x.label} className={x.d > 0 ? 'up' : 'down'}>{x.label}: {sign(x.d)}</li>)}
          </ul>
        )}
      </div>
    )
  }
  return (
    <div className="compare">
      <h5>Why #{rec.rank} is below #1</h5>
      {tierBand(rec.confidence.tier) > tierBand(top.confidence.tier)
        ? <p>
            {rec.confidence.tier === 'weak' ? 'Weak' : 'Probable'} evidence is never ranked above
            {top.confidence.tier === 'probable' ? ' probable' : ' strong or moderate'} evidence, whatever the distance.
          </p>
        : (
          <p>
            Match {rec.score.match} vs {top.score.match}: trust {sign(dTrust)} (×0.6 = {sign(+(0.6 * dTrust).toFixed(1))}),
            distance score {sign(dDist)} (×0.4 = {sign(+(0.4 * dDist).toFixed(1))}).
          </p>
        )}
      {diffs.length > 0 && (
        <ul className="diffs">
          {diffs.map((x) => <li key={x.label} className={x.d > 0 ? 'up' : 'down'}>{x.label}: {sign(x.d)}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function ResultCard({ rec, top, selected, onSelect }) {
  const [open, setOpen] = useState(rec.rank === 1)
  const ref = useRef(null)
  useEffect(() => { if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [selected])

  const address = [rec.address, rec.city, rec.district, rec.state, rec.pincode].filter(Boolean)
  const uniqueAddress = address.filter((v, i) => address.findIndex((w) => String(w).toLowerCase() === String(v).toLowerCase()) === i).join(', ')

  return (
    <article ref={ref} className={`card ${selected ? 'selected' : ''}`} onClick={onSelect}>
      <header className="card-head">
        <span className="rank">{rec.rank}</span>
        <div className="title">
          <h3>{rec.name}</h3>
          <p className="muted">{uniqueAddress || 'Address not listed'}</p>
        </div>
        <div className="right-meta">
          <span className={`conf ${CONF_CLASS[rec.confidence.label]}`} title={rec.confidence.rule}>
            {rec.confidence.label} confidence
          </span>
          {rec.distance_km != null && <span className="dist">{rec.distance_km} km</span>}
        </div>
      </header>

      <div className="tags">
        {rec.tags.map((t) => <span key={t} className={WARN_TAGS.includes(t) ? 'tag warn' : 'tag'}>{t}</span>)}
      </div>

      {(rec.tradeoff_note || rec.counterfactual_note) && (
        <div className="tradeoff">
          {rec.tradeoff_note && <p><b>{rec.is_nearest_alternative ? 'Nearest option' : 'Trade-off'}:</b> {rec.tradeoff_note}</p>}
          {rec.counterfactual_note && <p className="muted small">{rec.counterfactual_note}</p>}
        </div>
      )}

      <div className="contacts">
        <Contact icon="📞" label={rec.phone} value={rec.phone} href={rec.phone && `tel:${rec.phone.replace(/[^+\d]/g, '')}`} />
        <Contact icon="🌐" label={rec.website && hostOf(rec.website)} value={rec.website}
                 href={rec.website && (rec.website.startsWith('http') ? rec.website : `https://${rec.website}`)} />
        <Contact icon="f" label="Facebook" value={rec.facebook} />
        {rec.email && <Contact icon="✉" label={rec.email} value={rec.email} href={`mailto:${rec.email}`} />}
      </div>

      <button className="why-toggle" onClick={(e) => { e.stopPropagation(); setOpen(!open) }} aria-expanded={open}>
        {open ? '▾' : '▸'} Why this was recommended
      </button>

      {open && (
        <div className="why" onClick={(e) => e.stopPropagation()}>
          <ScoreBreakdown score={rec.score} confidence={rec.confidence} distanceKm={rec.distance_km} rec={rec} />

          <h5>Evidence from the facility's record <span className="muted">(verbatim, by column)</span></h5>
          {rec.evidence.length === 0 && <p className="muted">No direct mention of this service in the record.</p>}
          <ul className="evidence">
            {rec.evidence.map((e, i) => (
              <li key={i}>
                <span className="field">{e.field}</span>
                <q><Highlight text={e.text} pattern={rec.match_pattern} /></q>
              </li>
            ))}
          </ul>

          {rec.rejected_evidence.length > 0 && (
            <>
              <h5>Mentions we did not count <span className="muted">(negative or referral-only)</span></h5>
              <ul className="evidence rejected">
                {rec.rejected_evidence.map((t, i) => <li key={i}><s>{t}</s></li>)}
              </ul>
            </>
          )}

          {rec.caveats.length > 0 && (
            <>
              <h5>What we're unsure about</h5>
              <ul className="caveats">{rec.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          )}

          <Comparison rec={rec} top={top} />

          {rec.sources.length > 0 && (
            <>
              <h5>Sources</h5>
              <div className="sources">
                {rec.sources.filter((s, i, all) => all.findIndex((t) => hostOf(t) === hostOf(s)) === i).slice(0, 8).map((s) => (
                  <a key={s} href={s} target="_blank" rel="noreferrer">{hostOf(s)}</a>
                ))}
              </div>
            </>
          )}

          <details className="raw">
            <summary>Plain-text explanation</summary>
            <p>{rec.why}</p>
            <p className="mono">{rec.how}</p>
          </details>
        </div>
      )}
    </article>
  )
}
