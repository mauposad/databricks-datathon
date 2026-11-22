import { useRef } from 'react'

// Tab row with roving focus (arrow keys, Home, End). The selected tab is marked by an underline.
export default function Tabs({ items, value, onChange, label, className = '' }) {
  const refs = useRef({})
  function onKeyDown(e) {
    const i = items.findIndex((t) => t.key === value)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: items.length - 1 }[e.key]
    if (next == null) return
    e.preventDefault()
    const t = items[(next + items.length) % items.length]
    onChange(t.key)
    refs.current[t.key]?.focus()
  }
  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {items.map((t) => {
        const on = t.key === value
        return (
          <button key={t.key} ref={(el) => { refs.current[t.key] = el }} type="button" role="tab"
                  aria-selected={on} tabIndex={on ? 0 : -1} className={`tab ${on ? 'active' : ''}`}
                  onClick={() => onChange(t.key)}>
            <span className="tab-label">{t.label}</span>
            {on && <span className="tab-underline" aria-hidden />}
          </button>
        )
      })}
    </div>
  )
}
