import Icon from '../Icon.jsx'

// Tones: neutral, success, warning, danger.
export default function Badge({ tone = 'neutral', icon, className = '', children, ...props }) {
  return (
    <span className={`badge badge-${tone} ${className}`} {...props}>
      {icon && <Icon name={icon} />}
      {children}
    </span>
  )
}
