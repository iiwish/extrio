import { ArrowLeft, Database, Layers3, LayoutDashboard, PlayCircle, Settings2 } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'

const primaryNavItems = [
  { to: '/', label: '概览', icon: LayoutDashboard },
  { to: '/collectors', label: '采集器', icon: Layers3 },
  { to: '/runs', label: '运行', icon: PlayCircle },
  { to: '/items', label: '数据', icon: Database },
]
const settingsNavItem = { to: '/settings', label: '设置', icon: Settings2 }
const navItems = [...primaryNavItems, settingsNavItem]

function MainNav() {
  return (
    <nav className="side-nav" aria-label="主导航">
      {primaryNavItems.map(({ to, label, icon: Icon }) => (
        <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => cn('nav-link', isActive && 'is-active')}>
          <Icon className="size-4" aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

export function AppShell() {
  const location = useLocation()
  const currentArea = location.pathname === '/'
    ? '概览'
    : navItems.find((item) => item.to !== '/' && location.pathname.startsWith(item.to))?.label ?? '工作台'
  const collectorDetail = location.pathname.startsWith('/collectors/') && location.pathname !== '/collectors/new'
  const runDetail = location.pathname.startsWith('/runs/')
  const itemDetail = location.pathname.startsWith('/items/')
  const [detailBackTarget, setTopbarBackTarget] = useState<string | null>(null)
  const topbarBackTarget = collectorDetail ? detailBackTarget ?? '/collectors' : runDetail ? '/runs' : itemDetail ? '/items' : null
  const topbarBackLabel = runDetail ? '返回运行列表' : itemDetail ? '返回数据列表' : '返回所属需求'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label="Extrio 首页">
          <span className="brand-mark">E</span>
          <span>Extrio</span>
        </NavLink>
        <MainNav />
        <div className="sidebar-bottom">
          <NavLink to={settingsNavItem.to} className={({ isActive }) => cn('nav-link', isActive && 'is-active')}>
            <Settings2 className="size-4" aria-hidden="true" />
            <span>{settingsNavItem.label}</span>
          </NavLink>
        </div>
      </aside>

      <div className="app-column">
        <header className="topbar">
          <div className="topbar-context" aria-label="当前页面">
            {topbarBackTarget && <NavLink className="topbar-back" to={topbarBackTarget} aria-label={topbarBackLabel} title={topbarBackLabel}><ArrowLeft /></NavLink>}
            <strong>{currentArea}</strong>
          </div>
          <div className="topbar-actions">
            <span className="role-pill">RuleReviewer</span>
            <span className="user-avatar" aria-label="当前用户：林然">林</span>
          </div>
        </header>
        <main className="app-main">
          <Outlet context={{ setTopbarBackTarget }} />
        </main>
      </div>
    </div>
  )
}
