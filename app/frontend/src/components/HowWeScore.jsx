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
          <p><b>Location checks.</b> Each facility's location gets a score from 0 to 5 for how well its own claims agree:
            pincode, city and state, district and postal region, postal circle and division (main checks), plus the map point
            and phone numbers (supporting checks). 5 = all agree; 4 = all main checks agree, or 2-3 do and both supporting
            checks agree; 3 = some agree. Facilities scoring 0-2 are left out because their location could not be verified.
            Facilities not yet checked are shown and marked "Location not validated". The location score does not change the rank.</p>
          <p className="muted">Evidence is matched in the facility's own listed procedures, capabilities, equipment,
            specialties and description, and quoted word for word on each card. Nothing is inferred by an AI model:
            the ranking is a fixed formula over the cleaned data in <code>workspace.datathon</code>.</p>
        </div>
      )}
    </div>
  )
}
