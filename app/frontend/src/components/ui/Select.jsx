import * as S from '@radix-ui/react-select'
import Icon from '../Icon.jsx'

// options: [{ value, label }]. Values must be non-empty strings (Radix rule).
export default function Select({ value, onValueChange, options, placeholder, label, disabled, loading, loadingText, className = '', id }) {
  return (
    <S.Root value={value || undefined} onValueChange={onValueChange} disabled={disabled || loading}>
      <S.Trigger id={id} className={`field select-trigger ${className}`} aria-label={label}>
        <S.Value placeholder={loading ? (loadingText || 'Loading') : placeholder} />
        <S.Icon className="select-chevron">
          {loading ? <Icon name="spinner" className="spin" /> : <Icon name="chevronDown" />}
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content className="pop select-content" position="popper" sideOffset={4} collisionPadding={8}>
          <S.Viewport className="select-viewport">
            {options.map((o) => (
              <S.Item key={o.value} value={o.value} className="select-item">
                <S.ItemText>{o.label}</S.ItemText>
                <S.ItemIndicator className="select-check"><Icon name="check" /></S.ItemIndicator>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  )
}
