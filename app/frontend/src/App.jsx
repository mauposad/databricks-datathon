import { useEffect, useState } from 'react'
import * as api from './api.js'
import SearchForm from './components/SearchForm.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import VoicePanel from './components/VoicePanel.jsx'
import ResultCard from './components/ResultCard.jsx'
import ResultsMap from './components/ResultsMap.jsx'
import HowWeScore from './components/HowWeScore.jsx'
import Planner from './components/Planner.jsx'

const MODES = [
  { key: 'form', label: 'Search' },
  { key: 'chat', label: 'Chat' },
  { key: 'voice', label: 'Voice' },
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
          <span className="logo" aria-hidden>✚</span>
          <div>
            <h1>Care Finder</h1>
            <p>Find Indian healthcare facilities for a specific service, with the evidence behind every recommendation.</p>
          </div>
        </div>
        <div className="view-switch" role="tablist">
          <button role="tab" aria-selected={view === 'find'} className={view === 'find' ? 'tab active' : 'tab'} onClick={() => setView('find')}>Find care</button>
          <button role="tab" aria-selected={view === 'planner'} className={view === 'planner' ? 'tab active' : 'tab'} onClick={() => setView('planner')}>District planner</button>
        </div>
      </header>

      {view === 'planner' ? <main className="planner-layout"><Planner /></main> : (
      <main className="layout">
        <section className="left">
          <div className="panel input-panel">
            <div className="tabs" role="tablist">
              {MODES.map((m) => (
                <button key={m.key} role="tab" aria-selected={mode === m.key}
                        className={mode === m.key ? 'tab active' : 'tab'} onClick={() => setMode(m.key)}>
                  {m.label}
                </button>
              ))}
            </div>
            {mode === 'form' && <SearchForm services={services} places={places} loading={loading} onSearch={runSearch} />}
            {mode === 'chat' && <ChatPanel onResult={showResult} />}
            {mode === 'voice' && <VoicePanel onResult={showResult} />}
          </div>

          {error && <div className="alert error">{error}</div>}

          {result && (
            <div className="summary">
              {result.chat && (
                <div className="understood">
                  Searching: <b>{result.service_label || result.query.service}</b> near <b>{result.query.place}</b>,
                  {' '}{result.query.max_km} km{result.query.public_only ? ', government facilities only' : ''}
                  <span className="muted"> (understood {result.chat.parsed_by === 'llm' ? 'by the AI model' : 'by keyword matching'};
                  {' '}reply {result.chat.reply_source === 'llm' ? 'worded by the AI model and checked against these results' : `from a fixed template${result.chat.reply_source?.startsWith('template (') ? ': ' + result.chat.reply_source.slice(10, -1) : ''}`})</span>
                </div>
              )}
              <div>
                <strong>{result.service_label || result.query.service}</strong> near{' '}
                <strong>{result.origin?.label || result.query.place}</strong>
                <span className="muted"> · within {result.query.max_km} km{result.query.public_only ? ' · government facilities only' : ''} · {result.n_candidates} facilities with evidence in range</span>
              </div>
              <HowWeScore method={result.method} rule={results[0]?.confidence.rule} />
            </div>
          )}
          {result?.safety_note && <div className="alert safety" role="alert">⚠ {result.safety_note}</div>}
          {result?.notes?.map((n) => <div key={n} className="alert note">{n}</div>)}

          {loading && <div className="skeletons">{[0, 1, 2].map((i) => <div key={i} className="skeleton" />)}</div>}

          <div className="cards">
            {!loading && results.map((r) => (
              <ResultCard key={r.id} rec={r} top={results[0]} selected={selected === r.id}
                          onSelect={() => setSelected(r.id)} serviceKey={result.service_key} onVerified={refresh} />
            ))}
          </div>

          {!result && !loading && (
            <div className="empty">
              <p>Pick a service and a place to get the top 5 facilities.</p>
              <p className="muted">Every result shows the exact text from the facility's record that supports it, how the score was calculated, and what we are unsure about.</p>
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
