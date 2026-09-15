import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { LoaderCircle, Plus, Save } from 'lucide-react'
import type { CollectionInput } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

export function CollectionForm({ initial, pending, onSave, onCancel, creating = false }: {
  creating?: boolean
  initial: CollectionInput; pending: boolean; onSave: (input: CollectionInput) => void; onCancel: () => void
}) {
  const { t } = useTranslation('common')
  const [name, setName] = useState(initial.name)
  const [intent, setIntent] = useState(initial.intent)
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || !intent.trim() || pending) return
    onSave({ name: name.trim(), intent: intent.trim() })
  }
  return <form className="collection-form" onSubmit={submit}>
    <div className="field-group"><label htmlFor="requirement-name">{t('collections.name')}</label><Input id="requirement-name" autoFocus required maxLength={200} value={name} disabled={pending} onChange={(event) => setName(event.target.value)} /></div>
    <div className="field-group"><label htmlFor="requirement-intent">{t('collections.intent')}</label><Textarea id="requirement-intent" required maxLength={10000} rows={7} value={intent} disabled={pending} onChange={(event) => setIntent(event.target.value)} /></div>
    <div className="collection-form-actions"><Button type="button" variant="outline" disabled={pending} onClick={onCancel}>{t('action.cancel')}</Button><Button type="submit" disabled={pending || !name.trim() || !intent.trim()}>{pending ? <LoaderCircle className="animate-spin" /> : creating ? <Plus /> : <Save />}{t(pending ? 'collections.saving' : creating ? 'collections.createSubmit' : 'collections.save')}</Button></div>
  </form>
}
