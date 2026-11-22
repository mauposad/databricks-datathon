// A fixed, made-up response in the RecommendResponse shape (app/backend/schema.py).
// Used for the "Example result" on the first screen and by the dev-only mock mode (VITE_MOCK=1).
// The facilities are fictional. Never present this as real data or as a recommendation.

const RULE = 'High: trust ≥ 70 with strong/moderate evidence · Medium: trust 45–69 · Low: trust < 45 · ' +
  'Probable: the procedure is not named, but a large or teaching hospital lists the specialty (call to confirm) · ' +
  'Unconfirmed: only weak evidence · Ranking puts High before Medium before Low/Probable, then orders by Quality within each group'

const LOC_CHECKS = [
  { key: 'pincode', label: 'PIN code matches the city', kind: 'main', status: 'pass' },
  { key: 'city_state', label: 'City is in the stated state', kind: 'main', status: 'pass' },
  { key: 'district_region', label: 'District matches the postal region', kind: 'main', status: 'pass' },
  { key: 'circle_division', label: 'Postal circle and division agree', kind: 'main', status: 'pass' },
  { key: 'coordinates', label: 'Map point is near the PIN code', kind: 'secondary', status: 'pass' },
]

const parts = (ev, ft, beds, sup, src, loc, coh, pens = []) => [
  { key: 'q_evidence', label: 'Evidence for this service', points: ev, max: 50 },
  { key: 'q_facility_type', label: 'Facility type', points: ft, max: 10 },
  { key: 'q_beds', label: 'Beds', points: beds, max: 10 },
  { key: 'q_support', label: 'Supporting services', points: sup, max: 10 },
  { key: 'q_sources', label: 'Independent sources', points: src, max: 8 },
  { key: 'q_location', label: 'Location certainty', points: loc, max: 6 },
  { key: 'q_coherence', label: 'Record coherence', points: coh, max: 6 },
  ...pens,
]

const base = {
  address: null, facebook: null, email: null, website: null, rejected_evidence: [], caveats: [], sources: [],
  match_pattern: 'dialys[ie]s|haemodialysis|hemodialysis|renal replacement', travel_budget_min: 120,
  ranking_band: 'reachable', points_below_best: null, support_found: [], is_nearest_alternative: false,
  is_better_farther: false, tradeoff_note: null, counterfactual_note: null, claims: [], call_to_confirm: null,
  identity_conflict: false, coherence: 90, verified_service: null, double_checks: [], pick_strength: null,
  pick_strength_note: null, tip_note: null, evidence: [],
}

const checks = (statuses) => [
  { key: 'machines', label: 'Dialysis machines', points: 10, max_points: 10, field: 'equipment', claim_type: 'direct', cited_text: '12 haemodialysis machines with RO water plant' },
  { key: 'nephrology', label: 'Nephrologist on staff', points: 10, max_points: 10, field: 'specialties', claim_type: 'direct', cited_text: 'Department of Nephrology with full-time nephrologist' },
  { key: 'icu', label: 'ICU on site', points: 0, max_points: 10, field: null, claim_type: null, cited_text: null },
  { key: 'hours', label: 'Open 24 hours', points: 0, max_points: 10, field: 'description', claim_type: 'hedged', cited_text: 'appears to run dialysis round the clock' },
].map((c, i) => ({ ...c, status: statuses[i] }))

