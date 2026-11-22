import { useState } from 'react'

export default function HowWeScore({ method, rule }) {
  const [open, setOpen] = useState(false)
  if (!method) return null
  return (
    <div className="how">
      <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'How we score'} ⓘ</button>
      {open && (
        <div className="how-body">
          <p>{method}</p>
          {rule && <p><b>Confidence labels.</b> {rule}</p>}
          <p><b>How solid is this pick?</b> After ranking, we double-check #1 by re-running the ranking three ways, each
            time doubting one part of the data: only facilities with detailed evidence count, facilities found on just one
            website are ignored, and fuzzy addresses are moved to their other recorded location. If #1 stays on top every
            time, it's a solid pick; if not, we name who would take its place, so you know who to call second. We also
            check two situations (you can travel twice as far; only the evidence matters, not hospital size) and show a
            tip on any facility that would become the best option.</p>
          <p className="muted">Evidence is matched in the facility's own listed procedures, capabilities, equipment,
            specialties and description, and quoted word for word on each card. Nothing is inferred by an AI model:
            the ranking is a fixed formula over the cleaned data in <code>workspace.datathon</code>.</p>
        </div>
      )}
    </div>
  )
}
