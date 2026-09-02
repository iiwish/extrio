import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronDown, CircleAlert, Eye, EyeOff, KeyRound, MoreHorizontal, Pencil, Plus, Power, Star, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type {
  ModelConfiguration,
  ModelConfigurationInput,
  ModelConfigurationItem,
  ModelConfigurationItemInput,
  ModelProvider,
  ModelProviderConfiguration,
  ModelProviderConfigurationInput,
} from '@/api/types'
import { APP_LANGUAGES, getAppLanguage, setAppLanguage, type AppLanguage } from '@/i18n/language'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const providerOptions: Array<{ value: ModelProvider; labelKey: string; baseUrl: string }> = [
  { value: 'openai', labelKey: 'provider.typeOpenai', baseUrl: 'https://api.openai.com/v1' },
  { value: 'deepseek', labelKey: 'provider.typeDeepseek', baseUrl: 'https://api.deepseek.com/v1' },
  { value: 'qwen', labelKey: 'provider.typeQwen', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'custom', labelKey: 'provider.typeCustom', baseUrl: '' },
]

export function providerPreset(provider: ModelProvider) {
  return providerOptions.find((option) => option.value === provider) ?? providerOptions[0]
}

const emptyConfiguration: ModelConfiguration = { providers: [], models: [], defaultModelId: null, updatedAt: null }
type ProviderDraft = ModelProviderConfigurationInput
type ModelDraft = ModelConfigurationItemInput
type DeleteTarget = { type: 'provider' | 'model'; id: string; label: string } | null

function configurationInput(providers: ProviderDraft[], models: ModelDraft[], defaultModelId: string | null): ModelConfigurationInput {
  return { providers, models, defaultModelId }
}

function providerInput(provider: ModelProviderConfiguration): ProviderDraft {
  return { id: provider.id, name: provider.name, provider: provider.provider, baseUrl: provider.baseUrl, enabled: provider.enabled }
}

function modelInput(model: ModelConfigurationItem): ModelDraft {
  return { id: model.id, providerId: model.providerId, modelId: model.modelId, enabled: model.enabled }
}

function nextId(prefix: 'provider' | 'model') {
  return `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`
}

function availableModelIds(providers: ProviderDraft[], models: ModelDraft[]) {
  const enabledProviders = new Set(providers.filter((provider) => provider.enabled).map((provider) => provider.id))
  return models.filter((model) => model.enabled && enabledProviders.has(model.providerId)).map((model) => model.id)
}

function validDefaultModelId(providers: ProviderDraft[], models: ModelDraft[], preferred: string | null) {
  const available = availableModelIds(providers, models)
  return preferred && available.includes(preferred) ? preferred : available[0] ?? null
}

function Status({ enabled, ready }: { enabled: boolean; ready?: boolean }) {
  const { t } = useTranslation('settings')
  if (!enabled) return <span className="settings-status muted">{t('status.disabled')}</span>
  if (ready === false) return <span className="settings-status warning"><CircleAlert />{t('status.awaitingKey')}</span>
  return <span className="settings-status success"><Check />{t('status.enabled')}</span>
}

