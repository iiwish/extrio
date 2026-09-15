import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { NumberedPagination } from '@/api/types'
import { LIST_PAGE_SIZES } from '@/components/list-pagination'

type PageResult = { total?: number; pagination?: NumberedPagination }

export function useListQuery<T extends PageResult>({ queryKey, queryFn, enabled, refetchInterval }: {
  queryKey: QueryKey
  queryFn: (params: { page: number; limit: number }, signal: AbortSignal) => Promise<T>
  enabled?: boolean
  refetchInterval?: UseQueryOptions<T>['refetchInterval']
}) {
  const [params, setParams] = useSearchParams()
  const requested = Number(params.get('page') ?? 1)
  const page = Number.isSafeInteger(requested) && requested > 0 ? requested : 1
  const pageSize = LIST_PAGE_SIZES.find(size => size === Number(params.get('pageSize') ?? 50)) ?? 50
  const query = useQuery({ queryKey: [...queryKey, page, pageSize], queryFn: ({ signal }) => queryFn({ page, limit: pageSize }, signal), enabled, refetchInterval })
  const metadata = query.data?.pagination
  useEffect(() => {
    if (metadata && metadata.page !== page && enabled !== false) {
      const next = new URLSearchParams(params)
      if (metadata.page === 1) next.delete('page')
      else next.set('page', String(metadata.page))
      setParams(next, { replace: true })
    }
  }, [metadata, page, params, setParams, enabled])

  function updateParams(updates: Record<string, string | null>, replace = false) {
    const next = new URLSearchParams(params)
    if (!Object.hasOwn(updates, 'page')) next.delete('page')
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace })
  }

  return { query, params, updateParams, resetKey: params.toString(), pagination: {
    page: metadata?.page ?? page, pageSize, total: metadata?.total, totalPages: metadata?.totalPages,
    pending: query.isFetching,
    onPageChange: (value: number) => updateParams({ page: value === 1 ? null : String(value) }),
    onPageSizeChange: (value: number) => updateParams({ pageSize: value === 50 ? null : String(value) }),
  } }
}
