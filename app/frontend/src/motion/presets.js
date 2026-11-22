// Motion tokens, mirrored from styles/tokens.css (keep the two in step).
// Rules: animate only transform, opacity, filter and clip-path. Springs never rebound; curves never pass their end value.
import { useReducedMotion } from 'motion/react'

export const EASE_OUT = [0.23, 1, 0.32, 1]      // entrances, press release
export const EASE_IN_OUT = [0.65, 0, 0.35, 1]   // moves, layout
export const EASE_IN = [0.64, 0, 0.78, 0]       // exits only if needed

export const DUR = {
  press: 0.1, release: 0.16, fast: 0.15, pop: 0.16, list: 0.18,
  enter: 0.22, move: 0.28, reveal: 0.4,
}
DUR.exit = DUR.enter * 0.8                       // M15: exits are 20% shorter (176ms)
export const STAGGER = 0.03                      // M3: 30ms
export const STAGGER_CAP = 5                     // items 1 to 5 stagger, the rest arrive with the 5th (max 150ms)
export const PRESS_SCALE = 0.97
export const POP_SCALE = 0.95

export const staggerDelay = (i) => Math.min(i, STAGGER_CAP - 1) * STAGGER

// All presets in one hook so reduced motion swaps every one of them for an instant change.
export function usePresets() {
  const reduced = useReducedMotion()
  const t = (duration, ease = EASE_OUT, delay = 0) => (reduced ? { duration: 0 } : { duration, ease, delay })
  return {
    reduced,
    // M1: enter from 8px below and opacity 0, 220ms ease-out. Exit 20% shorter.
    enter: {
      initial: reduced ? false : { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0, transition: t(DUR.enter) },
      exit: { opacity: 0, transition: t(DUR.exit, EASE_OUT) },
    },
    // M1 + M3: list item i, staggered 30ms, capped at 150ms in total.
    item: (i) => ({
      initial: reduced ? false : { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0, transition: t(DUR.enter, EASE_OUT, staggerDelay(i)) },
      exit: { opacity: 0, transition: t(DUR.exit) },
    }),
    // M6: sections settle one after another, 6px up.
    settle: (i) => ({
      initial: reduced ? false : { opacity: 0, y: 6 },
      animate: { opacity: 1, y: 0, transition: t(DUR.enter, EASE_OUT, i * STAGGER) },
    }),
    // M16: crossfade with overlap (used with AnimatePresence mode="popLayout").
    fade: {
      initial: reduced ? false : { opacity: 0 },
      animate: { opacity: 1, transition: t(DUR.enter) },
      exit: { opacity: 0, transition: t(DUR.exit) },
    },
    // M17: reveal top to bottom with a mask, not a height tween.
    revealDown: {
      initial: reduced ? false : { clipPath: 'inset(0 0 100% 0)', opacity: 0 },
      animate: { clipPath: 'inset(0 0 0% 0)', opacity: 1, transition: t(DUR.enter) },
      exit: { clipPath: 'inset(0 0 100% 0)', opacity: 0, transition: t(DUR.exit) },
    },
    // M9 + M20: shared elements and layout moves use ease-in-out 280ms.
    move: t(DUR.move, EASE_IN_OUT),
    // M8: one ring pulse to confirm success. Not a loop.
    pulse: reduced ? {} : { scale: [1, 1.04, 1], transition: { duration: 0.28, ease: EASE_IN_OUT } },
    // M4: press scale (for motion elements; plain buttons use CSS :active).
    tap: reduced ? undefined : { scale: PRESS_SCALE, transition: { duration: DUR.press, ease: EASE_OUT } },
  }
}
