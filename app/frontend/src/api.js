// Dev only: VITE_MOCK=1 (or empty, fail, slow) answers from src/mock.js instead of the backend.
// `import.meta.env.DEV` is false in `npm run build`, so the mock path is dropped from the production bundle.
const MOCK = import.meta.env.DEV && import.meta.env.VITE_MOCK
let mock

async function call(path, opts = {}) {
  if (MOCK) { mock ??= await import('./mock.js'); return mock.handle(path, opts, MOCK) }
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { msg = (await res.json()).detail || msg } catch { /* not json */ }
    throw new Error(msg)
  }
  return res.json()
}

// Fire-and-forget: asks the backend to start the SQL warehouse while the user is still typing.
export const warmup = () => call('/api/warmup', { method: 'POST' }).catch(() => {})
export const getServices = () => call('/api/services')
// Broad care groups; [] when the backend predates them, and the form falls back to the plain service list.
export const getServiceGroups = () => call('/api/service-groups').catch(() => [])
export const getPlaces = () => call('/api/places')
export const recommend = (q) => call('/api/recommend', { method: 'POST', body: JSON.stringify(q) })
export const chat = (message, history, max_km) =>
  call('/api/chat', { method: 'POST', body: JSON.stringify({ message, history, max_km }) })
export const verify = (body) => call('/api/verify', { method: 'POST', body: JSON.stringify(body) })
export const planner = (service, state) =>
  call(`/api/planner?service=${encodeURIComponent(service)}${state ? `&state=${encodeURIComponent(state)}` : ''}`)
