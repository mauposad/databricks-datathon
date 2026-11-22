import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { usePresets } from '../motion/presets.js'
import { Badge } from './ui/index.js'
import ResultDetails from './result/ResultDetails.jsx'
import { Actions, BeforeYouDecide, Caution, MetaLine, Stats } from './result/CardFront.jsx'
import { describe } from './result/shared.js'

// Rank 1: the main answer. Larger name, travel time as the largest number, Call as the one primary button.
export default function ResultHero({ rec, top, selected, onSelect, verify, example = false }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => { if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [selected])
  const d = describe(rec, top)
  const p = usePresets()
  return (
    <article ref={ref} className={`card hero ${selected ? 'selected' : ''}`} onClick={onSelect}>
      {/* M20: one selection ring that slides between cards */}
      {selected && <motion.span layoutId="card-selection" className="selection-ring" transition={p.move} aria-hidden />}
      <header className="card-head">
        <motion.span layoutId={example ? undefined : `rank-${rec.id}`} transition={p.move} className="rank" aria-label={`Rank ${rec.rank}`}>{rec.rank}</motion.span>
        <div className="title">
          <h3>{rec.name}</h3>
          <MetaLine rec={rec} d={d} />
        </div>
        <Badge tone={d.badge.tone}>{d.badge.text}</Badge>
      </header>
      <Stats rec={rec} d={d} showQuality />
      <BeforeYouDecide rec={rec} />
      <Caution d={d} />
      {!example && <Actions rec={rec} hero open={open} onToggle={() => setOpen(!open)} />}
      <AnimatePresence mode="popLayout" initial={false}>
        {open && <ResultDetails key="details" rec={rec} d={d} verify={verify} />}
      </AnimatePresence>
    </article>
  )
}
