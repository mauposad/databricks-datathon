import { useEffect, useState } from 'react'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { usePresets } from './motion/presets.js'
import { StaggerItem } from './motion/Stagger.jsx'
import * as api from './api.js'
import SearchForm from './components/SearchForm.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import VoicePanel from './components/VoicePanel.jsx'
import ResultHero from './components/ResultHero.jsx'
import ResultRow from './components/ResultRow.jsx'
import ResultsMap from './components/ResultsMap.jsx'
import HowWeScore from './components/HowWeScore.jsx'
import Planner from './components/Planner.jsx'
import Icon from './components/Icon.jsx'
import ResultsSkeleton from './components/ResultsSkeleton.jsx'
import { Button, Tabs } from './components/ui/index.js'
import { saveVerification } from './components/result/shared.js'
import { SAMPLE_RESULTS } from './fixtures/sampleRecommendation.js'

const MODES = [
  { key: 'form', label: 'Search' },
  { key: 'chat', label: 'Chat' },
  { key: 'voice', label: 'Voice' },
]
const VIEWS = [
  { key: 'find', label: 'Find care' },
  { key: 'planner', label: 'District planner' },
]
const MAX_KM = 300
const DEMO = { service: 'dialysis', place: 'Jaipur', max_km: 75, top_n: 5, public_only: false }
// Example searches shown as pins before the first search (the same three as the form's "Try" buttons).
const EXAMPLE_PINS = [
  { label: 'Dialysis · Jaipur', lat: 26.9124, lon: 75.7873, dir: 'left', q: DEMO },
  { label: 'Emergency C-section · 226001', lat: 26.8467, lon: 80.9462, dir: 'top', q: { ...DEMO, service: 'emergency_csection', place: '226001' } },
  { label: 'NICU · Patna', lat: 25.5941, lon: 85.1376, dir: 'right', q: { ...DEMO, service: 'nicu', place: 'Patna' } },
]

// "Dialysis" -> "dialysis", but keep "NICU" and "MRI" as they are.
const lowerFirst = (s) => (s && s.length > 1 && s[1] === s[1].toLowerCase() ? s[0].toLowerCase() + s.slice(1) : s)

const placeName = (result) => (result.origin?.label || result.query.place).replace(/\s*\(.*\)\s*$/, '')

function headline(result, n) {
  const what = lowerFirst(result.service_label || result.query.service)
  // The backend annotates the label ("Jaipur (city, from 165 facilities)"); the headline keeps the place only.
  const where = placeName(result)
  const km = result.query.max_km
  if (n === 0) return `No ${what} options within ${km} km of ${where}`
  return `${n} ${what} option${n === 1 ? '' : 's'} within ${km} km of ${where}`
}

