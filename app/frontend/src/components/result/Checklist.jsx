import Icon from '../Icon.jsx'
import { Tooltip } from '../ui/index.js'
import VerifyAction from './VerifyAction.jsx'

const CLAIM_LABEL = { direct: 'stated', list_dump: 'in a list', hedged: 'guess', third_party: 'other institution', negated: 'negative', verified: 'reviewer' }
export const CLAIM_HELP = {
  direct: 'A plain statement in the record. Counts fully.',
  list_dump: 'Named only inside a long list of departments. Counts as moderate evidence at most.',
  hedged: 'A guess, e.g. from photos ("appears to be"). Counts as weak evidence only.',
  third_party: 'About another institution, a paper or a partner, not this facility. Not counted.',
  negated: 'A negative or referral-only mention. Not counted.',
  verified: 'Recorded by a reviewer (e.g. after a phone call). Overrides what the record says for this item.',
}
const STATUS_ICON = { found: 'check', unknown: 'help', contradicted: 'x' }

function toRegex(pattern) {
  if (!pattern) return null
  try { return new RegExp(`(${pattern})`, 'gi') } catch { return null }
}

// Wrap the parts of `text` that matched the pipeline's own regex in <mark>.
export function Highlight({ text, pattern }) {
  const re = toRegex(pattern)
  if (!re) return text
  return text.split(re).map((p, i) => (i % 2 === 1 && p ? <mark key={i}>{p}</mark> : p))
}

export function ClaimTag({ type }) {
  return (
    <Tooltip content={CLAIM_HELP[type]}>
      <span className="claim" tabIndex={0}>{CLAIM_LABEL[type] || type}</span>
    </Tooltip>
  )
}

function VerifyButtons({ label, verify }) {
  return (
    <span className="verify">
      <VerifyAction status="confirmed" label={label} icon="check" ariaLabel={`Confirm: ${label}`} onSave={(note) => verify('confirmed', note)}>Confirm</VerifyAction>
      <VerifyAction status="rejected" label={label} icon="x" ariaLabel={`Reject: ${label}`} onSave={(note) => verify('rejected', note)}>Reject</VerifyAction>
    </span>
  )
}

// What the record shows for each key item, what it doesn't say, and what it contradicts.
export default function Checklist({ checks, pattern, verify }) {
  return (
    <ul className="checklist">
      {checks.map((c) => (
        <li key={c.key} className={`check check-${c.status}`}>
          <span className="status-icon"><Icon name={STATUS_ICON[c.status] || 'help'} label={c.status} /></span>
          <div className="check-body">
            <div className="check-title">
              <span>{c.label}</span>
              {verify && <VerifyButtons label={c.label} verify={(status, note) => verify(c.key, status, c.label, note)} />}
            </div>
            {c.cited_text
              ? <div className="quote">
                  {c.claim_type && c.claim_type !== 'direct' && <ClaimTag type={c.claim_type} />}
                  {c.status === 'contradicted' ? <s><q>{c.cited_text}</q></s> : <q><Highlight text={c.cited_text} pattern={pattern} /></q>}
                </div>
              : <div className="muted small">Not mentioned in the record.</div>}
          </div>
        </li>
      ))}
    </ul>
  )
}
