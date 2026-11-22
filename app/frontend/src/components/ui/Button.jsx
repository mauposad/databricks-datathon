import { forwardRef } from 'react'
import Icon from '../Icon.jsx'

// Action weight: primary (accent fill, one per screen area), secondary (outline), ghost (text), danger.
// `as="a"` renders a link with the same look.
const Button = forwardRef(function Button(
  { variant = 'secondary', size = 'md', as: As = 'button', icon, iconRight, loading = false, className = '', children, ...props }, ref,
) {
  const extra = As === 'button' ? { type: props.type || 'button' } : {}
  return (
    <As ref={ref} className={`btn btn-${variant} btn-${size} ${loading ? 'is-loading' : ''} ${className}`}
        aria-busy={loading || undefined} {...extra} {...props}>
      {(icon || loading) && (
        <span className="btn-icon">{loading ? <Icon name="spinner" className="spin" /> : <Icon name={icon} />}</span>
      )}
      {children != null && <span className="btn-label">{children}</span>}
      {iconRight && <Icon name={iconRight} />}
    </As>
  )
})
export default Button