export default function App() {
  const [view, setView] = useState('find')        // find | planner
  const [mode, setMode] = useState('form')
  const [services, setServices] = useState([])
  const [places, setPlaces] = useState([])
  const [servicesLoading, setServicesLoading] = useState(true)
  const [placesLoading, setPlacesLoading] = useState(true)
  const [result, setResult] = useState(null)      // RecommendResponse
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)        // { text, detail, retry }
  const [selected, setSelected] = useState(null)  // facility id
  const [expandSignal, setExpandSignal] = useState(null)  // { id, n }: open a row when its map pin is clicked
  const [mapOpen, setMapOpen] = useState(true)    // narrow screens only: the map is a collapsible panel
  const p = usePresets()

  function loadServices() {
    setServicesLoading(true); setError(null)
    api.getServices().then(setServices)
      .catch((e) => setError({ text: 'We could not load the list of care types.', detail: e.message, retry: loadServices }))
      .finally(() => setServicesLoading(false))
  }
  useEffect(() => {
    api.warmup()
    loadServices()
    api.getPlaces().then(setPlaces).catch(() => {}).finally(() => setPlacesLoading(false))
  }, [])

  async function runSearch(q) {
    setLoading(true); setError(null); setSelected(null)
    try { setResult(await api.recommend(q)) }
    catch (e) { setError({ text: 'We could not reach the search service. Try again.', detail: e.message, retry: () => runSearch(q) }) }
    finally { setLoading(false) }
  }

  // After a reviewer confirms / rejects something, re-run the same search so the overlay shows.
  // The cards stay on screen, dimmed, while it runs.
  async function refresh() {
    if (!result?.query) return
    setRefreshing(true)
    try { const r = await api.recommend(result.query); setResult({ ...r, chat: result.chat }) }
    catch (e) { setError({ text: 'Saved, but we could not refresh the results.', detail: e.message, retry: refresh }) }
    finally { setRefreshing(false) }
  }

  // Chat and voice hand back a RecommendResponse when they have one.
  function showResult(rec) { if (rec) { setResult(rec); setSelected(null) } }

  const results = result?.results || []
  const nMain = results.filter((r) => !r.is_nearest_alternative).length
  const verifyFor = (rec) => (result?.service_key
    ? (checkKey, status, label, note) => saveVerification({ facilityId: rec.id, serviceKey: result.service_key, checkKey, status, label, note, onVerified: refresh })
    : null)
  const widerKm = result && Math.min(MAX_KM, result.query.max_km * 2)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Icon name="logo" size="md" className="logo" />
          <h1>Care Finder</h1>
        </div>
        <Tabs items={VIEWS} value={view} onChange={setView} label="View" id="view" className="view-switch" />
      </header>

      {view === 'planner' ? <main className="planner-layout"><Planner /></main> : (
      <main className="layout">
        <div className="map-toggle">
          <Button variant="ghost" size="sm" icon="pin" aria-expanded={mapOpen} aria-controls="map-panel" onClick={() => setMapOpen(!mapOpen)}>
            {mapOpen ? 'Hide map' : 'Show map'}
          </Button>
        </div>
        <section className="left">
          <div className="panel input-panel">
            <Tabs items={MODES} value={mode} onChange={setMode} label="Input mode" id="input" className="input-tabs" />
            {/* M16: the old panel leaves while the new one enters */}
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div key={mode} {...p.fade}>
                {mode === 'form' && <SearchForm services={services} places={places} servicesLoading={servicesLoading}
                                                placesLoading={placesLoading} loading={loading} onSearch={runSearch} />}
                {mode === 'chat' && <ChatPanel onResult={showResult} />}
                {mode === 'voice' && <VoicePanel onResult={showResult} />}
              </motion.div>
            </AnimatePresence>
          </div>

          {error && (
            <div className="alert error" role="alert">
              <Icon name="alert" />
              <div className="alert-body">
                <p><b>{error.text}</b></p>
                {error.detail && <p className="small">{error.detail}</p>}
              </div>
              {error.retry && <Button size="sm" icon="retry" onClick={error.retry}>Try again</Button>}
            </div>
          )}

          {result?.safety_note && (
            <div className="alert safety" role="alert">
              <Icon name="warning" />
              <div><b>Emergency?</b> {result.safety_note}</div>
            </div>
          )}

          <AnimatePresence mode="popLayout" initial={false}>
          {result && !loading && (
            <motion.div key={headline(result, nMain)} className="summary" {...p.enter}>
              <h2>{headline(result, nMain)}</h2>
              <p className="muted num">
                {result.origin?.label && result.origin.label !== placeName(result) && <>Searched from {result.origin.label} · </>}
                {result.n_candidates} facilities checked
                {result.query.public_only ? ' · government facilities only' : ''}
              </p>
              {result.chat && (
                <p className="muted small">
                  Understood {result.chat.parsed_by === 'llm' ? 'by the AI model' : 'by keyword matching'};
                  {' '}reply {result.chat.reply_source === 'llm' ? 'worded by the AI model and checked against these results' : 'from a fixed template'}.
                </p>
              )}
              <div className="summary-actions">
                {results.length === 0 && result.query.max_km < MAX_KM && (
                  <Button onClick={() => runSearch({ ...result.query, max_km: widerKm })}>Search up to {widerKm} km</Button>
                )}
                <HowWeScore method={result.method} rule={results[0]?.confidence.rule} />
              </div>
            </motion.div>
          )}
          </AnimatePresence>
          {result?.notes?.map((n) => <div key={n} className="alert note">{n}</div>)}

          {/* M16: skeleton, results and the example overlap as they swap. M3: cards stagger 30ms. */}
          <AnimatePresence mode="popLayout" initial={false}>
          {loading && <motion.div key="loading" {...p.fade}><ResultsSkeleton /></motion.div>}

          {!loading && results.length > 0 && (
            <motion.div key={`results-${result.query.service}-${result.query.place}-${result.query.max_km}`} {...p.fade}
                        className={`cards ${refreshing ? 'is-refreshing' : ''}`} aria-busy={refreshing || undefined}>
              {refreshing && <span className="progress-line" aria-hidden />}
              <LayoutGroup>
                <StaggerItem index={0}>
                  <ResultHero key={results[0].id} rec={results[0]} top={results[0]} selected={selected === results[0].id}
                              onSelect={() => setSelected(results[0].id)} verify={verifyFor(results[0])} />
                </StaggerItem>
                {results.length > 1 && (
                  <div className="rows">
                    {results.slice(1).map((r, i) => (
                      <StaggerItem key={r.id} index={i + 1} layout="position" transition={p.move}>
                        <ResultRow rec={r} top={results[0]} selected={selected === r.id}
                                   onSelect={() => setSelected(r.id)} verify={verifyFor(r)} expandSignal={expandSignal} />
                      </StaggerItem>
                    ))}
                  </div>
                )}
              </LayoutGroup>
            </motion.div>
          )}

          {!result && !loading && (
            <motion.section key="example" className="example" aria-label="Example result" {...p.fade}>
              <div className="example-head">
                <p><b>Example result</b> <span className="muted">Made-up data. It shows what a search returns.</span></p>
                <Button size="sm" icon="search" onClick={() => runSearch(DEMO)}>Try an example</Button>
              </div>
              <div className="example-card" inert="">
                <ResultHero rec={SAMPLE_RESULTS[0]} top={SAMPLE_RESULTS[0]} example onSelect={() => {}} />
              </div>
            </motion.section>
          )}
          </AnimatePresence>
        </section>

        <section id="map-panel" className={`right ${mapOpen ? '' : 'collapsed'}`} aria-label="Map">
          <ResultsMap result={result} selected={selected}
                      onSelect={(id) => { setSelected(id); setExpandSignal((s) => ({ id, n: (s?.n || 0) + 1 })) }}
                      examples={EXAMPLE_PINS.map((e) => ({ ...e, onPick: () => runSearch(e.q) }))} />
        </section>
      </main>
      )}
    </div>
  )
}
