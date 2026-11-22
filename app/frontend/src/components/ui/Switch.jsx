import { useId } from 'react'
import * as S from '@radix-ui/react-switch'

export default function Switch({ checked, onCheckedChange, label, className = '' }) {
  const id = useId()
  return (
    <span className={`switch-row ${className}`}>
      <S.Root id={id} className="switch" checked={checked} onCheckedChange={onCheckedChange}>
        <S.Thumb className="switch-thumb" />
      </S.Root>
      <label htmlFor={id}>{label}</label>
    </span>
  )
}
