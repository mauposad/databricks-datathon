import { useEffect, useState } from 'react'
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
import { Button, Skeleton, Tabs } from './components/ui/index.js'
import { recordVerification } from './components/result/shared.js'

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

// "Dialysis" -> "dialysis", but keep "NICU" and "MRI" as they are.
const lowerFirst = (s) => (s && s.length > 1 && s[1] === s[1].toLowerCase() ? s[0].toLowerCase() + s.slice(1) : s)

function headline(result, n) {
  const what = lowerFirst(result.service_label || result.query.service)
  const where = result.origin?.label || result.query.place
  const km = result.query.max_km
  if (n === 0) return `No ${what} options within ${km} km of ${where}`
  return `${n} ${what} option${n === 1 ? '' : 's'} within ${km} km of ${where}`
}

export default function App() {
  const [view, setView] = useState('find')        // find | planner
  const [mode, setMode] = useState('form')
  const [services, setServices] = useState([])
  const [places, setPlaces] = useState([])
  const [result, setResult] = useState(null)      // RecommendResponse
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)  // facility id

  useEffect(() => {
    api.getServices().then(setServices).catch((e) => setError(`Could not load services: ${e.message}`))
    api.getPlaces().then(setPlaces).catch(() => {})
  }, [])

  async function runSearch(q) {
    setLoading(true); setError(''); setSelected(null)
    try { setResult(await api.recommend(q)) } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  // After a reviewer confirms / rejects something, re-run the same search so the overlay shows.
  async function refresh() {
    if (!result?.query) return
    try { const r = await api.recommend(result.query); setResult({ ...r, chat: result.chat }) } catch (e) { setError(e.message) }
  }

  // Chat and voice hand back a RecommendResponse when they have one.
  function showResult(rec) { if (rec) { setResult(rec); setSelected(null) } }

  const results = result?.results || []
  const nMain = results.filter((r) => !r.is_nearest_alternative).length
  const verifyFor = (rec) => (result?.service_key
    ? (checkKey, status, label) => recordVerification({ facilityId: rec.id, serviceKey: result.service_key, checkKey, status, label, onVerified: refresh })
    : null)
  const widerKm = result && Math.min(MAX_KM, result.query.max_km * 2)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Icon name="logo" size="md" className="logo" />
          <h1>Care Finder</h1>
        </div>
        <Tabs items={VIEWS} value={view} onChange={setView} label="View" className="view-switch" />
      </header>

      {view === 'planner' ? <main className="planner-layout"><Planner /></main> : (
      <main className="layout">
        <section className="left">
          <div className="panel input-panel">
            <Tabs items={MODES} value={mode} onChange={setMode} label="Input mode" className="input-tabs" />
            {mode === 'form' && <SearchForm services={services} places={places} loading={loading} onSearch={runSearch} />}
            {mode === 'chat' && <ChatPanel onResult={showResult} />}
            {mode === 'voice' && <VoicePanel onResult={showResult} />}
          </div>

          {error && <div className="alert error" role="alert"><Icon name="alert" /><span>{error}</span></div>}

          {result?.safety_note && (
            <div className="alert safety" role="alert">
              <Icon name="warning" />
              <div><b>Emergency?</b> {result.safety_note}</div>
            </div>
          )}

          {result && !loading && (
            <div className="summary">
              <h2>{headline(result, nMain)}</h2>
              <p className="muted num">
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
            </div>
          )}
          {result?.notes?.map((n) => <div key={n} className="alert note">{n}</div>)}

          {loading && <div className="skeletons">{[0, 1, 2].map((i) => <Skeleton key={i} height={i ? 64 : 280} radius="var(--r-lg)" />)}</div>}

          {!loading && results.length > 0 && (
            <div className="cards">
              <ResultHero rec={results[0]} top={results[0]} selected={selected === results[0].id}
                          onSelect={() => setSelected(results[0].id)} verify={verifyFor(results[0])} />
              {results.length > 1 && (
                <div className="rows">
                  {results.slice(1).map((r) => (
                    <ResultRow key={r.id} rec={r} top={results[0]} selected={selected === r.id}
                               onSelect={() => setSelected(r.id)} verify={verifyFor(r)} />
                  ))}
                </div>
              )}
            </div>
          )}

          {!result && !loading && (
            <div className="empty">
              <p><b>Choose the care you need and where you are.</b></p>
              <p className="muted">We'll show the 5 best nearby options, how long it takes to get there, and what to ask when you call.</p>
            </div>
          )}
        </section>

        <section className="right">
          <ResultsMap result={result} selected={selected} onSelect={setSelected} />
        </section>
      </main>
      )}
    </div>
  )
}
