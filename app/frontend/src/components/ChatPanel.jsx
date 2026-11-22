import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import { canListen, canSpeak, listen, speak, stopSpeaking } from '../speech.js'
import Icon from './Icon.jsx'
import { Button, Switch } from './ui/index.js'

const GREETING = { role: 'assistant', content: 'Tell me what care you need and where. For example: "My father needs dialysis, we are in Jaipur".' }

export default function ChatPanel({ onResult, voiceFirst = false }) {
  const [messages, setMessages] = useState([GREETING])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(voiceFirst)
  const stopRef = useRef(null)
  const endRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [messages])
  useEffect(() => () => { stopRef.current?.(); stopSpeaking() }, [])

  async function send(text) {
    const msg = text.trim()
    if (!msg || busy) return
    const history = messages.filter((m) => m !== GREETING)
    setMessages((m) => [...m, { role: 'user', content: msg }])
    setInput(''); setBusy(true)
    try {
      const res = await api.chat(msg, history)
      setMessages((m) => [...m, { role: 'assistant', content: res.reply, meta: res.query ? `${res.query.service} · ${res.query.place} · parsed by ${res.parsed_by}` : null }])
      onResult(res.recommendations && { ...res.recommendations, chat: { parsed_by: res.parsed_by, reply_source: res.reply_source } })
      if (autoSpeak) speak(res.reply)
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: `Sorry, something went wrong: ${e.message}` }])
    } finally { setBusy(false) }
  }

  function toggleMic() {
    if (listening) { stopRef.current?.(); return }
    stopSpeaking()
    setListening(true)
    stopRef.current = listen({
      onInterim: (t) => setInput(t),
      onFinal: (t) => { setInput(t); send(t) },
      onEnd: () => setListening(false),
      onError: (err) => { setListening(false); if (err !== 'no-speech' && err !== 'aborted') alert(`Microphone error: ${err}`) },
    })
  }

  return (
    <div className={`chat ${voiceFirst ? 'voice-mode' : ''}`}>
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.content}</div>
            {m.role === 'assistant' && i > 0 && canSpeak && (
              <Button variant="ghost" size="sm" icon="speaker" onClick={() => speak(m.content)}>Read aloud</Button>
            )}
            {m.meta && <div className="meta">{m.meta}</div>}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing">Searching…</div></div>}
        <div ref={endRef} />
      </div>

      {voiceFirst ? (
        <div className="voice-controls">
          <button type="button" className={`mic big ${listening ? 'on' : ''}`} onClick={toggleMic} disabled={!canListen || busy}
                  aria-label={listening ? 'Stop listening' : 'Start talking'}>
            <Icon name={listening ? 'stop' : 'mic'} size="xl" />
          </button>
          <div className="muted" aria-live="polite">
            {!canListen ? 'Voice input needs Chrome, Edge or Safari.'
              : listening ? <><span className="rec-dot" aria-hidden />{input || 'Listening'}</>
              : 'Tap and say what you need and where.'}
          </div>
        </div>
      ) : (
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(input) }}>
          {canListen && (
            <button type="button" className={`icon-btn mic ${listening ? 'on' : ''}`} onClick={toggleMic}
                    aria-label={listening ? 'Stop listening' : 'Speak'}>
              <Icon name={listening ? 'stop' : 'mic'} />
            </button>
          )}
          <input className="field" value={input} onChange={(e) => setInput(e.target.value)} aria-label="Message"
                 placeholder="e.g. NICU near Patna within 100 km" />
          <Button type="submit" variant="primary" icon="send" disabled={busy || !input.trim()}>Send</Button>
        </form>
      )}
      {canSpeak && <Switch checked={autoSpeak} onCheckedChange={setAutoSpeak} label="Read answers aloud" className="auto-speak" />}
    </div>
  )
}
