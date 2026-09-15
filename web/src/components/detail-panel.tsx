import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import './detail-panel.css'

export function DetailPanel({ as: Element = 'section', className, ...props }: HTMLAttributes<HTMLElement> & { as?: 'section' | 'article' }) {
  return <Element {...props} className={cn('detail-panel', className)} />
}
