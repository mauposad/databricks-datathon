import Icon from '../Icon.jsx'

// Location validation (notebooks/location_validation_scoring): do the record's pincode, city, district, postal
// circle and map point agree? Its weighted agreement feeds the location part of Quality. Facilities scoring 0-2
// never reach the app (find_care leaves them out).
const LOC_ICON = { pass: 'check', partial: 'half', fail: 'x', missing: 'minus' }
const LOC_CLASS = { pass: 'check-found', partial: 'check-unknown', fail: 'check-contradicted', missing: 'check-unknown' }
export const LOC_LABEL = { verified_all: 'every check agrees', verified_strong: 'strong agreement', verified_partial: 'partial agreement' }

// Plain text for the card front, only when there is something to say (a 5/5 is not news).
export function locationNote(lv) {
  if (!lv) return null
  if (lv.status !== 'scored') return 'Location not validated'
  if (lv.score >= 5) return null
  return `Location checks ${lv.score}/5`
}

export default function LocationChecks({ lv }) {
  if (lv.status !== 'scored') {
    return <p className="muted small">Not checked yet: this record has no location validation score.</p>
  }
  return (
    <>
      <p className="small muted">
        {lv.score}/5, {LOC_LABEL[lv.label] || lv.label}. We compare the record's own pincode, city, district, postal
        circle and map point with each other. How well they agree makes up the location part of Quality.
      </p>
      <ul className="checklist">
        {lv.checks.map((c) => (
          <li key={c.key} className={`check ${LOC_CLASS[c.status] || 'check-unknown'}`}>
            <span className="status-icon"><Icon name={LOC_ICON[c.status] || 'help'} label={c.status} /></span>
            <div className="check-body">
              <div className="check-title">
                <span>{c.label}</span>
                {c.kind === 'secondary' && <span className="muted small">supporting check</span>}
              </div>
              {(c.status === 'fail' || c.status === 'partial') && c.why && <div className="muted small">{c.why}</div>}
              {c.status === 'missing' && <div className="muted small">Not in the record (does not count against it).</div>}
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}
