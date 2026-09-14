import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useMemo, useRef, useState, type FormEvent } from 'react'
import { useBeforeUnload } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { BatchCollectorImportResult, CollectionDetail } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { inspectSourceUrls } from '@/features/collectors/new-collector-page'

export function CollectionSourceDialog({ requirement, onClose, onCreated, onRestoreFocus }: {
  requirement: CollectionDetail; onClose: () => void; onCreated: () => void; onRestoreFocus: () => void
}) {
  const { t } = useTranslation('common')
  const client = useQueryClient()
  const [input, setInput] = useState('')
  const [discarding, setDiscarding] = useState(false)
  const [result, setResult] = useState<BatchCollectorImportResult | null>(null)
  const submission = useRef<{ body: string; key: string } | null>(null)
  const sources = useMemo(() => inspectSourceUrls(input), [input])
  const valid = sources.length > 0 && sources.every(source => source.status === 'valid')
  useBeforeUnload(event => { if (input.trim()) { event.preventDefault(); event.returnValue = '' } })
  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        collectionId: requirement.id,
        collectionName: requirement.name,
        intent: requirement.intent,
        sources: sources.map(source => ({ entryUrl: source.normalized!, mode: 'exact' as const })),
      }
      const body = JSON.stringify(payload)
      if (submission.current?.body !== body) submission.current = { body, key: crypto.randomUUID() }
      return api.createCollectors(payload, submission.current.key)
    },
    onSuccess: async value => {
      setResult(value)
      submission.current = null
      // Retain only rejected rows so partial batches cannot resubmit created sources.
      setInput(value.results.filter(item => item.status === 'rejected').map(item => item.sourceUrl).join('\n'))
      await client.invalidateQueries({ queryKey: ['collections'] })
      await client.invalidateQueries({ queryKey: ['collectors'] })
      await client.invalidateQueries({ queryKey: ['collection', requirement.id] })
      if (value.createdCount > 0) onCreated()
      if (value.createdCount > 0 && value.rejectedCount === 0) onClose()
    },
  })
  function close() {
    if (mutation.isPending) return
    if (input.trim()) setDiscarding(true)
    else onClose()
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (valid && !mutation.isPending && requirement.status === 'active') mutation.mutate()
  }
  return <Dialog open onOpenChange={open => { if (!open) close() }}>
    <DialogContent className="collection-source-dialog" showCloseButton={!mutation.isPending} onInteractOutside={event => event.preventDefault()} onCloseAutoFocus={event => { event.preventDefault(); onRestoreFocus() }}>
      <DialogHeader><DialogTitle>{t('collections.addSource')}</DialogTitle><DialogDescription className="collection-source-target">{requirement.name}</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="collection-source-form">
        <div className="collection-source-body">
          <label className="field-group" htmlFor="collection-source-urls"><span>{t('collectors:create.sources.manualLabel')}</span><Textarea id="collection-source-urls" autoFocus rows={6} disabled={mutation.isPending} value={input} onChange={event => { setInput(event.target.value); setDiscarding(false) }} placeholder="https://example.com/notices" /></label>
          {sources.length > 0 && <ul className="collection-source-checks" aria-label={t('collectors:create.sources.heading')}>
            {sources.map(source => <li key={source.id}><code>{source.raw}</code><span className={source.status === 'valid' ? '' : 'field-error'}>{source.status === 'valid' ? t('collections.sourceFormatValid') : source.message}</span></li>)}
          </ul>}
          {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}
          {result && <div role="status">
            <p>{t('collections.sourceResult', { created: result.createdCount, rejected: result.rejectedCount })}</p>
            {result.results.filter(item => item.status === 'rejected').map((item, index) => <Alert key={index} variant="destructive"><AlertDescription><code className="block">{item.sourceUrl}</code><span className="block">{item.error?.message}</span></AlertDescription></Alert>)}
          </div>}
          {discarding && <Alert><AlertDescription>{t('collectors:leave.description')}</AlertDescription></Alert>}
        </div>
        <DialogFooter>
          {discarding ? <><Button type="button" variant="outline" onClick={() => setDiscarding(false)}>{t('fields.keepEditing')}</Button><Button type="button" variant="destructive" onClick={onClose}>{t('fields.discardLeave')}</Button></>
            : <><Button type="button" variant="outline" disabled={mutation.isPending} onClick={close}>{t('action.cancel')}</Button><Button type="submit" disabled={!valid || mutation.isPending || requirement.status !== 'active'}><Plus />{t(mutation.isPending ? 'collections.saving' : 'collections.addSource')}</Button></>}
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}