export const SAMPLE_RESULTS = [
  {
    ...base, rank: 1, id: 'sample-1', name: 'Example Kidney and Dialysis Centre',
    address: '14 Sample Road, Civil Lines', city: 'Jaipur', district: 'Jaipur', state: 'Rajasthan', pincode: 302006,
    phone: '+91 141 000 0001', website: 'example.org', lat: 26.905, lon: 75.79, distance_km: 3.2, travel_min: 8,
    facility_type: 'hospital', operator_type: 'private',
    confidence: { label: 'High', score: 84, tier: 'strong', rule: RULE },
    score: { match: 82, trust: 84, distance: 96, mode: 'quality_first', parts: parts(44, 10, 7, 8, 6, 6, 5) },
    tags: ['Strong evidence', 'Hospital', 'Private', '60 beds', '8 doctors', '3 sources', '~8 min travel'],
    checks: checks(['found', 'found', 'unknown', 'found']),
    claims: [
      { text: '12 haemodialysis machines with RO water plant', field: 'equipment', claim_type: 'direct' },
      { text: 'Dialysis unit open for walk-in patients', field: 'procedure', claim_type: 'direct' },
      { text: 'appears to run dialysis round the clock', field: 'description', claim_type: 'hedged' },
    ],
    support_found: ['ICU', 'Blood bank'],
    pick_strength: 'Solid', pick_strength_note: 'Solid pick: it stays #1 under all 3 double-checks.',
    double_checks: [
      { kind: 'data', label: 'Only facilities with detailed evidence count', still_first: true },
      { kind: 'data', label: 'Facilities found on just one website are ignored', still_first: true },
      { kind: 'data', label: 'Fuzzy addresses move to their other recorded location', still_first: true },
      { kind: 'situation', label: 'You can travel twice as far', still_first: true },
      { kind: 'situation', label: 'Only the evidence matters, not hospital size', still_first: false, winner: 'Example Renal Clinic' },
    ],
    call_to_confirm: 'Ask if they take new patients without a referral.',
    sources: ['https://example.org/dialysis', 'https://directory.example.com/jaipur/kidney'],
    caveats: ['Opening hours are inferred from one description.'],
    location_validation: { status: 'scored', score: 5, label: 'verified_all', checks: LOC_CHECKS },
    why: 'Strong, direct evidence for dialysis in its own record, 8 minutes away.',
    how: 'Quality 82 = evidence 44/50 + readiness 25/30 + reliability 17/20 - 0 penalties; band reachable (8 ≤ 120 min)',
  },
  {
    ...base, rank: 2, id: 'sample-2', name: 'Example Government District Hospital',
    city: 'Jaipur', district: 'Jaipur', state: 'Rajasthan', pincode: 302004, phone: '+91 141 000 0002',
    lat: 26.88, lon: 75.82, distance_km: 6.8, travel_min: 16, facility_type: 'hospital', operator_type: 'public',
    confidence: { label: 'High', score: 76, tier: 'moderate', rule: RULE },
    score: { match: 74, trust: 76, distance: 91, mode: 'quality_first', parts: parts(36, 10, 10, 8, 4, 4, 4) },
    tags: ['Moderate evidence', 'Hospital', 'Public', '300 beds', '2 sources', '~16 min travel'],
    checks: checks(['found', 'unknown', 'found', 'unknown']),
    tip_note: 'Would be your best option if only government facilities count.',
    location_validation: { status: 'scored', score: 4, label: 'verified_strong',
      checks: LOC_CHECKS.map((c) => (c.key === 'coordinates' ? { ...c, status: 'partial', why: 'The map point is 4 km from the PIN code centre.' } : c)) },
    why: 'Named dialysis unit in a large public hospital.', how: 'Quality 74; band reachable (16 ≤ 120 min)',
  },
  {
    ...base, rank: 3, id: 'sample-3', name: 'Example Renal Clinic',
    city: 'Jaipur', district: 'Jaipur', state: 'Rajasthan', pincode: 302017, phone: '+91 141 000 0003',
    lat: 26.85, lon: 75.8, distance_km: 7.9, travel_min: 19, facility_type: 'clinic', operator_type: 'private',
    confidence: { label: 'Medium', score: 61, tier: 'strong', rule: RULE },
    score: { match: 68, trust: 61, distance: 89, mode: 'quality_first',
      parts: parts(46, 3, 2, 2, 2, 6, 4, [{ key: 'pen_facility_type', label: 'Not a hospital', points: -4 }]) },
    tags: ['Strong evidence', 'Clinic', 'Private', 'Single source', 'Not a hospital', '~19 min travel'],
    checks: checks(['found', 'found', 'contradicted', 'unknown']),
    location_validation: { status: 'scored', score: 5, label: 'verified_all', checks: LOC_CHECKS },
    why: 'Clear dialysis evidence, but a small clinic with one source.', how: 'Quality 68; band reachable',
  },
  {
    ...base, rank: 4, id: 'sample-4', name: 'Example Multispeciality Hospital, Sanganer',
    city: 'Jaipur', district: 'Jaipur', state: 'Rajasthan', pincode: 302029, phone: null,
    lat: 26.82, lon: 75.78, distance_km: 11.5, travel_min: 27, facility_type: 'hospital', operator_type: 'private',
    confidence: { label: 'Probable', score: 52, tier: 'probable', rule: RULE },
    score: { match: 63, trust: 52, distance: 84, mode: 'quality_first', parts: parts(22, 10, 8, 10, 6, 3, 4) },
    tags: ['Probable evidence', 'Hospital', 'Private', '120 beds', 'Location uncertain', '~27 min travel'],
    location_validation: { status: 'not_scored', checks: [] },
    why: 'Large hospital with nephrology, dialysis not named.', how: 'Quality 63; band reachable',
  },
  {
    ...base, rank: 5, id: 'sample-5', name: 'Example Charitable Trust Hospital',
    city: 'Chomu', district: 'Jaipur', state: 'Rajasthan', pincode: 303702, phone: '+91 142 000 0005',
    lat: 27.17, lon: 75.72, distance_km: 31, travel_min: 74, facility_type: 'hospital', operator_type: 'trust',
    confidence: { label: 'Unconfirmed', score: 38, tier: 'weak', rule: RULE }, ranking_band: 'unconfirmed',
    score: { match: 41, trust: 38, distance: 59, mode: 'quality_first', parts: parts(8, 10, 6, 4, 6, 4, 3) },
    tags: ['Weak evidence', 'Hospital', '~74 min travel', 'Has referral mentions'],
    rejected_evidence: ['patients needing dialysis are referred to SMS Hospital'],
    location_validation: { status: 'scored', score: 3, label: 'verified_partial',
      checks: LOC_CHECKS.map((c) => (c.key === 'district_region' ? { ...c, status: 'fail', why: 'The record names a district the PIN code is not in.' } : c)) },
    why: 'Only a passing mention.', how: 'Quality 41; band unconfirmed',
  },
]

