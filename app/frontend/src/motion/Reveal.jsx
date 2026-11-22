import { motion } from 'motion/react'
import { DUR, EASE_OUT } from './presets.js'
import { useReducedMotion } from 'motion/react'

// M17: mask reveal, left to right, once per card, when the card first shows (cards mount when they are shown:
// the hero on results, a row's meters when it expands). whileInView never fired inside the scrolling list column.
export default function Reveal({ as = 'div', children, className, ...props }) {
  const reduced = useReducedMotion()
  const M = motion[as]
  if (reduced) return <M className={className} {...props}>{children}</M>
  return (
    <M className={className} initial={{ clipPath: 'inset(0 100% 0 0)' }} animate={{ clipPath: 'inset(0 0% 0 0)' }}
       transition={{ duration: DUR.reveal, ease: EASE_OUT, delay: 0.1 }} {...props}>
      {children}
    </M>
  )
}
