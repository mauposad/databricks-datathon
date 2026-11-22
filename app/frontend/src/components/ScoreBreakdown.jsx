// Visual version of the ranking score.
//  quality_first: Quality = evidence + readiness + reliability − penalties (ranking also uses travel time)
//  weighted (legacy adapters): match = 0.6 × trust + 0.4 × distance

const PART_CLASS = {
  pts_evidence: 'seg-evidence', pts_sources: 'seg-sources', pts_scale: 'seg-scale', pts_location: 'seg-location',
  q_evidence: 'seg-evidence', q_facility_type: 'seg-scale', q_beds: 'seg-scale', q_support: 'seg-scale',
  q_sources: 'seg-sources', q_location: 'seg-location', q_coherence: 'seg-location',
}

function Parts({ parts }) {
  const positives = parts.filter((p) => p.points > 0)
  const penalties = parts.filter((p) => p.points < 0)
  return (
    <>
      <div className="bar trust-bar">
        {positives.map((p) => (
          <div key={p.key} className={`seg ${PART_CLASS[p.key] || ''}`} style={{ width: `${p.points}%` }}
               title={`${p.label}: ${p.points}/${p.max}`} />
        ))}
      </div>
      <ul className="parts">
        {parts.filter((p) => p.max != null).map((p) => (
          <li key={p.key}>
            <span className={`dot ${PART_CLASS[p.key] || ''}`} />
            {p.label} <b>{p.points}</b><span className="muted">/{p.max}</span>
          </li>
        ))}
        {penalties.map((p) => (
          <li key={p.key} className="penalty"><span className="dot seg-penalty" />{p.label} <b>{p.points}</b></li>
        ))}
      </ul>
    </>
  )
}

export default function ScoreBreakdown({ score, confidence, distanceKm, rec }) {
  if (score.mode === 'quality_first') {
    const sum = (keys) => score.parts.filter((p) => keys.includes(p.key)).reduce((a, p) => a + p.points, 0)
    const evidence = sum(['q_evidence'])
    const readiness = sum(['q_facility_type', 'q_beds', 'q_support'])
    const reliability = sum(['q_sources', 'q_location', 'q_coherence'])
    const penalties = score.parts.filter((p) => p.points < 0).reduce((a, p) => a + p.points, 0)
    return (
      <div className="breakdown">
        <div className="formula">
          <div className="big">{score.match}</div>
          <div className="eq">
            Quality = <b>evidence {evidence}</b>/50 + <b>readiness {readiness}</b>/30 + <b>reliability {reliability}</b>/20
            {penalties < 0 && <> <b>{penalties}</b> penalties</>}
          </div>
        </div>
        {rec?.travel_min != null && (
          <p className="small">
            About <b>{rec.travel_min} min</b> away ({distanceKm} km)
            {rec.travel_budget_min != null && <> · travel budget for this service: <b>{rec.travel_budget_min} min</b>
              {rec.ranking_band === 'farther option' ? ' (beyond it)' : ' (within it)'}</>}
          </p>
        )}
        <Parts parts={score.parts} />
        {rec?.support_found?.length > 0 && (
          <p className="muted small">Supporting services counted: {rec.support_found.join(', ')}.</p>
        )}
        <p className="muted small">Evidence tier: <b>{confidence.tier}</b>. {confidence.rule}</p>
      </div>
    )
  }

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
      <Parts parts={score.parts} />
      <p className="muted small">Evidence tier: <b>{confidence.tier}</b>. {confidence.rule}</p>
    </div>
  )
}
