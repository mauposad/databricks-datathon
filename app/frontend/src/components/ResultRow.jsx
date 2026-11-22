import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { Badge, Button, Tooltip } from './ui/index.js'
import ResultDetails from './result/ResultDetails.jsx'
import { Actions, BeforeYouDecide, Caution, MetaLine, Stats } from './result/CardFront.jsx'
import { describe, fmtKm, fmtMin, telHref } from './result/shared.js'

// Ranks 2 to 5: one compact row. Expanding it shows what the full card shows.
export default function ResultRow({ rec, top, selected, onSelect, verify }) {
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => { if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [selected])
  const d = describe(rec, top)
  const travel = rec.travel_min != null ? fmtMin(rec.travel_min) : rec.distance_km != null ? fmtKm(rec.distance_km) : null
  const bodyId = `row-body-${rec.id}`

  function toggle() { setExpanded(!expanded); onSelect() }

  return (
    <article ref={ref} className={`card row ${selected ? 'selected' : ''} ${expanded ? 'expanded' : ''}`}>
      <div className="row-head" onClick={toggle}>
        <span className="rank" aria-label={`Rank ${rec.rank}`}>{rec.rank}</span>
        <div className="row-title">
          <h3>{rec.name}</h3>
          <Badge tone={d.badge.tone}>{d.badge.text}</Badge>
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
            <Icon name="chevronDown" />
          </button>
        </span>
      </div>
      {expanded && (
        <div className="row-body" id={bodyId}>
          <MetaLine rec={rec} d={d} />
          <Stats rec={rec} d={d} />
          <BeforeYouDecide rec={rec} />
          <Caution d={d} />
          <Actions rec={rec} open={open} onToggle={() => setOpen(!open)} />
          {open && <ResultDetails rec={rec} d={d} verify={verify} />}
        </div>
      )}
    </article>
  )
}
