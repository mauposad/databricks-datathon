import { useMemo, useRef, useState } from 'react'
import * as P from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import Icon from './Icon.jsx'
import { buildVocab, suggest } from '../careTerms.js'

// "Care needed": type everyday words ("childbirth", "chest pain", "daant") or browse the broad groups.
// value: { group, service } where group is a group key and service an optional specific service key.
export default function CarePicker({ groups, services, value, onChange, loading, id }) {
  const [text, setText] = useState(null)          // null = show the selected group's label
  const [open, setOpen] = useState(false)
  const anchorRef = useRef(null)
  // clicks and focus on the input itself are not "outside" (it is the anchor, not a Radix trigger)
  const inAnchor = (e) => { if (anchorRef.current?.contains(e.target)) e.preventDefault() }
  const vocab = useMemo(() => buildVocab(groups, services), [groups, services])
  const selected = groups.find((g) => g.key === value?.group)
  const shown = text ?? (selected?.label || '')
  const items = useMemo(() => suggest(text ?? '', groups, vocab), [text, groups, vocab])
  const labelOf = (k) => services.find((s) => s.key === k)?.label || k

  function pick(it) {
    onChange({ group: it.group.key, service: it.service })
    setText(null); setOpen(false)
  }

  function onBlur() {
    setOpen(false)
    // typed words but did not pick: take the best match, so "chest pain" + Find works
    if (text && text.trim()) {
      const best = suggest(text, groups, vocab, 1)[0]
      if (best) pick(best)
      else setText(null)
    } else setText(null)
  }

  return (
    <P.Root open={open && items.length > 0} onOpenChange={setOpen}>
      <Command shouldFilter={false} loop label="Care needed" className="combobox"
               onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.preventDefault(); setOpen(false) } }}>
        <P.Anchor asChild>
          <div className="field field-group" ref={anchorRef}>
            <Icon name="search" className="field-icon" />
            <Command.Input id={id} value={shown} aria-label="Care needed"
                           placeholder={loading ? 'Loading care types' : 'e.g. childbirth, chest pain, child doctor'}
                           disabled={loading && !groups.length}
                           onValueChange={(v) => { setText(v); setOpen(true); if (value?.group) onChange(null) }}
                           onFocus={() => setOpen(true)} onBlur={onBlur} />
            {loading && <span className="field-status" aria-label="Loading care types"><Icon name="spinner" className="spin" /></span>}
          </div>
        </P.Anchor>
        <P.Portal>
          <P.Content className="pop combobox-content" align="start" sideOffset={4} collisionPadding={8}
                     onOpenAutoFocus={(e) => e.preventDefault()} onCloseAutoFocus={(e) => e.preventDefault()}
                     onInteractOutside={inAnchor} onMouseDown={(e) => e.preventDefault()}>
            <Command.List className="combobox-list">
              {items.map((it) => (
                <Command.Item key={`${it.group.key}|${it.service || ''}`} value={`${it.group.key}|${it.service || ''}`}
                              className="select-item care-item" onSelect={() => pick(it)}>
                  <span className="care-item-label">{it.group.label}</span>
                  <span className="care-item-hint muted">
                    {it.via
                      ? <>matches “{it.via}”{it.service && it.group.services.length > 1 ? ` · ${labelOf(it.service)}` : ''}</>
                      : it.group.description}
                  </span>
                </Command.Item>
              ))}
            </Command.List>
          </P.Content>
        </P.Portal>
      </Command>
    </P.Root>
  )
}
