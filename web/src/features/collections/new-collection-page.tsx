import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useRef } from 'react'
import { api } from '@/api/client'
import type { CollectionInput } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CollectionForm } from './collection-form'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { CollectionsPage } from './collections-page'
import './new-collection.css'

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
  const close = () => { if (!mutation.isPending) navigate('/collections') }
  return <>
    <CollectionsPage />
    <Dialog open onOpenChange={(open) => { if (!open) close() }}>
    <DialogContent className="collection-create-dialog" aria-describedby={undefined} showCloseButton={!mutation.isPending} onInteractOutside={(event) => event.preventDefault()} onEscapeKeyDown={(event) => { if (mutation.isPending) event.preventDefault() }}>
    <DialogHeader><DialogTitle>{t('collections.create')}</DialogTitle></DialogHeader>
    {user.role !== 'administrator' && user.role !== 'engineer'
      ? <Alert><AlertDescription>{t('collections.readOnly')}</AlertDescription></Alert>
      : <>{mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}
          <CollectionForm creating initial={{ name: '', intent: '' }} pending={mutation.isPending} onSave={(input) => mutation.mutate(input)} onCancel={close} />
      </>}
    </DialogContent>
    </Dialog>
  </>
}
