import { ClaimTag, Highlight } from './Checklist.jsx'

export default function Quotes({ rec }) {
  if (rec.claims?.length > 0) {
    return (
      <ul className="evidence">
        {rec.claims.map((c, i) => {
          const struck = c.claim_type === 'third_party' || c.claim_type === 'negated'
          const quote = <q><Highlight text={c.text} pattern={rec.match_pattern} /></q>
          return (
            <li key={i} className={struck ? 'rejected' : ''}>
              <span className="field-tag">{c.field}</span>
              {c.claim_type !== 'direct' && <ClaimTag type={c.claim_type} />}
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
          <li key={i}><span className="field-tag">{e.field}</span><q><Highlight text={e.text} pattern={rec.match_pattern} /></q></li>
        ))}
        {rec.rejected_evidence.map((t, i) => (
          <li key={`r${i}`} className="rejected"><span className="claim">not counted</span><s>{t}</s></li>
        ))}
      </ul>
    </>
  )
}
