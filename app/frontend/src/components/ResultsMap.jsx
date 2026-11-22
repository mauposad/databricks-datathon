import { useEffect } from 'react'
import { Circle, MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'

const INDIA = [22.5, 79]

// Map colours live in styles/tokens.css; read them here so no colour is typed in JS.
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

const numberIcon = (n, active) => L.divIcon({
  className: '',
  html: `<div class="pin ${active ? 'active' : ''}">${n}</div>`,
  iconSize: [30, 30],
  iconAnchor: [15, 15],
})
const originIcon = L.divIcon({ className: '', html: '<div class="origin-pin"></div>', iconSize: [18, 18], iconAnchor: [9, 9] })

function FitBounds({ result }) {
  const map = useMap()
  useEffect(() => {
    if (!result) return
    const pts = result.results.filter((r) => r.lat != null).map((r) => [r.lat, r.lon])
    if (result.origin?.lat != null) pts.push([result.origin.lat, result.origin.lon])
    if (pts.length === 1) map.setView(pts[0], 11)
    else if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40], maxZoom: 13 })
  }, [result, map])
  return null
}

function FlyTo({ result, selected }) {
  const map = useMap()
  useEffect(() => {
    const r = result?.results.find((x) => x.id === selected)
    if (r?.lat != null) map.flyTo([r.lat, r.lon], Math.max(map.getZoom(), 12), { duration: 0.6 })
  }, [selected, result, map])
  return null
}

export default function ResultsMap({ result, selected, onSelect }) {
  const origin = result?.origin
  return (
    <div className="map-wrap">
      <MapContainer center={INDIA} zoom={5} className="map" scrollWheelZoom>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                   url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {origin?.lat != null && (
          <>
            <Circle center={[origin.lat, origin.lon]} radius={result.query.max_km * 1000}
                    pathOptions={{ color: cssVar('--map-radius'), weight: 1, fillOpacity: 0.04 }} />
            <Marker position={[origin.lat, origin.lon]} icon={originIcon}>
              <Popup>Searched from: {origin.label}</Popup>
            </Marker>
          </>
        )}
        {result?.results.filter((r) => r.lat != null).map((r) => (
          <Marker key={r.id} position={[r.lat, r.lon]} icon={numberIcon(r.rank, r.id === selected)}
                  eventHandlers={{ click: () => onSelect(r.id) }} zIndexOffset={r.id === selected ? 1000 : 0}>
            <Popup>
              <strong>{r.rank}. {r.name}</strong><br />
              <span className="num">{r.travel_min != null ? `~${r.travel_min} min · ` : ''}{r.distance_km} km</span><br />
              <span className="muted">{r.confidence.label === 'Probable' ? 'Likely · call to confirm' : `${r.confidence.label} confidence`}</span>
            </Popup>
          </Marker>
        ))}
        <FitBounds result={result} />
        <FlyTo result={result} selected={selected} />
      </MapContainer>
      {result && (
        <div className="map-legend num">
          <span><span className="origin-pin inline" /> You searched here</span>
          <span><span className="pin inline">1</span> Ranked option</span>
          <span>Circle: {result.query.max_km} km</span>
        </div>
      )}
    </div>
  )
}
