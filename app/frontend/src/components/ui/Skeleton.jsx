// Flat opacity pulse placeholder. The only infinite animation on the page.
export default function Skeleton({ width, height = 14, radius, className = '', style }) {
  return <span className={`skeleton ${className}`} aria-hidden style={{ width, height, borderRadius: radius, ...style }} />
}
