import { useState } from 'react'
import CarePicker from './CarePicker.jsx'
import Icon from './Icon.jsx'
import { Button, Combobox, Select, Slider, Switch } from './ui/index.js'

// group: a broad care group; service: optional specific service (else the group's default)
const EXAMPLES = [
  { group: 'maternity', place: '226001' },
  { group: 'kidney', place: 'Jaipur' },
  { group: 'child', service: 'nicu', place: 'Patna' },
]
const LEGACY_EXAMPLES = [
  { service: 'dialysis', place: 'Jaipur' },
  { service: 'emergency_csection', place: '226001' },
  { service: 'nicu', place: 'Patna' },
]

export default function SearchForm({ services, groups = [], places, servicesLoading, placesLoading, loading, onSearch }) {
  const useGroups = groups.length > 0
  const [care, setCare] = useState(null)          // { group, service } (broad groups)
  const [legacyService, setLegacyService] = useState('')
  const [place, setPlace] = useState('')
  const [maxKm, setMaxKm] = useState(75)
  const [publicOnly, setPublicOnly] = useState(false)
  const [locating, setLocating] = useState(false)
  const [placeError, setPlaceError] = useState('')

  const group = useGroups ? groups.find((g) => g.key === care?.group) : null
  // the one service key sent to the search: the chosen one, or the group's default (one find_care call, as before)
  const service = useGroups ? (care?.service || group?.default_service || '') : legacyService
  const needsRefine = !!group && !service

  function submit(e) {
    e?.preventDefault()
    if (loading) return
    if (service && place.trim()) onSearch({ service, place: place.trim(), max_km: maxKm, top_n: 5, public_only: publicOnly })
  }

  function useMyLocation() {
    setPlaceError('')
    if (!navigator.geolocation) { setPlaceError('This browser cannot share your location. Type a PIN code or a city.'); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); setPlace(`${p.coords.latitude.toFixed(4)},${p.coords.longitude.toFixed(4)}`) },
      (err) => {
        setLocating(false)
        setPlaceError(err.code === 1
          ? 'Location access is blocked. Allow it in the browser, or type a PIN code or a city.'
          : 'We could not get your location. Type a PIN code or a city.')
      },
      { timeout: 15000 },
    )
  }

  const labelFor = (key) => services.find((s) => s.key === key)?.label || key

  return (
    <form className="search-form" onSubmit={submit}>
      <div className="form-grid">
        <div className="form-field">
          {useGroups ? (
            <CarePicker id="sf-service" groups={groups} services={services} value={care} onChange={setCare} loading={servicesLoading} />
          ) : (
            <Select id="sf-service" value={legacyService} onValueChange={setLegacyService} label="Care needed"
                    placeholder="Choose a service" loading={servicesLoading} loadingText="Loading care types" options={services.map((s) => ({ value: s.key, label: s.label }))} />
          )}
        </div>

        <div className="form-field">
          {/* The placeholder says what goes here; screen readers get the name from aria-label. */}
          <Combobox value={place} onChange={(v) => { setPlace(v); setPlaceError('') }} options={places} label="Your location"
                    placeholder="PIN code, city, village or district" onEnter={submit} loading={placesLoading && !places.length}
                    invalid={!!placeError} describedBy={placeError ? 'sf-place-error' : undefined}
                    trailing={
                      <button type="button" className="icon-btn" onClick={useMyLocation} disabled={locating}
                              aria-label={locating ? 'Finding your location' : 'Use my location'}>
                        <Icon name={locating ? 'spinner' : 'locate'} className={locating ? 'spin' : ''} />
                      </button>
                    } />
          {placeError && <p id="sf-place-error" className="field-error" role="alert"><Icon name="alert" /><span>{placeError}</span></p>}
        </div>
      </div>

      {group && group.services.length > 1 && (
        <div className="refine" role="radiogroup" aria-labelledby="sf-refine">
          <span className="field-label" id="sf-refine">{needsRefine ? group.refine_question : 'Specifically'}</span>
          <div className="refine-chips">
            {group.services.map((k) => {
              const on = service === k
              return (
                <button key={k} type="button" role="radio" aria-checked={on} className={`chip ${on ? 'on' : ''}`}
                        onClick={() => setCare({ group: group.key, service: k })}>
                  {on && <Icon name="check" />}{labelFor(k)}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="form-grid">
        <div className="form-field">
          <span className="field-label" id="sf-km">Search radius <span className="num value">{maxKm} km</span></span>
          <Slider value={maxKm} onValueChange={setMaxKm} min={10} max={300} step={5} label="Search radius in km" />
        </div>
        <Switch checked={publicOnly} onCheckedChange={setPublicOnly} label="Government facilities only" />
      </div>

      {/* Not disabled while loading: a disabled button drops keyboard focus to <body>. submit() ignores repeats. */}
      <Button type="submit" variant="primary" size="lg" icon="search" loading={loading}
              disabled={!service || !place.trim()}>
        Find facilities
      </Button>

      <div className="examples">
        <span className="muted">Try</span>
        {useGroups ? EXAMPLES.filter((ex) => groups.some((g) => g.key === ex.group)).map((ex) => {
          const g = groups.find((x) => x.key === ex.group)
          const svc = ex.service || g.default_service
          return (
            <Button key={ex.group + ex.place} size="sm" variant="secondary" disabled={!svc}
                    onClick={() => { setCare({ group: ex.group, service: ex.service || null }); setPlace(ex.place); onSearch({ service: svc, place: ex.place, max_km: maxKm, top_n: 5, public_only: publicOnly }) }}>
              {ex.service ? labelFor(ex.service) : g.label} · {ex.place}
            </Button>
          )
        }) : LEGACY_EXAMPLES.map((ex) => (
          <Button key={ex.service + ex.place} size="sm" variant="secondary"
                  onClick={() => { setLegacyService(ex.service); setPlace(ex.place); onSearch({ ...ex, max_km: maxKm, top_n: 5, public_only: publicOnly }) }}>
            {labelFor(ex.service)} · {ex.place}
          </Button>
        ))}
      </div>
    </form>
  )
}
