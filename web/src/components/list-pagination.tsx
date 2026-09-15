import { ArrowRight, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import './list-pagination.css'

export const LIST_PAGE_SIZES = [20, 50, 100, 200] as const

type ListPaginationProps = {
  page: number
  pageSize: number
  total?: number
  totalPages?: number
  pending?: boolean
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function ListPagination({ page, pageSize, total, totalPages, pending, onPageChange, onPageSizeChange }: ListPaginationProps) {
  const { t } = useTranslation('common')
  const unavailable = total === undefined || totalPages === undefined
  const disabled = pending || unavailable
  const start = total ? (page - 1) * pageSize + 1 : 0
  const end = Math.min(page * pageSize, total ?? 0)
  const controls = [
    { label: 'first', icon: ChevronsLeft, target: 1, boundary: page <= 1 },
    { label: 'previous', icon: ChevronLeft, target: page - 1, boundary: page <= 1 },
    { label: 'next', icon: ChevronRight, target: page + 1, boundary: page >= (totalPages ?? page) },
    { label: 'last', icon: ChevronsRight, target: totalPages ?? page, boundary: page >= (totalPages ?? page) },
  ]

  return (
    <nav className="list-pagination" aria-label={t('pagination.aria')} aria-busy={pending}>
      <span className="list-pagination-range" aria-live="polite">{unavailable ? t('pagination.unavailable') : t('pagination.range', { start, end, total })}</span>
      <div className="list-pagination-controls">
        <label className="list-pagination-size">{t('pagination.pageSize')}
          <select aria-label={t('pagination.pageSize')} value={pageSize} disabled={pending} onChange={event => onPageSizeChange(Number(event.target.value))}>
            {LIST_PAGE_SIZES.map(size => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <div className="list-pagination-buttons">
          {controls.map(({ label, icon: Icon, target, boundary }) => (
            <Button key={label} variant="outline" size="icon-sm" title={t(`pagination.${label}`)} aria-label={t(`pagination.${label}`)} disabled={disabled || boundary} onClick={() => onPageChange(target)}><Icon /></Button>
          ))}
        </div>
        <form className="list-pagination-jump" onSubmit={event => {
          event.preventDefault()
          const target = Number(new FormData(event.currentTarget).get('page'))
          if (!disabled && Number.isSafeInteger(target) && target >= 1 && target <= totalPages! && target !== page) onPageChange(target)
        }}>
          <Input key={`${page}:${totalPages}`} name="page" type="number" min={1} max={totalPages} step={1} required defaultValue={page} disabled={disabled} aria-label={t('pagination.page')} />
          <span>{t('pagination.pages', { totalPages: totalPages ?? '—' })}</span>
          <Button type="submit" variant="ghost" size="icon-sm" disabled={disabled} aria-label={t('pagination.jump')} title={t('pagination.jump')}><ArrowRight /></Button>
        </form>
      </div>
    </nav>
  )
}
