import { forwardRef } from 'react'
import Icon from '../Icon.jsx'
import IconSwap from '../../motion/IconSwap.jsx'

// Action weight: primary (accent fill, one per screen area), secondary (outline), ghost (text), danger.
// `as="a"` renders a link with the same look.
const Button = forwardRef(function Button(
  { variant = 'secondary', size = 'md', as: As = 'button', icon, iconRight, iconRightSwap = false, loading = false, className = '', children, ...props }, ref,
) {
  const extra = As === 'button' ? { type: props.type || 'button' } : {}
  return (
    <As ref={ref} className={`btn btn-${variant} btn-${size} ${loading ? 'is-loading' : ''} ${className}`}
        aria-busy={loading || undefined} {...extra} {...props}>
      {/* M18: the spinner crossfades in over the icon; the label stays, so the button keeps its width. */}
      {(icon || loading) && <span className="btn-icon"><IconSwap name={loading ? 'spinner' : icon} spin={loading} /></span>}
      {children != null && <span className="btn-label">{children}</span>}
      {iconRight && (iconRightSwap ? <IconSwap name={iconRight} /> : <Icon name={iconRight} />)}
    </As>
  )
})
export default Button
