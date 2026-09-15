import { CircleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

export function QueryError({ error, onRetry, retrying = false }: { error: unknown; onRetry: () => void; retrying?: boolean }) {
  const { t } = useTranslation('common')
  if (!error) return null
  return <div className="workspace-query-error" role="alert"><CircleAlert size={16} /><span>{error instanceof Error ? error.message : t('state.unavailable')}</span><Button size="sm" variant="outline" disabled={retrying} onClick={onRetry}>{t('action.retry')}</Button></div>
}
