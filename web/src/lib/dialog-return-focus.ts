import { useRef, type MouseEvent } from 'react'

export function useDialogReturnFocus<T extends HTMLElement>(open: boolean) {
  const containerRef = useRef<T>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  return {
    containerRef,
    onClickCapture(event: MouseEvent) {
      if (open || !(event.target instanceof Element)) return
      const button = event.target.closest<HTMLButtonElement>('button')
      if (button) triggerRef.current = button
    },
    onCloseAutoFocus(event: Event) {
      event.preventDefault()
      const trigger = triggerRef.current
      if (trigger?.isConnected && !trigger.disabled) trigger.focus()
      else containerRef.current?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus()
    },
  }
}
