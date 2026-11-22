import { useState } from 'react'
import { Button, Popover, toast } from '../ui/index.js'

// A Confirm or Reject button that opens a small form next to it: optional note, Save, Cancel.
export default function VerifyAction({ status, label, onSave, icon, size = 'sm', variant = 'ghost', children, ariaLabel }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  async function save(e) {
    e.preventDefault()
    setSaving(true)
    try { await onSave(note.trim()); setOpen(false); setNote('') }
    catch (err) { toast.error('Could not save', { description: err.message }) }
    finally { setSaving(false) }
  }

  return (
    <Popover open={open} onOpenChange={(o) => !saving && setOpen(o)} label={`${status === 'confirmed' ? 'Confirm' : 'Reject'}: ${label}`}
             trigger={<Button size={size} variant={variant} icon={icon} aria-label={ariaLabel}>{children}</Button>}>
      <form className="verify-form" onSubmit={save}>
        <p className="verify-form-title">{status === 'confirmed' ? 'Confirm' : 'Reject'}: {label}</p>
        <label className="form-field">
          <span className="field-label">Note (optional)</span>
          <textarea className="field textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="Who you spoke to, or the source" autoFocus />
        </label>
        <div className="verify-form-actions">
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={saving}>Cancel</Button>
          <Button type="submit" variant="primary" loading={saving}>Save</Button>
        </div>
      </form>
    </Popover>
  )
}