export function ModelSettingsPage() {
  const { t } = useTranslation('settings')
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['model-configuration'], queryFn: api.modelConfiguration })
  const configuration = query.data ?? emptyConfiguration
  const providers = configuration.providers.map(providerInput)
  const models = configuration.models.map(modelInput)
  const [providerDraft, setProviderDraft] = useState<ProviderDraft | null>(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [modelDraft, setModelDraft] = useState<ModelDraft | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null)
  const [collapsedProviderIds, setCollapsedProviderIds] = useState<Set<string>>(new Set())

  const mutation = useMutation({
    mutationFn: api.updateModelConfiguration,
    onSuccess: (value) => queryClient.setQueryData(['model-configuration'], value),
  })

  function persist(input: ModelConfigurationInput, onSuccess?: () => void) {
    mutation.mutate(input, { onSuccess })
  }

  function openProvider(provider?: ModelProviderConfiguration) {
    const preset = providerPreset('openai')
    setShowApiKey(false)
    setProviderDraft(provider ? providerInput(provider) : {
      id: nextId('provider'),
      name: t(preset.labelKey),
      provider: preset.value,
      baseUrl: preset.baseUrl,
      apiKey: '',
      enabled: true,
    })
  }

  function changeProviderType(provider: ModelProvider) {
    if (!providerDraft) return
    const previous = providerPreset(providerDraft.provider)
    const next = providerPreset(provider)
    setProviderDraft({
      ...providerDraft,
      provider,
      name: providerDraft.name === t(previous.labelKey) ? t(next.labelKey) : providerDraft.name,
      baseUrl: !providerDraft.baseUrl || providerDraft.baseUrl === previous.baseUrl ? next.baseUrl : providerDraft.baseUrl,
    })
  }

  function saveProvider(event: FormEvent) {
    event.preventDefault()
    if (!providerDraft) return
    const nextDraft = { ...providerDraft, apiKey: providerDraft.apiKey?.trim() || undefined }
    const nextProviders = providers.some((provider) => provider.id === providerDraft.id)
      ? providers.map((provider) => provider.id === providerDraft.id ? nextDraft : provider)
      : [...providers, nextDraft]
    persist(configurationInput(nextProviders, models, validDefaultModelId(nextProviders, models, configuration.defaultModelId)), () => setProviderDraft(null))
  }

  function openModel(model?: ModelConfigurationItem, providerId?: string) {
    const firstProviderId = providerId ?? providers[0]?.id
    if (!firstProviderId) {
      openProvider()
      return
    }
    setModelDraft(model ? modelInput(model) : { id: nextId('model'), providerId: firstProviderId, modelId: '', enabled: true })
  }

  function saveModel(event: FormEvent) {
    event.preventDefault()
    if (!modelDraft) return
    const nextModels = models.some((model) => model.id === modelDraft.id)
      ? models.map((model) => model.id === modelDraft.id ? modelDraft : model)
      : [...models, modelDraft]
    persist(configurationInput(providers, nextModels, validDefaultModelId(providers, nextModels, configuration.defaultModelId)), () => setModelDraft(null))
  }

  function toggleProvider(provider: ModelProviderConfiguration) {
    const nextProviders = providers.map((row) => row.id === provider.id ? { ...row, enabled: !row.enabled } : row)
    persist(configurationInput(nextProviders, models, validDefaultModelId(nextProviders, models, configuration.defaultModelId)))
  }

  function toggleModel(model: ModelConfigurationItem) {
    const nextModels = models.map((row) => row.id === model.id ? { ...row, enabled: !row.enabled } : row)
    persist(configurationInput(providers, nextModels, validDefaultModelId(providers, nextModels, configuration.defaultModelId)))
  }

  function toggleProviderModels(providerId: string) {
    setCollapsedProviderIds((current) => {
      const next = new Set(current)
      if (next.has(providerId)) next.delete(providerId)
      else next.add(providerId)
      return next
    })
  }

  function confirmDelete() {
    if (!deleteTarget) return
    if (deleteTarget.type === 'provider') {
      const nextProviders = providers.filter((provider) => provider.id !== deleteTarget.id)
      const nextModels = models.filter((model) => model.providerId !== deleteTarget.id)
      persist(configurationInput(nextProviders, nextModels, validDefaultModelId(nextProviders, nextModels, configuration.defaultModelId)), () => setDeleteTarget(null))
      return
    }
    const nextModels = models.filter((model) => model.id !== deleteTarget.id)
    persist(configurationInput(providers, nextModels, validDefaultModelId(providers, nextModels, configuration.defaultModelId)), () => setDeleteTarget(null))
  }

  const availableModels = configuration.models.filter((model) => {
    const provider = configuration.providers.find((row) => row.id === model.providerId)
    return model.enabled && provider?.enabled
  })

  return <div className="page-frame settings-page">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <label className="field-group grid-flow-col items-center">
        <span>{t('language.label')}</span>
        <Select value={getAppLanguage()} onValueChange={(value) => setAppLanguage(value as AppLanguage)}>
          <SelectTrigger aria-label={t('language.label')} className="h-7 w-36"><SelectValue /></SelectTrigger>
          <SelectContent>
            {APP_LANGUAGES.map((language) => <SelectItem key={language.code} value={language.code}>{language.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </label>
      <small className="credential-help">{t('language.description')}</small>
    </div>
    <div className="settings-ai-toolbar" aria-label={t('toolbar.overviewAria')}>
      <div className="settings-default-model">
        <span><Star />{t('toolbar.defaultModel')}</span>
        <Select value={configuration.defaultModelId ?? ''} onValueChange={(value) => persist(configurationInput(providers, models, value))} disabled={availableModels.length === 0 || mutation.isPending}>
          <SelectTrigger aria-label={t('toolbar.defaultModel')}><SelectValue placeholder={t('toolbar.defaultModelPlaceholder')} /></SelectTrigger>
          <SelectContent align="end">
            {availableModels.map((model) => {
              const provider = configuration.providers.find((row) => row.id === model.providerId)
              return <SelectItem key={model.id} value={model.id}>{provider?.name} · {model.modelId}</SelectItem>
            })}
          </SelectContent>
        </Select>
      </div>
      <Button onClick={() => openProvider()}><Plus />{t('provider.add')}</Button>
    </div>

    {query.isError && <Alert variant="destructive"><AlertDescription>{query.error.message}</AlertDescription></Alert>}
    {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}

    <div className="settings-provider-list" aria-label={t('toolbar.providerListAria')}>
      {configuration.providers.map((provider) => {
        const providerModels = configuration.models.filter((model) => model.providerId === provider.id)
        const collapsed = collapsedProviderIds.has(provider.id)
        return <section className={`settings-provider-group${collapsed ? ' is-collapsed' : ''}`} key={provider.id} aria-label={t('provider.groupAria', { name: provider.name })}>
          <header className="settings-provider-row">
            <button type="button" className="settings-provider-collapse" aria-label={collapsed ? t('provider.expandModelsAria', { name: provider.name }) : t('provider.collapseModelsAria', { name: provider.name })} aria-expanded={!collapsed} onClick={() => toggleProviderModels(provider.id)}><ChevronDown /></button>
            <span className="settings-provider-icon"><Bot /></span>
            <span className="settings-provider-identity"><strong>{provider.name}</strong><small title={provider.baseUrl}>{t(providerPreset(provider.provider).labelKey)} · {provider.baseUrl}</small></span>
            <Status enabled={provider.enabled} ready={provider.credentialConfigured} />
            <span className={`settings-secret${provider.credentialConfigured ? '' : ' warning'}`}><KeyRound />{provider.credentialConfigured ? t('provider.credentialConfigured') : t('provider.credentialMissing')}</span>
            <span className="settings-provider-count">{t('provider.modelCount', { count: providerModels.length })}</span>
            <Button variant="outline" size="sm" className="settings-provider-add-model" onClick={() => openModel(undefined, provider.id)}><Plus />{t('model.add')}</Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={t('provider.actionsAria', { name: provider.name })}><MoreHorizontal /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => openProvider(provider)}><Pencil />{t('provider.edit')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => toggleProvider(provider)}><Power />{provider.enabled ? t('provider.disable') : t('provider.enable')}</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTarget({ type: 'provider', id: provider.id, label: provider.name })}><Trash2 />{t('provider.delete')}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </header>

          <div className="settings-model-rows" hidden={collapsed}>
            {providerModels.map((model) => {
              const usable = Boolean(model.enabled && provider.enabled)
              return <div className="settings-model-row" key={model.id}>
                <button type="button" className={`settings-model-default${model.isDefault ? ' is-active' : ''}`} aria-label={model.isDefault ? t('model.isDefaultAria', { name: model.modelId }) : t('model.setAsDefaultAria', { name: model.modelId })} disabled={!usable} onClick={() => persist(configurationInput(providers, models, model.id))}><Star /></button>
                <span className="settings-model-identity"><strong>{model.modelId}</strong><small>{model.isDefault ? t('model.defaultTag') : t('model.tag')}</small></span>
                <Status enabled={usable} />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={t('model.actionsAria', { name: model.modelId })}><MoreHorizontal /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => openModel(model)}><Pencil />{t('model.edit')}</DropdownMenuItem>
                    {!model.isDefault && <DropdownMenuItem disabled={!usable} onSelect={() => persist(configurationInput(providers, models, model.id))}><Star />{t('model.setAsDefault')}</DropdownMenuItem>}
                    <DropdownMenuItem onSelect={() => toggleModel(model)}><Power />{model.enabled ? t('model.disable') : t('model.enable')}</DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTarget({ type: 'model', id: model.id, label: model.modelId })}><Trash2 />{t('model.delete')}</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            })}
            {providerModels.length === 0 && <div className="settings-model-empty"><span>{t('model.empty')}</span></div>}
          </div>
        </section>
      })}
      {!query.isLoading && configuration.providers.length === 0 && <div className="settings-empty"><Bot /><strong>{t('provider.emptyTitle')}</strong><Button onClick={() => openProvider()}><Plus />{t('provider.add')}</Button></div>}
    </div>

    <Dialog open={providerDraft !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setProviderDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader><DialogTitle>{configuration.providers.some((provider) => provider.id === providerDraft?.id) ? t('provider.edit') : t('provider.add')}</DialogTitle><DialogDescription>{t('dialog.providerDescription')}</DialogDescription></DialogHeader>
        {providerDraft && <form id="provider-settings-form" className="settings-dialog-form" onSubmit={saveProvider}>
          <div className="field-group"><label htmlFor="provider-name">{t('dialog.nameLabel')}</label><Input id="provider-name" value={providerDraft.name} onChange={(event) => setProviderDraft({ ...providerDraft, name: event.target.value })} required autoFocus /></div>
          <div className="field-group"><label htmlFor="provider-type">{t('dialog.providerLabel')}</label><Select value={providerDraft.provider} onValueChange={(value) => changeProviderType(value as ModelProvider)}><SelectTrigger id="provider-type" aria-label={t('dialog.providerLabel')}><SelectValue /></SelectTrigger><SelectContent>{providerOptions.map((option) => <SelectItem key={option.value} value={option.value}>{t(option.labelKey)}</SelectItem>)}</SelectContent></Select></div>
          <div className="field-group"><label htmlFor="provider-base-url">{t('dialog.baseUrlLabel')}</label><Input id="provider-base-url" type="url" value={providerDraft.baseUrl} onChange={(event) => setProviderDraft({ ...providerDraft, baseUrl: event.target.value })} placeholder="https://api.example.com/v1" required /></div>
          <div className="field-group">
            <label htmlFor="provider-api-key">{t('dialog.apiKeyLabel')}</label>
            <div className="credential-input">
              <KeyRound />
              <Input
                id="provider-api-key"
                type={showApiKey ? 'text' : 'password'}
                value={providerDraft.apiKey ?? ''}
                onChange={(event) => setProviderDraft({ ...providerDraft, apiKey: event.target.value })}
                placeholder={configuration.providers.some((provider) => provider.id === providerDraft.id) ? t('dialog.apiKeyKeepPlaceholder') : t('dialog.apiKeyPlaceholder')}
                autoComplete="new-password"
                required={!configuration.providers.some((provider) => provider.id === providerDraft.id)}
              />
              <Button type="button" variant="ghost" size="icon-sm" title={showApiKey ? t('dialog.hideApiKey') : t('dialog.showApiKey')} aria-label={showApiKey ? t('dialog.hideApiKey') : t('dialog.showApiKey')} onClick={() => setShowApiKey((visible) => !visible)}>
                {showApiKey ? <EyeOff /> : <Eye />}
              </Button>
            </div>
            <small className="credential-help">{configuration.providers.some((provider) => provider.id === providerDraft.id) && configuration.providers.find((provider) => provider.id === providerDraft.id)?.credentialConfigured ? t('dialog.apiKeyConfiguredHelp') : t('dialog.apiKeyHelp')}</small>
          </div>
          <label className="settings-checkbox"><Checkbox checked={providerDraft.enabled} onCheckedChange={(checked) => setProviderDraft({ ...providerDraft, enabled: checked === true })} />{t('dialog.enableProvider')}</label>
        </form>}
        <DialogFooter><Button variant="outline" onClick={() => setProviderDraft(null)} disabled={mutation.isPending}>{t('common:action.cancel')}</Button><Button type="submit" form="provider-settings-form" disabled={mutation.isPending}>{mutation.isPending ? t('dialog.saving') : t('dialog.saveProvider')}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={modelDraft !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setModelDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader><DialogTitle>{configuration.models.some((model) => model.id === modelDraft?.id) ? t('model.edit') : t('model.add')}</DialogTitle><DialogDescription>{t('dialog.modelDescription')}</DialogDescription></DialogHeader>
        {modelDraft && <form id="model-settings-form" className="settings-dialog-form" onSubmit={saveModel}>
          <div className="field-group"><label htmlFor="model-provider">{t('dialog.providerLabel')}</label><Select value={modelDraft.providerId} onValueChange={(value) => setModelDraft({ ...modelDraft, providerId: value })}><SelectTrigger id="model-provider" aria-label={t('dialog.modelProviderAria')}><SelectValue /></SelectTrigger><SelectContent>{configuration.providers.map((provider) => <SelectItem key={provider.id} value={provider.id}>{provider.name}</SelectItem>)}</SelectContent></Select></div>
          <div className="field-group"><label htmlFor="model-id">{t('dialog.modelIdLabel')}</label><Input id="model-id" value={modelDraft.modelId} onChange={(event) => setModelDraft({ ...modelDraft, modelId: event.target.value })} placeholder={t('dialog.modelIdPlaceholder')} required autoFocus /></div>
          <label className="settings-checkbox"><Checkbox checked={modelDraft.enabled} onCheckedChange={(checked) => setModelDraft({ ...modelDraft, enabled: checked === true })} />{t('dialog.enableModel')}</label>
        </form>}
        <DialogFooter><Button variant="outline" onClick={() => setModelDraft(null)} disabled={mutation.isPending}>{t('common:action.cancel')}</Button><Button type="submit" form="model-settings-form" disabled={mutation.isPending}>{mutation.isPending ? t('dialog.saving') : t('dialog.saveModel')}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setDeleteTarget(null) }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('dialog.deleteTitle')}</DialogTitle><DialogDescription>{t('dialog.deleteDescription', { name: deleteTarget?.label ?? '' })}</DialogDescription></DialogHeader>
        <DialogFooter><Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={mutation.isPending}>{t('common:action.cancel')}</Button><Button variant="destructive" onClick={confirmDelete} disabled={mutation.isPending}><Trash2 />{t('dialog.deleteAction')}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}
