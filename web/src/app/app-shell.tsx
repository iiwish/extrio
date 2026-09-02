import { ArrowLeft, Database, Layers3, LayoutDashboard, LogOut, PlayCircle, Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/auth-gate'

const primaryNavItems = [
  { to: '/', key: 'nav.overview', icon: LayoutDashboard },
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
  const { user, logout } = useAuth()
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
  const runDetail = location.pathname.startsWith('/runs/')
  const aiRunDetail = location.pathname.startsWith('/ai-runs/')
  const itemDetail = location.pathname.startsWith('/items/')
  const [detailBackTarget, setTopbarBackTarget] = useState<string | null>(null)
  const topbarBackTarget = collectorDetail ? detailBackTarget ?? '/collectors' : runDetail ? '/runs' : aiRunDetail ? '/runs?view=ai' : itemDetail ? '/items' : null
  const topbarBackLabel = runDetail || aiRunDetail
    ? t('action.detailBack', { target: t('nav.runs') })
    : itemDetail
      ? t('action.detailBack', { target: t('nav.items') })
      : t('action.backToRequirement')

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
            {topbarBackTarget && <NavLink className="topbar-back" to={topbarBackTarget} aria-label={topbarBackLabel} title={topbarBackLabel}><ArrowLeft /></NavLink>}
            <strong>{currentArea}</strong>
          </div>
          <div className="topbar-actions">
            <span className="role-pill">{t('topbar.administrator')}</span>
            <span className="user-avatar" aria-label={t('aria.currentUser', { name: user.displayName })}>{user.displayName.slice(0, 1).toUpperCase()}</span>
            <Button type="button" variant="ghost" size="icon-sm" onClick={logout} title={t('topbar.logout')} aria-label={t('topbar.logout')}>
              <LogOut />
            </Button>
          </div>
        </header>
        <main className="app-main">
          <Outlet context={{ setTopbarBackTarget }} />
        </main>
      </div>
    </div>
  )
}
