import { AlertTriangle, Check, Circle, Clock3, X } from 'lucide-react'
import type { ComponentType } from 'react'
import type { CollectorStatus, ItemDecision, RunStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { statusLabel, statusTone } from '@/lib/status'

const toneClasses = {
  neutral: 'border-[#d9e0e3] bg-[#eef2f3] text-[#526169]',
  info: 'border-[#bad0ff] bg-[#edf3ff] text-[#2557d6]',
  success: 'border-[#b6decf] bg-[#eaf7f2] text-[#117153]',
  warning: 'border-[#efd3a8] bg-[#fff6e8] text-[#9b5907]',
  danger: 'border-[#efc1c1] bg-[#fff0f0] text-[#aa3030]',
}

const toneIcons: Record<keyof typeof toneClasses, ComponentType<{ className?: string }>> = {
  neutral: Circle,
  info: Clock3,
  success: Check,
  warning: AlertTriangle,
  danger: X,
}

export function StatusBadge({ status }: { status: CollectorStatus | RunStatus | ItemDecision }) {
  const tone = statusTone(status)
  const Icon = toneIcons[tone]
  return (
    <Badge variant="outline" className={cn('gap-1 rounded-md px-1.5 py-0.5 font-medium', toneClasses[tone])}>
      <Icon className="size-3" aria-hidden="true" />
      {statusLabel(status)}
    </Badge>
  )
}
