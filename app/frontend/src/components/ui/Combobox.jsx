import { useMemo, useState } from 'react'
import * as P from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import Icon from '../Icon.jsx'

const LIMIT = 50

// Free-text input with suggestions. The user can type any value (a PIN code, a "lat,lon"), or pick one.
// Enter picks the highlighted suggestion; with no list open it submits the form.
export default function Combobox({ value, onChange, options, placeholder, label, loading, trailing, onEnter, invalid, describedBy }) {
  const [open, setOpen] = useState(false)
  const matches = useMemo(() => {
    const q = value.trim().toLowerCase()
    if (!q) return []
    const starts = [], has = []
    for (const o of options) {
      const l = o.toLowerCase()
      if (l === q) continue
      if (l.startsWith(q)) starts.push(o)
      else if (l.includes(q)) has.push(o)
      if (starts.length >= LIMIT) break
    }
    return [...starts, ...has].slice(0, LIMIT)
  }, [value, options])
  const show = open && matches.length > 0

  function onKeyDown(e) {
    if (e.key === 'Enter' && !show) { e.preventDefault(); onEnter?.() }
    if (e.key === 'Escape' && show) { e.preventDefault(); setOpen(false) }
  }

  return (
    <P.Root open={show} onOpenChange={setOpen}>
      <Command shouldFilter={false} loop label={label} className="combobox" onKeyDown={onKeyDown}>
        <P.Anchor asChild>
          <div className={`field field-group ${invalid ? 'is-invalid' : ''}`}>
            <Command.Input value={value} placeholder={placeholder} aria-label={label}
                           aria-invalid={invalid || undefined} aria-describedby={describedBy}
                           onValueChange={(v) => { onChange(v); setOpen(true) }}
                           onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} />
            {loading && <span className="field-status" aria-label="Loading places"><Icon name="spinner" className="spin" /></span>}
            {trailing}
          </div>
        </P.Anchor>
        <P.Portal>
          <P.Content className="pop combobox-content" align="start" sideOffset={4} collisionPadding={8}
                     onOpenAutoFocus={(e) => e.preventDefault()} onCloseAutoFocus={(e) => e.preventDefault()}
                     onMouseDown={(e) => e.preventDefault()}>
            <Command.List className="combobox-list">
              {matches.map((m) => (
                <Command.Item key={m} value={m} className="select-item" onSelect={() => { onChange(m); setOpen(false) }}>
                  {m}
                </Command.Item>
              ))}
            </Command.List>
          </P.Content>
        </P.Portal>
      </Command>
    </P.Root>
  )
}
