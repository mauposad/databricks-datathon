import {
  ArrowRight, Check, ChevronDown, ChevronRight, ChevronUp, CircleAlert, Contrast, Info, Link, LoaderCircle, LocateFixed,
  Mail, MapPin, Mic, Minus, Navigation, Phone, Plus, Search, Send, ShieldCheck, Square, TriangleAlert, Volume2, X,
  Globe, HeartPulse, Lightbulb, MessageSquare, CircleHelp, RotateCw,
} from 'lucide-react'

// One icon set, one stroke width, one size scale (16 and 20).
// `xl` (28) is used once: the large voice button, where a 20px glyph reads as a mistake.
const ICONS = {
  arrowRight: ArrowRight, check: Check, chevronDown: ChevronDown, chevronRight: ChevronRight, chevronUp: ChevronUp, alert: CircleAlert,
  half: Contrast, info: Info, link: Link, spinner: LoaderCircle, locate: LocateFixed, mail: Mail, pin: MapPin,
  mic: Mic, minus: Minus, directions: Navigation, phone: Phone, plus: Plus, search: Search, send: Send,
  shield: ShieldCheck, stop: Square, warning: TriangleAlert, speaker: Volume2, x: X, globe: Globe, logo: HeartPulse,
  tip: Lightbulb, ask: MessageSquare, help: CircleHelp, retry: RotateCw,
}
const SIZES = { sm: 16, md: 20, xl: 28 }

export default function Icon({ name, size = 'sm', label, className = '', ...rest }) {
  const C = ICONS[name]
  if (!C) throw new Error(`Unknown icon: ${name}`)
  return (
    <C size={SIZES[size] || size} strokeWidth={1.75} className={`icon icon-${name} ${className}`}
       aria-hidden={label ? undefined : true} aria-label={label} role={label ? 'img' : undefined} focusable="false" {...rest} />
  )
}
