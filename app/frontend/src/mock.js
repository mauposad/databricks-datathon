// Dev-only fake backend. Loaded by api.js when VITE_MOCK is set; never part of the production build.
//   VITE_MOCK=1      normal answers after a short delay
//   VITE_MOCK=slow   same, 4 s delay (to look at loading states)
//   VITE_MOCK=empty  searches return no results
//   VITE_MOCK=fail   every search fails
import { SAMPLE_PLACES, SAMPLE_RESPONSE, SAMPLE_SERVICES } from './fixtures/sampleRecommendation.js'

const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const verified = {}

const DISTRICTS = ['Barmer', 'Jaisalmer', 'Bikaner', 'Jodhpur', 'Nagaur', 'Churu', 'Sikar', 'Jaipur', 'Ajmer', 'Kota', 'Udaipur', 'Alwar']
const plannerRows = (service) => DISTRICTS.map((d, i) => ({
  district: d, state: 'Rajasthan', travel_budget_min: 120, quality_within_budget: i > 3,
  quality_facility: i === 0 ? null : `Example Hospital ${d}`, quality_facility_quality: 70 + (i % 5) * 4,
  quality_km: 180 - i * 14, quality_travel_min: i === 0 ? null : Math.round((180 - i * 14) * 1.4 / 35 * 60),
  nearest_facility: `Example Clinic ${d}`, nearest_tier: i % 3 ? 'moderate' : 'weak', nearest_travel_min: 30 + i * 3,
  n_reachable: i, women_high_blood_sugar_pct: 6.1 + i * 0.4, men_high_blood_sugar_pct: i % 4 ? 7.2 + i * 0.3 : null,
  women_high_bp_pct: 12.4 + i, institutional_birth_pct: 82 + i, institutional_birth_public_pct: 60 + i,
  csection_rate_pct: 8 + i * 0.5, women_anaemic_pct: 50 + i, health_insurance_pct: 70 - i, service,
}))

export async function handle(path, opts, mode) {
  await wait(mode === 'slow' ? 4000 : 700)
  const body = opts.body ? JSON.parse(opts.body) : {}
  window.__mockCalls = [...(window.__mockCalls || []), { path, body }]  // read by UI regression scripts
  if (path === '/api/services') return SAMPLE_SERVICES
  if (path === '/api/places') return SAMPLE_PLACES
  if (path.startsWith('/api/planner')) {
    const service = new URL(path, 'http://x').searchParams.get('service')
    return plannerRows(service)
  }
  if (path === '/api/verify') { verified[body.facility_id] = body.status; return { ok: true } }
  if (mode === 'fail') throw new Error('503 Service Unavailable')
  const respond = (q) => {
    const svc = SAMPLE_SERVICES.find((s) => s.key === q.service)
    const results = mode === 'empty' ? [] : SAMPLE_RESPONSE.results.map((r) => (
      verified[r.id] ? { ...r, verified_service: verified[r.id], confidence: verified[r.id] === 'confirmed' ? { ...r.confidence, label: 'High' } : r.confidence } : r))
    return { ...SAMPLE_RESPONSE, query: { ...SAMPLE_RESPONSE.query, ...q }, service_key: q.service,
             service_label: svc?.label || q.service, origin: { ...SAMPLE_RESPONSE.origin, label: q.place }, results }
  }
  if (path === '/api/recommend') return respond(body)
  if (path === '/api/chat') {
    const q = { service: 'dialysis', place: 'Jaipur', max_km: body.max_km || 75, top_n: 5, public_only: false }
    return { reply: 'I found 5 dialysis options within 75 km of Jaipur. The best one is Example Kidney and Dialysis Centre, about 8 minutes away. Its record names 12 haemodialysis machines and a nephrology department. It stays first under all three double-checks. Before you go, call and ask if they take new patients without a referral. If they cannot help, the next option is a large public hospital about 16 minutes away.',
             query: q, recommendations: respond(q), parsed_by: 'keywords', reply_source: 'template' }
  }
  throw new Error(`mock: no route for ${path}`)
}
