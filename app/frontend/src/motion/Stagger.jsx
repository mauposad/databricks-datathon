import { motion } from 'motion/react'
import { usePresets } from './presets.js'

// <StaggerItem index={i}> enters 30ms after the one before it (M3), capped at 150ms in total.
export function StaggerItem({ index = 0, as = 'div', children, ...props }) {
  const p = usePresets()
  const M = motion[as]
  return <M {...p.item(index)} {...props}>{children}</M>
}
