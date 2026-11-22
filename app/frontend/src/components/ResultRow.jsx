import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { usePresets } from '../motion/presets.js'
import IconSwap from '../motion/IconSwap.jsx'
import { Badge, Button, Tooltip } from './ui/index.js'
import Icon from './Icon.jsx'
import ResultDetails from './result/ResultDetails.jsx'
import { Actions, BeforeYouDecide, Caution, MetaLine, Stats } from './result/CardFront.jsx'
import { describe, fmtKm, fmtMin, telHref } from './result/shared.js'

// Ranks 2 to 5: one compact row. Expanding it shows what the full card shows.
// expandSignal: { id, n } from App when a map pin is clicked; that row opens, as the old full card showed everything.
export default function ResultRow({ rec, top, selected, onSelect, verify, expandSignal }) {
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  // Scroll after the row has opened (rAF), so the whole expanded row comes into view.
  useEffect(() => {
    if (!selected) return
    const id = requestAnimationFrame(() => ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
    return () => cancelAnimationFrame(id)
  }, [selected, expanded])
  useEffect(() => { if (expandSignal?.id === rec.id) setExpanded(true) }, [expandSignal, rec.id])
  const d = describe(rec, top)
  const p = usePresets()
  const travel = rec.travel_min != null ? fmtMin(rec.travel_min) : rec.distance_km != null ? fmtKm(rec.distance_km) : null
  const bodyId = `row-body-${rec.id}`

  function toggle(e) { e.stopPropagation(); setExpanded(!expanded); onSelect() }

  return (
    <article ref={ref} className={`card row ${selected ? 'selected' : ''} ${expanded ? 'expanded' : ''}`} onClick={onSelect}>
      {selected && <motion.span layoutId="card-selection" className="selection-ring" transition={p.move} aria-hidden />}
      <div className="row-head" onClick={toggle}>
        <motion.span layoutId={`rank-${rec.id}`} transition={p.move} className="rank" aria-label={`Rank ${rec.rank}`}>{rec.rank}</motion.span>
        <div className="row-title">
          <h3>{rec.name}</h3>
          <Badge tone={d.badge.tone}>{d.badge.text}</Badge>
          {/* The old cards showed heads-ups on every card; a collapsed row keeps a marker with the text. */}
          {d.headsUp.length > 0 && (
            <Tooltip content={d.headsUp.map((h) => h.text).join(' ')}>
              <span className={`row-caution ${d.headsUp.some((h) => h.level === 'bad') ? 'bad' : ''}`} tabIndex={0}>
                <Icon name="warning" /><span className="vh">{d.headsUp.map((h) => h.text).join(' ')}</span>
              </span>
            </Tooltip>
          )}
        </div>
        {travel && <span className="row-travel num">{travel}</span>}
        <span className="row-actions" onClick={(e) => e.stopPropagation()}>
          {rec.phone && (
            <Tooltip content={`Call ${rec.phone}`}>
              <Button as="a" size="sm" icon="phone" className="icon-only" href={telHref(rec.phone)} aria-label={`Call ${rec.name}, ${rec.phone}`} />
            </Tooltip>
          )}
          <button type="button" className="icon-btn row-chevron" aria-expanded={expanded} aria-controls={bodyId}
                  aria-label={expanded ? `Collapse ${rec.name}` : `Expand ${rec.name}`} onClick={toggle}>
            <IconSwap name={expanded ? 'chevronUp' : 'chevronDown'} />
          </button>
        </span>
      </div>
      <AnimatePresence mode="popLayout" initial={false}>
      {expanded && (
        <motion.div key="body" className="row-body" id={bodyId} {...p.revealDown}>
          <MetaLine rec={rec} d={d} />
          <Stats rec={rec} d={d} />
          <BeforeYouDecide rec={rec} />
          <Caution d={d} />
          <Actions rec={rec} open={open} onToggle={() => setOpen(!open)} />
          <AnimatePresence mode="popLayout" initial={false}>
            {open && <ResultDetails key="details" rec={rec} d={d} verify={verify} />}
          </AnimatePresence>
        </motion.div>
      )}
      </AnimatePresence>
    </article>
  )
}
