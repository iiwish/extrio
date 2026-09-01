import { Check, Circle } from 'lucide-react'
import { cn } from '@/lib/utils'

const stages = ['设计', '探索', '审核', '发布', '运行']

export function StageRail({ current }: { current: number }) {
  return (
    <ol className="stage-rail" aria-label="Collector 阶段">
      {stages.map((stage, index) => {
        const complete = index < current
        const active = index === current
        return (
          <li key={stage} className={cn('stage-item', active && 'is-active', complete && 'is-complete')}>
            <span className="stage-marker" aria-hidden="true">
              {complete ? <Check className="size-3.5" /> : <Circle className="size-3" fill={active ? 'currentColor' : 'none'} />}
            </span>
            <span>{stage}</span>
          </li>
        )
      })}
    </ol>
  )
}
