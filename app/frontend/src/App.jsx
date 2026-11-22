import { useEffect, useState } from 'react'
import * as api from './api.js'
import SearchForm from './components/SearchForm.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import VoicePanel from './components/VoicePanel.jsx'
import ResultCard from './components/ResultCard.jsx'
import ResultsMap from './components/ResultsMap.jsx'
import HowWeScore from './components/HowWeScore.jsx'
import Planner from './components/Planner.jsx'
import Icon from './components/Icon.jsx'
import { Skeleton, Tabs } from './components/ui/index.js'

const MODES = [
  { key: 'form', label: 'Search' },
  { key: 'chat', label: 'Chat' },
  { key: 'voice', label: 'Voice' },
]
const VIEWS = [
  { key: 'find', label: 'Find care' },
  { key: 'planner', label: 'District planner' },
]

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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Icon name="logo" size="md" className="logo" />
          <div>
            <h1>Care Finder</h1>
            <p>Find the right hospital for the care you need, and see why we recommend it.</p>
          </div>
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

          {error && <div className="alert error">{error}</div>}

          {result?.safety_note && (
            <div className="alert safety" role="alert">
              <Icon name="warning" size="md" />
              <div><b>Emergency?</b> {result.safety_note}</div>
            </div>
          )}

          {result && (
            <div className="summary">
              <h2>
                {results.length > 0 ? `${results.filter((r) => !r.is_nearest_alternative).length} best options` : 'No matches'} for{' '}
                {result.service_label || result.query.service}
              </h2>
              <p className="muted">
                Near {result.origin?.label || result.query.place} · within {result.query.max_km} km
                {result.query.public_only ? ' · government facilities only' : ''} · {result.n_candidates} facilities checked
              </p>
              {result.chat && (
                <p className="muted small">
                  Understood {result.chat.parsed_by === 'llm' ? 'by the AI model' : 'by keyword matching'};
                  {' '}reply {result.chat.reply_source === 'llm' ? 'worded by the AI model and checked against these results' : 'from a fixed template'}.
                </p>
              )}
              <HowWeScore method={result.method} rule={results[0]?.confidence.rule} />
            </div>
          )}
          {result?.notes?.map((n) => <div key={n} className="alert note">{n}</div>)}

          {loading && <div className="skeletons">{[0, 1, 2].map((i) => <Skeleton key={i} height={200} radius="var(--r-lg)" />)}</div>}

          <div className="cards">
            {!loading && results.map((r) => (
              <ResultCard key={r.id} rec={r} top={results[0]} selected={selected === r.id}
                          onSelect={() => setSelected(r.id)} serviceKey={result.service_key} onVerified={refresh} />
            ))}
          </div>

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
