import { Toaster as Sonner, toast } from 'sonner'

export function Toaster() {
  return <Sonner position="bottom-center" visibleToasts={3} closeButton={false}
                 toastOptions={{ unstyled: true, classNames: { toast: 'toast', title: 'toast-title', description: 'toast-desc', success: 'toast-success', error: 'toast-error' } }} />
}
export { toast }
