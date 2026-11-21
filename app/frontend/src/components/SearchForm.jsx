import { useState } from 'react'

const EXAMPLES = [
  { service: 'dialysis', place: 'Jaipur' },
  { service: 'emergency_csection', place: '226001' },
  { service: 'nicu', place: 'Patna' },
]

export default function SearchForm({ services, places, loading, onSearch }) {
  const [service, setService] = useState('')
  const [place, setPlace] = useState('')
  const [maxKm, setMaxKm] = useState(75)

  function submit(e) {
    e?.preventDefault()
    if (service && place.trim()) onSearch({ service, place: place.trim(), max_km: maxKm, top_n: 5 })
  }

  function useMyLocation() {
    navigator.geolocation?.getCurrentPosition(
      (p) => setPlace(`${p.coords.latitude.toFixed(4)},${p.coords.longitude.toFixed(4)}`),
      () => alert('Location permission was denied.'),
    )
  }

  const labelFor = (key) => services.find((s) => s.key === key)?.label || key

  return (
    <form className="search-form" onSubmit={submit}>
      <label>
        <span>Service</span>
        <select value={service} onChange={(e) => setService(e.target.value)} required>
          <option value="">Choose a service…</option>
          {services.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
      </label>

      <label>
        <span>Location</span>
        <div className="row">
          <input list="places" value={place} onChange={(e) => setPlace(e.target.value)}
                 placeholder="PIN code, city, district, or lat,lon" required />
          <button type="button" className="ghost" onClick={useMyLocation} title="Use my location">📍</button>
        </div>
        <datalist id="places">{places.map((p) => <option key={p} value={p} />)}</datalist>
      </label>

      <label>
        <span>Search radius: <strong>{maxKm} km</strong></span>
        <input type="range" min="10" max="300" step="5" value={maxKm} onChange={(e) => setMaxKm(+e.target.value)} />
      </label>

      <button className="primary" disabled={loading || !service || !place.trim()}>
        {loading ? 'Searching…' : 'Find facilities'}
      </button>

      <div className="examples">
        <span className="muted">Try:</span>
        {EXAMPLES.map((ex) => (
          <button type="button" key={ex.service + ex.place} className="chip"
                  onClick={() => { setService(ex.service); setPlace(ex.place); onSearch({ ...ex, max_km: maxKm, top_n: 5 }) }}>
            {labelFor(ex.service)} · {ex.place}
          </button>
        ))}
      </div>
    </form>
  )
}
