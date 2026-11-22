import * as D from '@radix-ui/react-dialog'
import Icon from '../Icon.jsx'

export default function Dialog({ trigger, title, children, open, onOpenChange }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <D.Trigger asChild>{trigger}</D.Trigger>}
      <D.Portal>
        <D.Overlay className="dialog-overlay" />
        <D.Content className="pop dialog" aria-describedby={undefined}>
          <div className="dialog-head">
            <D.Title className="dialog-title">{title}</D.Title>
            <D.Close className="icon-btn" aria-label="Close"><Icon name="x" /></D.Close>
          </div>
          <div className="dialog-body">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
