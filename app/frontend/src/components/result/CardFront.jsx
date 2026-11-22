import { useEffect } from 'react'
import { motion } from 'motion/react'
import Icon from '../Icon.jsx'
import Reveal from '../../motion/Reveal.jsx'
import { usePresets } from '../../motion/presets.js'
import { Button } from '../ui/index.js'
import PickStrength from './PickStrength.jsx'
import { locationNote } from './LocationChecks.jsx'
import { directionsHref, fmtKm, fmtMin, justConfirmed, telHref, withScheme } from './shared.js'

// M8: "Confirmed by phone" pulses once when it first appears after a save. It does not pulse on a fresh search
// The set is filled by saveVerification for a confirmed service, just before the search re-runs.
function ConfirmedSignal({ id }) {
  const p = usePresets()
  const pulse = justConfirmed.has(id)
  useEffect(() => { justConfirmed.delete(id) }, [id])
  return (
    <motion.span className="meta-good" initial={false} animate={pulse ? p.pulse : undefined}>
      <Icon name="check" />Confirmed by phone
    </motion.span>
  )
}

// One line of plain text under the name: facts, then the signals that used to be badges.
export function MetaLine({ rec, d }) {
  const loc = locationNote(rec.location_validation)
  const items = [
    ...d.facts.map((f) => <span key={f}>{f}</span>),
    rec.verified_service === 'confirmed' && <ConfirmedSignal key="conf" id={rec.id} />,
    rec.is_nearest_alternative && <span key="near">Closest option</span>,
    loc && <span key="loc">{loc}</span>,
  ].filter(Boolean)
  if (!items.length) return null
  return <p className="facts">{items.flatMap((x, i) => (i ? [<span key={`s${i}`} className="sep" aria-hidden>·</span>, x] : [x]))}</p>
}

export function Stats({ rec, d, showQuality }) {
  const travel = rec.travel_min != null ? fmtMin(rec.travel_min) : rec.distance_km != null ? fmtKm(rec.distance_km) : '-'
  return (
    <dl className="stats">
      <div className="stat stat-main">
        <dt>Travel</dt>
        <dd className="stat-value num">{travel}</dd>
        <dd className={`stat-sub num ${d.beyond ? 'warn-text' : ''}`}>
          {rec.travel_min != null && rec.distance_km != null ? fmtKm(rec.distance_km) : ''}
          {rec.travel_budget_min != null && ` · ${d.beyond ? 'beyond' : 'within'} ${rec.travel_budget_min} min limit`}
        </dd>
      </div>
      {showQuality && (
        <div className="stat">
          <dt>{rec.score.mode === 'quality_first' ? 'Quality' : 'Match score'}</dt>
          <dd className="stat-value num">{Math.round(rec.score.match)} <span className="of">of 100</span></dd>
          <Reveal as="dd" className="meter bar-meter" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, rec.score.match))}%` }} /></Reveal>
        </div>
      )}
      {d.total > 0 ? (
        <div className="stat">
          <dt>Key items found</dt>
          <dd className="stat-value num">{d.found} <span className="of">of {d.total}</span></dd>
          <Reveal as="dd" className="meter" aria-hidden>{rec.checks.map((c) => <i key={c.key} className={`m-${c.status}`} />)}</Reveal>
        </div>
      ) : (
        <div className="stat">
          <dt>Evidence</dt>
          <dd className="stat-value">{rec.confidence.tier ? rec.confidence.tier.charAt(0).toUpperCase() + rec.confidence.tier.slice(1) : '-'}</dd>
          <dd className="stat-sub">in the facility's record</dd>
        </div>
      )}
    </dl>
  )
}

// Pick strength, trade-off, tip and "before you go" share one block with one background.
export function BeforeYouDecide({ rec }) {
  const tradeoff = (rec.is_nearest_alternative || rec.is_better_farther) && rec.tradeoff_note
  if (!rec.pick_strength_note && !tradeoff && !rec.tip_note && !rec.call_to_confirm) return null
  return (
    <section className="decide" onClick={(e) => e.stopPropagation()} aria-label="Before you decide">
      <h4>Before you decide</h4>
      <ul>
        {rec.pick_strength_note && <PickStrength rec={rec} />}
        {tradeoff && <li><Icon name="arrowRight" /><span>{tradeoff}</span></li>}
        {rec.tip_note && <li><Icon name="tip" /><span>{rec.tip_note}</span></li>}
        {rec.call_to_confirm && <li><Icon name="ask" /><span>{rec.call_to_confirm}</span></li>}
      </ul>
    </section>
  )
}

// One caution at most, and only one that changes what the user does. The rest are in the details.
export function Caution({ d }) {
  const h = d.headsUp[0]
  if (!h) return null
  return <p className={`caution ${h.level === 'bad' ? 'bad' : ''}`}><Icon name="warning" /><span>{h.text}</span></p>
}

export function Actions({ rec, hero, open, onToggle }) {
  return (
    <div className="actions" onClick={(e) => e.stopPropagation()}>
      {rec.phone
        ? <Button as="a" variant={hero ? 'primary' : 'secondary'} size={hero ? 'lg' : 'md'} icon="phone" href={telHref(rec.phone)}>
            Call <span className="num">{rec.phone}</span>
          </Button>
        : <span className="muted small">No phone listed</span>}
      {rec.lat != null && <Button as="a" icon="directions" href={directionsHref(rec)} target="_blank" rel="noreferrer">Directions</Button>}
      {rec.website && <Button as="a" icon="globe" href={withScheme(rec.website)} target="_blank" rel="noreferrer">Website</Button>}
      <Button variant="ghost" className="details-toggle" onClick={onToggle} aria-expanded={open} iconRight={open ? 'chevronUp' : 'chevronDown'} iconRightSwap>
        {open ? 'Hide details' : 'Details'}
      </Button>
    </div>
  )
}