export const SAMPLE_RESPONSE = {
  query: { service: 'dialysis', place: 'Jaipur', max_km: 75, top_n: 5, public_only: false },
  service_label: 'Dialysis', service_key: 'dialysis',
  origin: { lat: 26.9124, lon: 75.7873, label: 'Jaipur', matched_as: 'city' },
  results: SAMPLE_RESULTS, n_candidates: 41, adapter: 'sample',
  method: 'Quality (0–100) = evidence for this service in the record (up to 50) + readiness (up to 30) + record reliability (up to 20) minus penalties.',
  notes: [], ranking_rule: '', travel_assumption: 'Travel time = km × 1.4 ÷ 35 km/h.', search_note: null,
  safety_note: null, n_excluded_unverified_location: 2,
}

export const SAMPLE_SERVICES = [
  { key: 'dialysis', label: 'Dialysis', aliases: [] },
  { key: 'emergency_csection', label: 'Emergency C-section', aliases: [] },
  { key: 'nicu', label: 'NICU', aliases: [] },
  { key: 'trauma', label: 'Trauma', aliases: [] },
  { key: 'cardiac_surgery', label: 'Cardiac surgery', aliases: [] },
  { key: 'mri', label: 'MRI', aliases: [] },
]
export const SAMPLE_PLACES = ['Jaipur', 'Jaipur Rural', 'Jaisalmer', 'Patna', 'Lucknow', '226001', '302006', 'Pune', 'Bengaluru']
