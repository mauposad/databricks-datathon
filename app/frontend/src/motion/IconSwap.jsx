import { AnimatePresence, motion } from 'motion/react'
import Icon from '../components/Icon.jsx'
import { DUR, EASE_OUT } from './presets.js'
import { useReducedMotion } from 'motion/react'

// M18: crossfade two icons with blur. The old one goes to opacity 0, scale 0.8, blur 4px while the new one
// comes in from the same state, 150ms, overlapped (popLayout).
const HIDDEN = { opacity: 0, scale: 0.8, filter: 'blur(4px)' }
const SHOWN = { opacity: 1, scale: 1, filter: 'blur(0px)' }

export default function IconSwap({ name, size, className = '', spin = false, label }) {
  const reduced = useReducedMotion()
  const transition = reduced ? { duration: 0 } : { duration: DUR.fast, ease: EASE_OUT }
  return (
    <span className={`icon-swap ${className}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={name} className="icon-swap-item" initial={HIDDEN} animate={SHOWN} exit={HIDDEN} transition={transition}>
          <Icon name={name} size={size} label={label} className={spin ? 'spin' : ''} />
        </motion.span>
      </AnimatePresence>
    </span>
  )
}
