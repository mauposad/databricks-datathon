import Icon from '../Icon.jsx'
import ScoreBreakdown from '../ScoreBreakdown.jsx'
import { Button } from '../ui/index.js'
import Checklist from './Checklist.jsx'
import Quotes from './Quotes.jsx'
import LocationChecks from './LocationChecks.jsx'
import { hostOf, MINOR, withScheme } from './shared.js'

function Section({ title, defaultOpen = false, children }) {
  return (
    <details className="section" open={defaultOpen}>
      <summary><Icon name="chevronRight" className="chev" />{title}</summary>
      <div className="section-body">{children}</div>
    </details>
  )
}

// Everything behind "Details". Nothing here is dropped from the old card; only the titles changed.
export default function ResultDetails({ rec, d, verify }) {
  const { headsUp, minor, reason } = d
  const more = headsUp.slice(1)  // the first heads-up is on the card front
  return (
    <div className="details" onClick={(e) => e.stopPropagation()}>
      <p className="address"><Icon name="pin" /><span>{d.uniqueAddress || 'Address not listed'}</span></p>

      {rec.checks?.length > 0 && (
        <Section title="What their record says" defaultOpen>
          <Checklist checks={rec.checks} pattern={rec.match_pattern} verify={verify} />
        </Section>
      )}

      <Section title="Exact quotes from the record" defaultOpen={!rec.checks?.length}>
        <Quotes rec={rec} />
      </Section>

      {(rec.caveats.length > 0 || more.length > 0 || minor.length > 0) && (
        <Section title="What could be wrong with this record" defaultOpen={more.length > 1}>
          <ul className="caveats">
            {more.map((h) => <li key={h.text}>{h.text}</li>)}
            {rec.caveats.map((c, i) => <li key={i}>{c}</li>)}
            {minor.map((t) => <li key={t}>{MINOR[t]}</li>)}
          </ul>
        </Section>
      )}

      {rec.location_validation && (
        <Section title="Do the pincode, city and map point agree?">
          <LocationChecks lv={rec.location_validation} />
        </Section>
      )}

      {(reason || rec.counterfactual_note || (rec.tradeoff_note && !rec.is_nearest_alternative && !rec.is_better_farther)) && (
        <Section title={`Why this is #${rec.rank}`}>
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
            <Button size="sm" icon="check" onClick={() => verify('service', 'confirmed', 'they offer this service')}>They offer this service</Button>
            <Button size="sm" icon="x" onClick={() => verify('service', 'rejected', 'they do not offer this service')}>Not available</Button>
          </div>
        </Section>
      )}

      {(rec.sources.length > 0 || rec.email || rec.facebook) && (
        <Section title="Sources and other contacts">
          <div className="sources">
            {rec.email && <a href={`mailto:${rec.email}`}><Icon name="mail" /> {rec.email}</a>}
            {rec.facebook && <a href={withScheme(rec.facebook)} target="_blank" rel="noreferrer">Facebook</a>}
            {rec.sources.filter((s, i, all) => all.findIndex((t) => hostOf(t) === hostOf(s)) === i).slice(0, 8).map((s) => (
              <a key={s} href={s} target="_blank" rel="noreferrer">{hostOf(s)}</a>
            ))}
          </div>
          <details className="raw">
            <summary><Icon name="chevronRight" className="chev" />Plain-text explanation</summary>
            <p>{rec.why}</p>
            <p className="mono">{rec.how}</p>
          </details>
        </Section>
      )}
    </div>
  )
}
