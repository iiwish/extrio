import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronDown, CircleAlert, Eye, EyeOff, KeyRound, MoreHorizontal, Pencil, Plus, Power, Star, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
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
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const providerOptions: Array<{ value: ModelProvider; label: string; baseUrl: string }> = [
  { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
  { value: 'qwen', label: '阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'custom', label: 'OpenAI 兼容服务', baseUrl: '' },
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
  if (!enabled) return <span className="settings-status muted">已停用</span>
  if (ready === false) return <span className="settings-status warning"><CircleAlert />等待密钥</span>
  return <span className="settings-status success"><Check />已启用</span>
}

export function ModelSettingsPage() {
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
      name: preset.label,
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
      name: providerDraft.name === previous.label ? next.label : providerDraft.name,
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
    <div className="settings-ai-toolbar" aria-label="模型配置概况">
      <div className="settings-default-model">
        <span><Star />默认模型</span>
        <Select value={configuration.defaultModelId ?? ''} onValueChange={(value) => persist(configurationInput(providers, models, value))} disabled={availableModels.length === 0 || mutation.isPending}>
          <SelectTrigger aria-label="默认模型"><SelectValue placeholder="尚未配置" /></SelectTrigger>
          <SelectContent align="end">
            {availableModels.map((model) => {
              const provider = configuration.providers.find((row) => row.id === model.providerId)
              return <SelectItem key={model.id} value={model.id}>{provider?.name} · {model.modelId}</SelectItem>
            })}
          </SelectContent>
        </Select>
      </div>
      <Button onClick={() => openProvider()}><Plus />添加供应商</Button>
    </div>

    {query.isError && <Alert variant="destructive"><AlertDescription>{query.error.message}</AlertDescription></Alert>}
    {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}

    <div className="settings-provider-list" aria-label="供应商与模型">
      {configuration.providers.map((provider) => {
        const providerModels = configuration.models.filter((model) => model.providerId === provider.id)
        const collapsed = collapsedProviderIds.has(provider.id)
        return <section className={`settings-provider-group${collapsed ? ' is-collapsed' : ''}`} key={provider.id} aria-label={`${provider.name} 供应商`}>
          <header className="settings-provider-row">
            <button type="button" className="settings-provider-collapse" aria-label={`${collapsed ? '展开' : '折叠'} ${provider.name} 的模型`} aria-expanded={!collapsed} onClick={() => toggleProviderModels(provider.id)}><ChevronDown /></button>
            <span className="settings-provider-icon"><Bot /></span>
            <span className="settings-provider-identity"><strong>{provider.name}</strong><small title={provider.baseUrl}>{providerPreset(provider.provider).label} · {provider.baseUrl}</small></span>
            <Status enabled={provider.enabled} ready={provider.credentialConfigured} />
            <span className={`settings-secret${provider.credentialConfigured ? '' : ' warning'}`}><KeyRound />{provider.credentialConfigured ? '密钥已配置' : '未配置密钥'}</span>
            <span className="settings-provider-count">{providerModels.length} 个模型</span>
            <Button variant="outline" size="sm" className="settings-provider-add-model" onClick={() => openModel(undefined, provider.id)}><Plus />添加模型</Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${provider.name} 供应商操作`}><MoreHorizontal /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => openProvider(provider)}><Pencil />编辑供应商</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => toggleProvider(provider)}><Power />{provider.enabled ? '停用供应商' : '启用供应商'}</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTarget({ type: 'provider', id: provider.id, label: provider.name })}><Trash2 />删除供应商</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </header>

          <div className="settings-model-rows" hidden={collapsed}>
            {providerModels.map((model) => {
              const usable = Boolean(model.enabled && provider.enabled)
              return <div className="settings-model-row" key={model.id}>
                <button type="button" className={`settings-model-default${model.isDefault ? ' is-active' : ''}`} aria-label={model.isDefault ? `${model.modelId} 当前为默认模型` : `设 ${model.modelId} 为默认模型`} disabled={!usable} onClick={() => persist(configurationInput(providers, models, model.id))}><Star /></button>
                <span className="settings-model-identity"><strong>{model.modelId}</strong><small>{model.isDefault ? '默认模型' : '模型'}</small></span>
                <Status enabled={usable} />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${model.modelId} 模型操作`}><MoreHorizontal /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => openModel(model)}><Pencil />编辑模型</DropdownMenuItem>
                    {!model.isDefault && <DropdownMenuItem disabled={!usable} onSelect={() => persist(configurationInput(providers, models, model.id))}><Star />设为默认模型</DropdownMenuItem>}
                    <DropdownMenuItem onSelect={() => toggleModel(model)}><Power />{model.enabled ? '停用模型' : '启用模型'}</DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onSelect={() => setDeleteTarget({ type: 'model', id: model.id, label: model.modelId })}><Trash2 />删除模型</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            })}
            {providerModels.length === 0 && <div className="settings-model-empty"><span>暂无模型</span></div>}
          </div>
        </section>
      })}
      {!query.isLoading && configuration.providers.length === 0 && <div className="settings-empty"><Bot /><strong>尚未配置供应商</strong><Button onClick={() => openProvider()}><Plus />添加供应商</Button></div>}
    </div>

    <Dialog open={providerDraft !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setProviderDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader><DialogTitle>{configuration.providers.some((provider) => provider.id === providerDraft?.id) ? '编辑供应商' : '添加供应商'}</DialogTitle><DialogDescription>直接配置供应商凭据。密钥会加密保存，之后不会回显。</DialogDescription></DialogHeader>
        {providerDraft && <form id="provider-settings-form" className="settings-dialog-form" onSubmit={saveProvider}>
          <div className="field-group"><label htmlFor="provider-name">配置名称</label><Input id="provider-name" value={providerDraft.name} onChange={(event) => setProviderDraft({ ...providerDraft, name: event.target.value })} required autoFocus /></div>
          <div className="field-group"><label htmlFor="provider-type">供应商</label><Select value={providerDraft.provider} onValueChange={(value) => changeProviderType(value as ModelProvider)}><SelectTrigger id="provider-type" aria-label="供应商"><SelectValue /></SelectTrigger><SelectContent>{providerOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
          <div className="field-group"><label htmlFor="provider-base-url">API 地址</label><Input id="provider-base-url" type="url" value={providerDraft.baseUrl} onChange={(event) => setProviderDraft({ ...providerDraft, baseUrl: event.target.value })} placeholder="https://api.example.com/v1" required /></div>
          <div className="field-group">
            <label htmlFor="provider-api-key">API 密钥</label>
            <div className="credential-input">
              <KeyRound />
              <Input
                id="provider-api-key"
                type={showApiKey ? 'text' : 'password'}
                value={providerDraft.apiKey ?? ''}
                onChange={(event) => setProviderDraft({ ...providerDraft, apiKey: event.target.value })}
                placeholder={configuration.providers.some((provider) => provider.id === providerDraft.id) ? '留空保持当前密钥' : '输入供应商 API Key'}
                autoComplete="new-password"
                required={!configuration.providers.some((provider) => provider.id === providerDraft.id)}
              />
              <Button type="button" variant="ghost" size="icon-sm" title={showApiKey ? '隐藏密钥' : '显示密钥'} aria-label={showApiKey ? '隐藏密钥' : '显示密钥'} onClick={() => setShowApiKey((visible) => !visible)}>
                {showApiKey ? <EyeOff /> : <Eye />}
              </Button>
            </div>
            <small className="credential-help">{configuration.providers.some((provider) => provider.id === providerDraft.id) && configuration.providers.find((provider) => provider.id === providerDraft.id)?.credentialConfigured ? '已配置密钥，留空不会覆盖。' : '密钥仅在保存时提交，读取配置时不会返回。'}</small>
          </div>
          <label className="settings-checkbox"><Checkbox checked={providerDraft.enabled} onCheckedChange={(checked) => setProviderDraft({ ...providerDraft, enabled: checked === true })} />启用此供应商</label>
        </form>}
        <DialogFooter><Button variant="outline" onClick={() => setProviderDraft(null)} disabled={mutation.isPending}>取消</Button><Button type="submit" form="provider-settings-form" disabled={mutation.isPending}>{mutation.isPending ? '保存中…' : '保存供应商'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={modelDraft !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setModelDraft(null) }}>
      <DialogContent className="settings-dialog">
        <DialogHeader><DialogTitle>{configuration.models.some((model) => model.id === modelDraft?.id) ? '编辑模型' : '添加模型'}</DialogTitle><DialogDescription>模型 ID 是发送给供应商的真实标识。</DialogDescription></DialogHeader>
        {modelDraft && <form id="model-settings-form" className="settings-dialog-form" onSubmit={saveModel}>
          <div className="field-group"><label htmlFor="model-provider">供应商</label><Select value={modelDraft.providerId} onValueChange={(value) => setModelDraft({ ...modelDraft, providerId: value })}><SelectTrigger id="model-provider" aria-label="模型供应商"><SelectValue /></SelectTrigger><SelectContent>{configuration.providers.map((provider) => <SelectItem key={provider.id} value={provider.id}>{provider.name}</SelectItem>)}</SelectContent></Select></div>
          <div className="field-group"><label htmlFor="model-id">模型 ID</label><Input id="model-id" value={modelDraft.modelId} onChange={(event) => setModelDraft({ ...modelDraft, modelId: event.target.value })} placeholder="例如：gpt-4.1-mini" required autoFocus /></div>
          <label className="settings-checkbox"><Checkbox checked={modelDraft.enabled} onCheckedChange={(checked) => setModelDraft({ ...modelDraft, enabled: checked === true })} />启用此模型</label>
        </form>}
        <DialogFooter><Button variant="outline" onClick={() => setModelDraft(null)} disabled={mutation.isPending}>取消</Button><Button type="submit" form="model-settings-form" disabled={mutation.isPending}>{mutation.isPending ? '保存中…' : '保存模型'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !mutation.isPending) setDeleteTarget(null) }}>
      <DialogContent>
        <DialogHeader><DialogTitle>确认删除</DialogTitle><DialogDescription>删除“{deleteTarget?.label}”后无法恢复。删除供应商会同时删除它的全部模型。</DialogDescription></DialogHeader>
        <DialogFooter><Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={mutation.isPending}>取消</Button><Button variant="destructive" onClick={confirmDelete} disabled={mutation.isPending}><Trash2 />删除</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}
