import { useEffect, useRef, useState } from 'react'
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
  return (
    <article ref={ref} className={`card hero ${selected ? 'selected' : ''}`} onClick={onSelect}>
      <header className="card-head">
        <span className="rank" aria-label={`Rank ${rec.rank}`}>{rec.rank}</span>
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
      {open && <ResultDetails rec={rec} d={d} verify={verify} />}
    </article>
  )
}
