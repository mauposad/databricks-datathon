import { useRef, useState } from 'react'
import * as S from '@radix-ui/react-slider'
import { useReducedMotion } from 'motion/react'

const RESISTANCE = 0.3   // M19: the thumb follows 0.3 of the pointer past either end
const MAX_PULL = 16      // px

// M5: the thumb stretches 12% along the track while held (CSS, .slider-thumb:active).
// M14: while held, the thumb follows the pointer 1:1 (Radix sets its position directly; no transition on it).
// M19: past the 10 or 300 km end the thumb moves on with resistance, then returns on release (ease-out, 200ms).
export default function Slider({ value, onValueChange, min, max, step, label, className = '' }) {
  const rootRef = useRef(null)
  const [pull, setPull] = useState(0)
  const [held, setHeld] = useState(false)
  const reduced = useReducedMotion()

  function onPointerDown(e) {
    if (reduced) return
    setHeld(true)
    const move = (ev) => {
      const r = rootRef.current?.getBoundingClientRect()
      if (!r) return
      const over = ev.clientX > r.right ? ev.clientX - r.right : ev.clientX < r.left ? ev.clientX - r.left : 0
      setPull(Math.max(-MAX_PULL, Math.min(MAX_PULL, over * RESISTANCE)))
    }
    const up = () => { setHeld(false); setPull(0); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <S.Root ref={rootRef} className={`slider ${held ? 'is-held' : ''} ${className}`} value={[value]} min={min} max={max} step={step}
            onValueChange={([v]) => onValueChange(v)} onPointerDown={onPointerDown}
            style={{ '--pull': `${pull}px` }}>
      <S.Track className="slider-track"><S.Range className="slider-range" /></S.Track>
      <S.Thumb className="slider-thumb" aria-label={label} />
    </S.Root>
  )
}
