// Visual version of: match = 0.6 × trust + 0.4 × distance, with trust split into its components.

const PART_CLASS = {
  pts_evidence: 'seg-evidence', pts_sources: 'seg-sources', pts_scale: 'seg-scale', pts_location: 'seg-location',
}

export default function ScoreBreakdown({ score, confidence, distanceKm }) {
  const positives = score.parts.filter((p) => p.points > 0)
  const penalties = score.parts.filter((p) => p.points < 0)
  const trustPart = +(score.trust_weight * score.trust).toFixed(1)
  const distPart = +(score.distance_weight * score.distance).toFixed(1)

  return (
    <div className="breakdown">
      <div className="formula">
        <div className="big">{score.match}</div>
        <div className="eq">
          match score = <b>0.6 × trust {score.trust}</b> ({trustPart}) + <b>0.4 × distance {score.distance}</b> ({distPart})
          {distanceKm != null && <span className="muted"> · {distanceKm} km away</span>}
        </div>
      </div>

      <div className="bar match-bar" aria-label="match score split">
        <div className="seg seg-trust" style={{ width: `${trustPart}%` }} title={`Trust contributes ${trustPart}`} />
        <div className="seg seg-distance" style={{ width: `${distPart}%` }} title={`Distance contributes ${distPart}`} />
      </div>

      <div className="trust-label">Trust score {score.trust}/100 is made of:</div>
      <div className="bar trust-bar">
        {positives.map((p) => (
          <div key={p.key} className={`seg ${PART_CLASS[p.key] || ''}`} style={{ width: `${p.points}%` }}
               title={`${p.label}: ${p.points}/${p.max}`} />
        ))}
      </div>
      <ul className="parts">
        {score.parts.filter((p) => p.max != null).map((p) => (
          <li key={p.key}>
            <span className={`dot ${PART_CLASS[p.key] || ''}`} />
            {p.label} <b>{p.points}</b><span className="muted">/{p.max}</span>
          </li>
        ))}
        {penalties.map((p) => (
          <li key={p.key} className="penalty"><span className="dot seg-penalty" />{p.label} <b>{p.points}</b></li>
        ))}
      </ul>
      <p className="muted small">Evidence tier: <b>{confidence.tier}</b>. {confidence.rule}</p>
    </div>
  )
}
