import * as T from '@radix-ui/react-tooltip'

export const TooltipProvider = ({ children }) => <T.Provider delayDuration={300} skipDelayDuration={200}>{children}</T.Provider>

// Wraps one focusable child. Tooltips hold extra help only; never the only place a fact lives.
export default function Tooltip({ content, children, side = 'top' }) {
  if (!content) return children
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content className="pop tooltip" side={side} sideOffset={6} collisionPadding={8}>{content}</T.Content>
      </T.Portal>
    </T.Root>
  )
}
