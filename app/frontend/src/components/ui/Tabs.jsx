import { useRef } from 'react'
import { motion } from 'motion/react'
import { usePresets } from '../../motion/presets.js'

// Tab row with roving focus (arrow keys, Home, End). The selected tab is marked by an underline.
// M20 + M9: one underline per tab group (layoutId) that slides between tabs, ease-in-out 280ms.
export default function Tabs({ items, value, onChange, label, id, className = '' }) {
  const refs = useRef({})
  const p = usePresets()
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
            {on && <motion.span layoutId={`tab-underline-${id}`} className="tab-underline" aria-hidden transition={p.move} />}
          </button>
        )
      })}
    </div>
  )
}
