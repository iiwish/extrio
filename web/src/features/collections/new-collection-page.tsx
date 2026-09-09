import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useRef } from 'react'
import { api } from '@/api/client'
import type { CollectionInput } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CollectionForm } from './collection-form'

export function NewCollectionPage() {
  const { t } = useTranslation('common')
  const { user } = useAuth()
  const navigate = useNavigate()
  const client = useQueryClient()
  const submission = useRef<{ body: string; key: string } | null>(null)
  const mutation = useMutation({ mutationFn: (input: CollectionInput) => {
    const body = JSON.stringify(input)
    if (submission.current?.body !== body) submission.current = { body, key: crypto.randomUUID() }
    return api.createCollection(input, submission.current.key)
  }, onSuccess: (value) => {
    client.invalidateQueries({ queryKey: ['collections'] })
    navigate(`/collections/${encodeURIComponent(value.id)}`)
  } })
  return <div className="page-frame collection-new-page">
    <h1>{t('collections.create')}</h1>
    {user.role !== 'administrator' && user.role !== 'engineer'
      ? <Alert><AlertDescription>{t('collections.readOnly')}</AlertDescription></Alert>
      : <>{mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}
        <CollectionForm initial={{ name: '', intent: '' }} pending={mutation.isPending} onSave={(input) => mutation.mutate(input)} onCancel={() => navigate('/collections')} />
      </>}
  </div>
}
