import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronDown, CircleAlert, Eye, EyeOff, KeyRound, MoreHorizontal, Pencil, Plus, Power, Star, Trash2, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiRequestError, api } from '@/api/client'
import type {
  CreateUserInput,
  ModelConfiguration,
  ModelConfigurationInput,
  ModelConfigurationItem,
  ModelConfigurationItemInput,
  ModelProvider,
  ModelProviderConfiguration,
  ModelProviderConfigurationInput,
  UpdateUserInput,
  User,
  UserRole,
} from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { APP_LANGUAGES, getAppLanguage, setAppLanguage, type AppLanguage } from '@/i18n/language'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type ProviderOption = { key: string; value: ModelProvider; labelKey: string; baseUrl: string }

const providerOptions: ProviderOption[] = [
  { key: 'openai', value: 'openai', labelKey: 'provider.typeOpenai', baseUrl: 'https://api.openai.com/v1' },
  { key: 'deepseek', value: 'deepseek', labelKey: 'provider.typeDeepseek', baseUrl: 'https://api.deepseek.com/v1' },
  { key: 'qwen', value: 'qwen', labelKey: 'provider.typeQwen', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { key: 'custom', value: 'custom', labelKey: 'provider.typeCustom', baseUrl: '' },
  { key: 'ollama', value: 'custom', labelKey: 'provider.typeOllama', baseUrl: 'http://127.0.0.1:11434/v1' },
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
  const { user: currentUser } = useAuth()
  const query = useQuery({ queryKey: ['model-configuration'], queryFn: api.modelConfiguration })
  const configuration = query.data ?? emptyConfiguration
  const providers = configuration.providers.map(providerInput)
  const models = configuration.models.map(modelInput)
  const [providerDraft, setProviderDraft] = useState<ProviderDraft | null>(null)
  const [providerOptionKey, setProviderOptionKey] = useState<string>('openai')
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
    setProviderOptionKey(provider ? providerPreset(provider.provider).key : 'openai')
    setProviderDraft(provider ? providerInput(provider) : {
      id: nextId('provider'),
      name: t(preset.labelKey),
      provider: preset.value,
      baseUrl: preset.baseUrl,
      apiKey: '',
      enabled: true,
    })
  }

  function changeProviderType(optionKey: string) {
    if (!providerDraft) return
    const previous = providerOptions.find((option) => option.key === providerOptionKey) ?? providerPreset(providerDraft.provider)
    const next = providerOptions.find((option) => option.key === optionKey) ?? previous
    setProviderOptionKey(next.key)
    setProviderDraft({
      ...providerDraft,
      provider: next.value,
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

    {currentUser.role === 'administrator' && <UsersSection currentUserId={currentUser.id} />}

    <Dialog open={providerDraft !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setProviderDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader><DialogTitle>{configuration.providers.some((provider) => provider.id === providerDraft?.id) ? t('provider.edit') : t('provider.add')}</DialogTitle><DialogDescription>{t('dialog.providerDescription')}</DialogDescription></DialogHeader>
        {providerDraft && <form id="provider-settings-form" className="settings-dialog-form" onSubmit={saveProvider}>
          <div className="field-group"><label htmlFor="provider-name">{t('dialog.nameLabel')}</label><Input id="provider-name" value={providerDraft.name} onChange={(event) => setProviderDraft({ ...providerDraft, name: event.target.value })} required autoFocus /></div>
          <div className="field-group"><label htmlFor="provider-type">{t('dialog.providerLabel')}</label><Select value={providerOptionKey} onValueChange={changeProviderType}><SelectTrigger id="provider-type" aria-label={t('dialog.providerLabel')}><SelectValue /></SelectTrigger><SelectContent>{providerOptions.map((option) => <SelectItem key={option.key} value={option.key}>{t(option.labelKey)}</SelectItem>)}</SelectContent></Select></div>
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

const USER_ROLE_OPTIONS: UserRole[] = ['administrator', 'engineer', 'reviewer', 'viewer']

type UserDraft = { id: string | null; username: string; displayName: string; password: string; role: UserRole; enabled: boolean }

function UsersSection({ currentUserId }: { currentUserId: string }) {
  const { t } = useTranslation(['settings', 'common'])
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['users'], queryFn: api.users })
  const users = query.data ?? []
  const activeAdministratorCount = users.filter((row) => row.role === 'administrator' && row.enabled).length
  const [userDraft, setUserDraft] = useState<UserDraft | null>(null)
  const [showUserPassword, setShowUserPassword] = useState(false)
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [toggleTarget, setToggleTarget] = useState<User | null>(null)

  const isLastActiveAdministrator = (row: User) => row.role === 'administrator' && row.enabled && activeAdministratorCount <= 1
  const isSelf = (row: User) => row.id === currentUserId
  const editTarget = userDraft?.id ? users.find((row) => row.id === userDraft.id) ?? null : null

  function actionError(reason: unknown) {
    if (reason instanceof ApiRequestError) return t(`users.errors.${reason.code}`, { defaultValue: reason.message })
    return reason instanceof Error ? reason.message : t('common:state.error')
  }

  const createMutation = useMutation({
    mutationFn: (input: CreateUserInput) => api.createUser(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setUserDraft(null)
    },
  })
  const updateMutation = useMutation({
    mutationFn: ({ userId, input }: { userId: string; input: UpdateUserInput }) => api.updateUser(userId, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
  const pending = createMutation.isPending || updateMutation.isPending

  function openCreateUser() {
    setShowUserPassword(false)
    setUserDraft({ id: null, username: '', displayName: '', password: '', role: 'engineer', enabled: true })
  }

  function openEditUser(row: User) {
    setUserDraft({ id: row.id, username: row.username, displayName: row.displayName, password: '', role: row.role, enabled: row.enabled })
  }

  function openResetPassword(row: User) {
    setNewPassword('')
    setShowUserPassword(false)
    setPasswordTarget(row)
  }

  function saveUser(event: FormEvent) {
    event.preventDefault()
    if (!userDraft) return
    if (userDraft.id) {
      updateMutation.mutate(
        { userId: userDraft.id, input: { displayName: userDraft.displayName.trim() || undefined, role: userDraft.role, enabled: userDraft.enabled } },
        { onSuccess: () => setUserDraft(null) },
      )
      return
    }
    createMutation.mutate({
      username: userDraft.username,
      password: userDraft.password,
      displayName: userDraft.displayName.trim() || undefined,
      role: userDraft.role,
    })
  }

  function saveNewPassword(event: FormEvent) {
    event.preventDefault()
    if (!passwordTarget || newPassword.length < 8) return
    updateMutation.mutate(
      { userId: passwordTarget.id, input: { password: newPassword } },
      { onSuccess: () => setPasswordTarget(null) },
    )
  }

  function confirmToggle() {
    if (!toggleTarget) return
    updateMutation.mutate(
      { userId: toggleTarget.id, input: { enabled: !toggleTarget.enabled } },
      { onSuccess: () => setToggleTarget(null) },
    )
  }

  const toggleActionLabel = toggleTarget?.enabled ? t('users.actions.disable') : t('users.actions.enable')

  return <section className="settings-users" aria-label={t('users.listAria')}>
    <header className="settings-users-toolbar">
      <div>
        <h2><Users aria-hidden="true" />{t('users.title')}</h2>
        <p>{t('users.description')}</p>
      </div>
      <Button onClick={() => openCreateUser()}><Plus />{t('users.add')}</Button>
    </header>

    {query.isError && <Alert variant="destructive"><AlertDescription>{query.error.message}</AlertDescription></Alert>}
    {createMutation.error && <Alert variant="destructive"><AlertDescription>{actionError(createMutation.error)}</AlertDescription></Alert>}
    {updateMutation.error && <Alert variant="destructive"><AlertDescription>{actionError(updateMutation.error)}</AlertDescription></Alert>}

    <div className="settings-users-head" aria-hidden="true">
      <span>{t('users.columns.username')}</span>
      <span>{t('users.columns.role')}</span>
      <span>{t('users.columns.status')}</span>
      <span>{t('users.columns.updatedAt')}</span>
      <span>{t('users.columns.actions')}</span>
    </div>
    {users.map((row) => {
      const rowLocked = isLastActiveAdministrator(row)
      const toggleDisabled = rowLocked || isSelf(row)
      return <div className="settings-users-row" key={row.id}>
        <span className="settings-users-identity"><strong>{row.username}</strong><small>{row.displayName}</small></span>
        <span className="role-pill">{t(`roles.${row.role}`, { ns: 'common' })}</span>
        <span className={`settings-status ${row.enabled ? 'success' : 'muted'}`}>{row.enabled ? t('users.enabled') : t('users.disabled')}</span>
        <span className="settings-users-updated">{row.updatedAt.slice(0, 10)}</span>
        <span className="settings-users-actions">
          <Button variant="ghost" size="sm" className="settings-provider-add-model" onClick={() => openEditUser(row)} aria-label={t('users.actions.editAria', { name: row.username })}><Pencil />{t('users.actions.edit')}</Button>
          <Button variant="ghost" size="sm" className="settings-provider-add-model" onClick={() => openResetPassword(row)} aria-label={t('users.actions.resetAria', { name: row.username })}><KeyRound />{t('users.actions.resetPassword')}</Button>
          <Button
            variant="ghost"
            size="sm"
            className="settings-provider-add-model"
            disabled={toggleDisabled}
            title={isSelf(row) ? t('users.selfHint') : rowLocked ? t('users.lastAdminHint') : undefined}
            onClick={() => setToggleTarget(row)}
            aria-label={row.enabled ? t('users.actions.disableAria', { name: row.username }) : t('users.actions.enableAria', { name: row.username })}
          ><Power />{row.enabled ? t('users.actions.disable') : t('users.actions.enable')}</Button>
        </span>
      </div>
    })}
    {!query.isLoading && users.length === 0 && <div className="settings-users-none">{t('users.empty')}</div>}

    <Dialog open={userDraft !== null} onOpenChange={(open) => { if (!open && !pending) setUserDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader>
          <DialogTitle>{userDraft?.id ? t('users.dialog.editTitle') : t('users.dialog.addTitle')}</DialogTitle>
          <DialogDescription>{userDraft?.id ? t('users.dialog.editDescription') : t('users.dialog.addDescription')}</DialogDescription>
        </DialogHeader>
        {userDraft && <form id="user-settings-form" className="settings-dialog-form" onSubmit={saveUser}>
          <div className="field-group">
            <label htmlFor="user-username">{t('users.dialog.usernameLabel')}</label>
            {userDraft.id
              ? <Input id="user-username" value={userDraft.username} disabled />
              : <Input id="user-username" value={userDraft.username} onChange={(event) => setUserDraft({ ...userDraft, username: event.target.value })} placeholder={t('users.dialog.usernamePlaceholder')} minLength={3} maxLength={64} required autoFocus />}
          </div>
          <div className="field-group">
            <label htmlFor="user-display-name">{t('users.dialog.displayNameLabel')}</label>
            <Input id="user-display-name" value={userDraft.displayName} onChange={(event) => setUserDraft({ ...userDraft, displayName: event.target.value })} placeholder={t('users.dialog.displayNamePlaceholder')} maxLength={64} />
          </div>
          {!userDraft.id && <div className="field-group">
            <label htmlFor="user-password">{t('users.dialog.passwordLabel')}</label>
            <div className="credential-input">
              <KeyRound />
              <Input
                id="user-password"
                type={showUserPassword ? 'text' : 'password'}
                value={userDraft.password}
                onChange={(event) => setUserDraft({ ...userDraft, password: event.target.value })}
                placeholder={t('users.dialog.passwordPlaceholder')}
                autoComplete="new-password"
                minLength={8}
                maxLength={256}
                required
              />
              <Button type="button" variant="ghost" size="icon-sm" title={showUserPassword ? t('users.dialog.hidePassword') : t('users.dialog.showPassword')} aria-label={showUserPassword ? t('users.dialog.hidePassword') : t('users.dialog.showPassword')} onClick={() => setShowUserPassword((visible) => !visible)}>
                {showUserPassword ? <EyeOff /> : <Eye />}
              </Button>
            </div>
          </div>}
          <div className="field-group">
            <label htmlFor="user-role">{t('users.dialog.roleLabel')}</label>
            <Select value={userDraft.role} onValueChange={(value) => setUserDraft({ ...userDraft, role: value as UserRole })} disabled={Boolean(editTarget && isLastActiveAdministrator(editTarget))}>
              <SelectTrigger id="user-role" aria-label={t('users.dialog.roleLabel')}><SelectValue /></SelectTrigger>
              <SelectContent>
                {USER_ROLE_OPTIONS.map((role) => <SelectItem key={role} value={role}>{t(`roles.${role}`, { ns: 'common' })}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {userDraft.id && <label className="settings-checkbox">
            <Checkbox
              checked={userDraft.enabled}
              disabled={Boolean(editTarget && (isLastActiveAdministrator(editTarget) || isSelf(editTarget)))}
              onCheckedChange={(checked) => setUserDraft({ ...userDraft, enabled: checked === true })}
            />
            {t('users.dialog.enabledLabel')}
          </label>}
          {editTarget && (isLastActiveAdministrator(editTarget) || isSelf(editTarget)) && <small className="credential-help">{isLastActiveAdministrator(editTarget) ? t('users.lastAdminHint') : t('users.selfHint')}</small>}
        </form>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setUserDraft(null)} disabled={pending}>{t('common:action.cancel')}</Button>
          <Button type="submit" form="user-settings-form" disabled={pending}>{pending ? t('users.dialog.saving') : userDraft?.id ? t('users.dialog.save') : t('users.dialog.saveNew')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={passwordTarget !== null} onOpenChange={(open) => { if (!open && !updateMutation.isPending) setPasswordTarget(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader>
          <DialogTitle>{t('users.dialog.resetTitle')}</DialogTitle>
          <DialogDescription>{t('users.dialog.resetDescription')}</DialogDescription>
        </DialogHeader>
        <form id="user-password-form" className="settings-dialog-form" onSubmit={saveNewPassword}>
          <div className="field-group">
            <label htmlFor="user-new-password">{t('users.dialog.newPasswordLabel')}</label>
            <div className="credential-input">
              <KeyRound />
              <Input
                id="user-new-password"
                type={showUserPassword ? 'text' : 'password'}
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder={t('users.dialog.newPasswordPlaceholder')}
                autoComplete="new-password"
                minLength={8}
                maxLength={256}
                required
                autoFocus
              />
              <Button type="button" variant="ghost" size="icon-sm" title={showUserPassword ? t('users.dialog.hidePassword') : t('users.dialog.showPassword')} aria-label={showUserPassword ? t('users.dialog.hidePassword') : t('users.dialog.showPassword')} onClick={() => setShowUserPassword((visible) => !visible)}>
                {showUserPassword ? <EyeOff /> : <Eye />}
              </Button>
            </div>
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => setPasswordTarget(null)} disabled={updateMutation.isPending}>{t('common:action.cancel')}</Button>
          <Button type="submit" form="user-password-form" disabled={updateMutation.isPending}>{updateMutation.isPending ? t('users.dialog.resetting') : t('users.dialog.reset')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={toggleTarget !== null} onOpenChange={(open) => { if (!open && !updateMutation.isPending) setToggleTarget(null) }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('users.dialog.toggleTitle', { action: toggleActionLabel })}</DialogTitle>
          <DialogDescription>{t('users.dialog.toggleDescription', { action: toggleActionLabel, name: toggleTarget?.displayName ?? '' })}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setToggleTarget(null)} disabled={updateMutation.isPending}>{t('common:action.cancel')}</Button>
          <Button variant={toggleTarget?.enabled ? 'destructive' : 'default'} onClick={confirmToggle} disabled={updateMutation.isPending}>{t('users.dialog.toggleAction')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </section>
}
