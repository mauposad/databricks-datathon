async function call(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { msg = (await res.json()).detail || msg } catch { /* not json */ }
    throw new Error(msg)
  }
  return res.json()
}

export const getServices = () => call('/api/services')
export const getPlaces = () => call('/api/places')
export const recommend = (q) => call('/api/recommend', { method: 'POST', body: JSON.stringify(q) })
export const chat = (message, history, max_km) =>
  call('/api/chat', { method: 'POST', body: JSON.stringify({ message, history, max_km }) })
