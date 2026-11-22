import { useState } from 'react'
import Icon from './Icon.jsx'
import { Button, Combobox, Select, Slider, Switch } from './ui/index.js'

const EXAMPLES = [
  { service: 'dialysis', place: 'Jaipur' },
  { service: 'emergency_csection', place: '226001' },
  { service: 'nicu', place: 'Patna' },
]

export default function SearchForm({ services, places, loading, onSearch }) {
  const [service, setService] = useState('')
  const [place, setPlace] = useState('')
  const [maxKm, setMaxKm] = useState(75)
  const [publicOnly, setPublicOnly] = useState(false)

  function submit(e) {
    e?.preventDefault()
    if (service && place.trim()) onSearch({ service, place: place.trim(), max_km: maxKm, top_n: 5, public_only: publicOnly })
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
      <div className="form-grid">
        <div className="form-field">
          <Select id="sf-service" value={service} onValueChange={setService} label="Care needed"
                  placeholder="Choose a service" options={services.map((s) => ({ value: s.key, label: s.label }))} />
        </div>

        <div className="form-field">
          {/* The placeholder says what goes here; screen readers get the name from aria-label. */}
          <Combobox value={place} onChange={setPlace} options={places} label="Your location"
                    placeholder="PIN code, city, village or district" onEnter={submit}
                    trailing={
                      <button type="button" className="icon-btn" onClick={useMyLocation} aria-label="Use my location">
                        <Icon name="locate" />
                      </button>
                    } />
        </div>
      </div>

      <div className="form-grid">
        <div className="form-field">
          <span className="field-label" id="sf-km">Search radius <span className="num value">{maxKm} km</span></span>
          <Slider value={maxKm} onValueChange={setMaxKm} min={10} max={300} step={5} label="Search radius in km" />
        </div>
        <Switch checked={publicOnly} onCheckedChange={setPublicOnly} label="Government facilities only" />
      </div>

      <Button type="submit" variant="primary" size="lg" icon="search" loading={loading}
              disabled={loading || !service || !place.trim()}>
        Find facilities
      </Button>

      <div className="examples">
        <span className="muted">Try</span>
        {EXAMPLES.map((ex) => (
          <Button key={ex.service + ex.place} size="sm" variant="secondary"
                  onClick={() => { setService(ex.service); setPlace(ex.place); onSearch({ ...ex, max_km: maxKm, top_n: 5, public_only: publicOnly }) }}>
            {labelFor(ex.service)} · {ex.place}
          </Button>
        ))}
      </div>
    </form>
  )
}
