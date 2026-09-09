import { Bot, Settings2 } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ModelSettingsPage, SystemSettingsPage } from './model-settings-page'

export function SettingsPage() {
  const { t } = useTranslation('settings')
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'models' ? 'models' : 'system'
  return <div className="page-frame settings-root">
    <h1 className="sr-only">{t('common:nav.settings')}</h1>
    <Tabs value={tab} onValueChange={(value) => {
      const next = new URLSearchParams(params)
      next.set('tab', value)
      setParams(next)
    }}>
      <TabsList variant="line" className="settings-tabs" aria-label={t('common:nav.settings')}>
        <TabsTrigger value="system"><Settings2 />{t('tabs.system')}</TabsTrigger>
        <TabsTrigger value="models"><Bot />{t('tabs.models')}</TabsTrigger>
      </TabsList>
      <TabsContent value="system"><SystemSettingsPage /></TabsContent>
      <TabsContent value="models"><ModelSettingsPage /></TabsContent>
    </Tabs>
  </div>
}
