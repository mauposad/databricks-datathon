// Browser-native speech: recognition (Chrome/Edge/Safari) and synthesis (all modern browsers).
const Recognition = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)

export const canListen = !!Recognition
export const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

export function listen({ lang = 'en-IN', onInterim, onFinal, onEnd, onError }) {
  const rec = new Recognition()
  rec.lang = lang
  rec.interimResults = true
  rec.continuous = false
  rec.onresult = (e) => {
    let text = ''
    let final = false
    for (const r of e.results) { text += r[0].transcript; final = final || r.isFinal }
    final ? onFinal?.(text) : onInterim?.(text)
  }
  rec.onerror = (e) => onError?.(e.error)
  rec.onend = () => onEnd?.()
  rec.start()
  return () => rec.stop()
}

export function speak(text, { lang = 'en-IN', onEnd } = {}) {
  if (!canSpeak) return
  window.speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = lang
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang === lang)
  if (voice) u.voice = voice
  u.onend = () => onEnd?.()
  window.speechSynthesis.speak(u)
}

export const stopSpeaking = () => canSpeak && window.speechSynthesis.cancel()
