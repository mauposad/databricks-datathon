// Contrast check for the colour tokens in src/styles/tokens.css (no dependencies).
// Usage: node frontend/scripts/check-contrast.mjs   (from app/)  -- exits 1 if any pair fails.
//
// Rules: body and small text >= 4.5:1, text of 18px or more >= 3:1, UI borders and icons >= 3:1.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const css = readFileSync(fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url)), 'utf8')

function block(source) {
  const vars = {}
  for (const m of source.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8})\b/g)) vars[m[1]] = m[2]
  return vars
}
const lightSrc = css.slice(0, css.indexOf('@media (prefers-color-scheme: dark)'))
const darkStart = css.indexOf('@media (prefers-color-scheme: dark)')
const darkSrc = css.slice(darkStart, css.indexOf('@media (prefers-reduced-motion', darkStart))
const light = block(lightSrc)
const dark = { ...light, ...block(darkSrc) }

function lum(hex) {
  let h = hex.replace('#', '')
  if (h.length === 3) h = [...h].map((c) => c + c).join('')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }

const TEXT = 4.5, LARGE = 3, UI = 3
// [foreground, background, minimum, what it is]
const PAIRS = [
  ['text', 'bg', TEXT, 'body text'],
  ['text', 'panel', TEXT, 'card text'],
  ['text', 'subtle', TEXT, 'text on inner surface'],
  ['muted', 'bg', TEXT, 'secondary text (12px)'],
  ['muted', 'panel', TEXT, 'secondary text on card (12px)'],
  ['muted', 'subtle', TEXT, 'secondary text on inner surface'],
  ['accent', 'panel', TEXT, 'link on card'],
  ['accent', 'bg', TEXT, 'link on page'],
  ['accent', 'accent-soft', TEXT, 'selected tab label'],
  ['on-accent', 'accent-fill', TEXT, 'primary button label'],
  ['high', 'high-bg', TEXT, 'High badge'],
  ['med', 'med-bg', TEXT, 'Medium badge'],
  ['low', 'low-bg', TEXT, 'Low / error badge'],
  ['none', 'none-bg', TEXT, 'Unconfirmed badge'],
  ['warn', 'warn-bg', TEXT, 'note text'],
  ['high', 'panel', TEXT, 'status text on card'],
  ['warn', 'panel', TEXT, 'warning text on card'],
  ['low', 'panel', TEXT, 'error text on card'],
  ['text', 'mark', TEXT, 'highlighted quote'],
  ['control', 'panel', UI, 'control border on card'],
  ['control', 'bg', UI, 'control border on page'],
  ['accent', 'panel', UI, 'focus ring'],
  ['accent', 'bg', UI, 'focus ring on page'],
  ['map-pin-text', 'map-pin', TEXT, 'map pin digit'],
  ['map-pin-text', 'map-pin-active', LARGE, 'selected map pin digit (bold)'],
]

let failed = 0
for (const [mode, vars] of [['light', light], ['dark', dark]]) {
  console.log(`\n${mode}`)
  for (const [fg, bg, min, what] of PAIRS) {
    if (!vars[fg] || !vars[bg]) { console.log(`  MISSING  --${fg} / --${bg}`); failed++; continue }
    const r = ratio(vars[fg], vars[bg])
    const ok = r >= min
    if (!ok) failed++
    console.log(`  ${ok ? 'pass' : 'FAIL'}  ${r.toFixed(2).padStart(5)}:1 (min ${min})  --${fg} on --${bg}  ${what}`)
  }
}
console.log(failed ? `\n${failed} pair(s) fail.` : '\nAll pairs pass.')
process.exit(failed ? 1 : 0)
