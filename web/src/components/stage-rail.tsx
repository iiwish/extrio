import { Check, Circle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

const stageKeys = ['design', 'explore', 'review', 'publish', 'run'] as const

export function StageRail({ current }: { current: number }) {
  const { t } = useTranslation('common')
  return (
    <ol className="stage-rail" aria-label={t('stage.railAria')}>
      {stageKeys.map((stageKey, index) => {
        const complete = index < current
        const active = index === current
        return (
          <li key={stageKey} className={cn('stage-item', active && 'is-active', complete && 'is-complete')}>
            <span className="stage-marker" aria-hidden="true">
              {complete ? <Check className="size-3.5" /> : <Circle className="size-3" fill={active ? 'currentColor' : 'none'} />}
            </span>
            <span>{t(`stage.${stageKey}`)}</span>
          </li>
        )
      })}
    </ol>
  )
}
