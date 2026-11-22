import * as P from '@radix-ui/react-popover'

// <Popover trigger={<Button />}>content</Popover>. Controlled when `open` is passed.
export default function Popover({ trigger, children, open, onOpenChange, align = 'start', side = 'bottom', className = '', label }) {
  return (
    <P.Root open={open} onOpenChange={onOpenChange}>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content className={`pop popover ${className}`} align={align} side={side} sideOffset={6}
                   collisionPadding={12} aria-label={label}>
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  )
}
export const PopoverClose = P.Close
