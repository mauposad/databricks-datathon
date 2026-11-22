import { useEffect, useState } from 'react'
import { Circle, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'

const INDIA = [22.5, 79]

// Map colours live in styles/tokens.css; read them here so no colour is typed in JS.
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

const numberIcon = (n, active) => L.divIcon({
  className: '',
  html: `<div class="pin ${active ? 'active' : ''}">${n}</div>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
})
const originIcon = L.divIcon({ className: '', html: '<div class="origin-pin"></div>', iconSize: [16, 16], iconAnchor: [8, 8] })
const exampleIcon = L.divIcon({ className: '', html: '<div class="example-pin"></div>', iconSize: [14, 14], iconAnchor: [7, 7] })

function FitBounds({ result }) {
  const map = useMap()
  useEffect(() => {
    if (!result) { map.setView(INDIA, 5); return }
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

// examples: [{ label, lat, lon, onPick }] shown before the first search so the map is never blank.
export default function ResultsMap({ result, selected, onSelect, examples = [] }) {
  const origin = result?.origin
  const [tilesReady, setTilesReady] = useState(false)
  return (
    <div className="map-wrap" aria-busy={!tilesReady || undefined}>
      <MapContainer center={INDIA} zoom={5} className="map" scrollWheelZoom>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                   url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                   eventHandlers={{ load: () => setTilesReady(true) }} />
        {!result && examples.map((ex) => (
          <Marker key={ex.label} position={[ex.lat, ex.lon]} icon={exampleIcon} eventHandlers={{ click: ex.onPick }}
                  keyboard title={`Try ${ex.label}`}>
            <Tooltip direction={ex.dir || 'top'} offset={{ top: [0, -8], left: [-8, 0], right: [8, 0] }[ex.dir || 'top']} permanent>{ex.label}</Tooltip>
          </Marker>
        ))}
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
      {!tilesReady && <div className="map-loading skeleton" aria-hidden />}
      {result ? (
        <div className="map-legend num">
          <span><span className="origin-pin inline" /> You searched here</span>
          <span><span className="pin inline">1</span> Ranked option</span>
          <span>Circle: {result.query.max_km} km</span>
        </div>
      ) : examples.length > 0 && (
        <div className="map-legend"><span><span className="example-pin inline" /> Example searches. Select one to run it.</span></div>
      )}
    </div>
  )
}
