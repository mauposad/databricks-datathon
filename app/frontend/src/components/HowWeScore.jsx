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
          <p className="muted">Evidence is matched in the facility's own listed procedures, capabilities, equipment,
            specialties and description, and quoted word for word on each card. Nothing is inferred by an AI model:
            the ranking is a fixed formula over the cleaned data in <code>workspace.datathon</code>.</p>
        </div>
      )}
    </div>
  )
}
