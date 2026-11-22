// One place to ask "should this move?". The CSS side is the media query in styles/tokens.css,
// which sets every duration token to 0.01ms. The motion side is <MotionConfig reducedMotion="user"> in main.jsx
// plus this hook, for code that picks a different variant (for example no slide, only an instant swap).
export { useReducedMotion } from 'motion/react'
