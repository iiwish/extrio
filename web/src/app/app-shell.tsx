import { ArrowLeft, ChevronRight, Database, FileText, Layers3, LayoutDashboard, PlayCircle, Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { returnTarget } from '@/lib/workspace-navigation'

const primaryNavItems = [
  { to: '/', key: 'nav.overview', icon: LayoutDashboard },
  { to: '/collections', key: 'nav.collections', icon: FileText },
  { to: '/collectors', key: 'nav.collectors', icon: Layers3 },
  { to: '/runs', key: 'nav.runs', icon: PlayCircle },
  { to: '/items', key: 'nav.items', icon: Database },
]
const settingsNavItem = { to: '/settings', key: 'nav.settings', icon: Settings2 }
const navItems = [...primaryNavItems, settingsNavItem]

function MainNav() {
  const { t } = useTranslation('common')
  return (
    <nav className="side-nav" aria-label={t('nav.mainNavAria')}>
      {primaryNavItems.map(({ to, key, icon: Icon }) => (
        <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => cn('nav-link', isActive && 'is-active')}>
          <Icon className="size-4" aria-hidden="true" />
          <span>{t(key)}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export function AppShell() {
  const { t, i18n } = useTranslation(['common', 'app'])
  const location = useLocation()
  useEffect(() => {
    document.title = t('title', { ns: 'app' })
    document.documentElement.lang = i18n.language === 'en' ? 'en' : 'zh-CN'
  }, [t, i18n.language])
  const activeNavItem = navItems.find((item) => item.to !== '/' && location.pathname.startsWith(item.to))
  const currentArea = location.pathname === '/'
    ? t('nav.overview')
    : location.pathname.startsWith('/ai-runs/')
      ? t('nav.runs')
    : activeNavItem ? t(activeNavItem.key) : t('workbench', { ns: 'app' })
  const collectorDetail = location.pathname.startsWith('/collectors/') && location.pathname !== '/collectors/new'
  const collectionDetail = location.pathname.startsWith('/collections/') && location.pathname !== '/collections/new'
  const runDetail = location.pathname.startsWith('/runs/')
  const aiRunDetail = location.pathname.startsWith('/ai-runs/')
  const itemDetail = location.pathname.startsWith('/items/')
  const [detailBackTarget, setTopbarBackTarget] = useState<string | null>(null)
  const requirementParams = new URLSearchParams(location.search)
  const requirementSearch = new URLSearchParams()
  for (const key of ['q', 'status', 'sort']) if (requirementParams.has(key)) requirementSearch.set(key, requirementParams.get(key)!)
  const topbarBackTarget = collectionDetail ? `/collections${requirementSearch.size ? `?${requirementSearch}` : ''}` : collectorDetail ? detailBackTarget ?? '/collectors' : runDetail ? '/runs' : aiRunDetail ? '/runs?view=ai' : itemDetail ? '/items' : null
  const topbarBackLabel = runDetail || aiRunDetail
    ? t('action.detailBack', { target: t('nav.runs') })
      : itemDetail
      ? t('action.detailBack', { target: t('nav.items') })
      : collectionDetail ? t('action.detailBack', { target: t('nav.collections') })
      : detailBackTarget ? t('action.backToRequirement') : t('action.detailBack', { target: t('nav.collectors') })
  const collectionCreate = location.pathname === '/collections/new'
  const collectorCreate = location.pathname === '/collectors/new' || collectionCreate
  const requestedCollectionId = new URLSearchParams(location.search).get('collection')?.trim()
  const collectorCreateBackTarget = collectionCreate ? '/collections' : requestedCollectionId
    ? `/collections/${encodeURIComponent(requestedCollectionId)}`
    : '/collectors'
  const fallbackBackTarget = collectorCreate ? collectorCreateBackTarget : topbarBackTarget
  const contextualBackTarget = fallbackBackTarget ? returnTarget(requirementParams, fallbackBackTarget) : null
  const returnArea = contextualBackTarget?.startsWith('/ai-runs/') ? t('nav.runs') : navItems.find(item => item.to !== '/' && contextualBackTarget?.startsWith(item.to))
  const returnAreaLabel = typeof returnArea === 'string' ? returnArea : returnArea ? t(returnArea.key) : currentArea
  const contextualBackLabel = requirementParams.has('returnTo')
    ? t('action.detailBack', { target: returnAreaLabel })
    : collectorCreate ? (requestedCollectionId ? t('action.backToRequirement') : t('action.detailBack', { target: t(collectionCreate ? 'nav.collections' : 'nav.collectors') })) : topbarBackLabel
  const subpage = collectorCreate
    ? t(collectionCreate ? 'collections.create' : 'subnav.newCollector')
    : collectionDetail ? t('collections.detail') : collectorDetail
      ? t('subnav.collectorDetail')
      : runDetail
        ? t('subnav.runDetail')
        : aiRunDetail
          ? t('subnav.aiRunDetail')
          : itemDetail
            ? t('subnav.itemDetail')
            : null

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label={t('aria.brandHome')}>
          <span className="brand-mark">E</span>
          <span>Extrio</span>
        </NavLink>
        <MainNav />
        <div className="sidebar-bottom">
          <NavLink to={settingsNavItem.to} className={({ isActive }) => cn('nav-link', isActive && 'is-active')}>
            <Settings2 className="size-4" aria-hidden="true" />
            <span>{t(settingsNavItem.key)}</span>
          </NavLink>
        </div>
      </aside>

      <div className="app-column">
        <header className="topbar">
          <div className="topbar-context" aria-label={t('aria.currentPage')}>
            {contextualBackTarget && <NavLink end className="topbar-back" to={contextualBackTarget} aria-label={contextualBackLabel} title={contextualBackLabel}><ArrowLeft /></NavLink>}
            {subpage && contextualBackTarget
              ? <nav className="topbar-trail" aria-label={t('aria.secondaryNavigation')}>
                <NavLink end to={contextualBackTarget}>{returnAreaLabel}</NavLink>
                <ChevronRight aria-hidden="true" />
                <strong aria-current="page">{subpage}</strong>
              </nav>
              : <strong>{currentArea}</strong>}
          </div>
        </header>
        <main className="app-main">
          <Outlet context={{ setTopbarBackTarget }} />
        </main>
      </div>
    </div>
  )
}
