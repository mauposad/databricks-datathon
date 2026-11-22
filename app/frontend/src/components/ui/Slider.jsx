import * as S from '@radix-ui/react-slider'

export default function Slider({ value, onValueChange, min, max, step, label, className = '' }) {
  return (
    <S.Root className={`slider ${className}`} value={[value]} min={min} max={max} step={step}
            onValueChange={([v]) => onValueChange(v)}>
      <S.Track className="slider-track"><S.Range className="slider-range" /></S.Track>
      <S.Thumb className="slider-thumb" aria-label={label} />
    </S.Root>
  )
}
