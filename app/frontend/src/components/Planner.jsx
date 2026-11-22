import { useEffect, useMemo, useState } from 'react'
import * as api from '../api.js'

const SERVICES = [
  ['emergency_csection', 'Emergency C-section'], ['nicu', 'NICU'], ['dialysis', 'Dialysis'], ['trauma', 'Trauma'],
  ['cardiac_surgery', 'Cardiac surgery'], ['mri', 'MRI'], ['emergency_24x7', '24/7 emergency'],
]

// NFHS-5 indicators shown next to access, picked to be relevant to each service
const INDICATORS = {
  emergency_csection: [['institutional_birth_pct', 'Institutional births %'], ['institutional_birth_public_pct', 'Births in public facility %'], ['csection_rate_pct', 'C-section rate %']],
  nicu: [['institutional_birth_pct', 'Institutional births %'], ['institutional_birth_public_pct', 'Births in public facility %'], ['women_anaemic_pct', 'Women anaemic %']],
  dialysis: [['women_high_blood_sugar_pct', 'Women high blood sugar %'], ['men_high_blood_sugar_pct', 'Men high blood sugar %'], ['women_high_bp_pct', 'Women high BP %']],
  trauma: [['health_insurance_pct', 'Household health insurance %']],
  cardiac_surgery: [['women_high_bp_pct', 'Women high BP %'], ['men_high_blood_sugar_pct', 'Men high blood sugar %'], ['health_insurance_pct', 'Household health insurance %']],
  mri: [['health_insurance_pct', 'Household health insurance %']],
  emergency_24x7: [['health_insurance_pct', 'Household health insurance %']],
}

export default function Planner() {
  const [service, setService] = useState('emergency_csection')
  const [state, setState] = useState('')
  const [rows, setRows] = useState([])
  const [allStates, setAllStates] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true); setError('')
    api.planner(service, state || null)
      .then((r) => { setRows(r); if (!state) setAllStates([...new Set(r.map((x) => x.state))].sort()) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [service, state])

  const ind = INDICATORS[service] || []
  const budget = rows[0]?.travel_budget_min
  const gaps = useMemo(() => rows.filter((r) => !r.quality_within_budget).length, [rows])

  return (
    <div className="panel planner">
      <div className="planner-head">
        <div>
          <h2>District planner</h2>
          <p className="muted small">
            Travel time from each district centre to the nearest <b>quality facility</b> (strong or moderate evidence and
            Quality ≥ 70) and to the nearest facility with any confirmed or probable evidence, next to NFHS-5 indicators.
            Travel time = km × 1.4 ÷ 35 km/h. A gap means <b>no facility documented in this dataset</b>, not that none exists.
          </p>
        </div>
        <div className="planner-controls">
          <select value={service} onChange={(e) => setService(e.target.value)}>
            {SERVICES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All states</option>
            {allStates.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}
      {!loading && rows.length > 0 && (
        <p className="small"><b>{gaps}</b> of {rows.length} districts have no documented quality facility within the
          {' '}{budget}-minute travel budget for this service. Worst access first.</p>
      )}
      {loading ? <div className="skeleton" /> : (
        <div className="table-wrap">
          <table className="planner-table">
            <thead>
              <tr>
                <th>District</th><th>Nearest quality facility</th><th>Travel</th><th>Nearest any evidence</th>
                <th title="Facilities with confirmed or probable evidence within the travel budget">Reachable</th>
                {ind.map(([k, l]) => <th key={k}>{l}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.district + r.state} className={r.quality_within_budget ? '' : 'gap'}>
                  <td><b>{r.district}</b><div className="muted small">{r.state}</div></td>
                  <td>{r.quality_facility || <span className="muted">none documented</span>}
                    {r.quality_facility && <div className="muted small">Quality {r.quality_facility_quality} · {r.quality_km} km</div>}</td>
                  <td className={r.quality_within_budget ? 'ok' : 'bad'}>{r.quality_travel_min != null ? `${r.quality_travel_min} min` : '–'}</td>
                  <td>{r.nearest_facility}<div className="muted small">{r.nearest_tier} · {r.nearest_travel_min} min</div></td>
                  <td>{r.n_reachable}</td>
                  {ind.map(([k]) => <td key={k}>{r[k] ?? <span className="muted" title="No NFHS-5 match for this district">–</span>}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
