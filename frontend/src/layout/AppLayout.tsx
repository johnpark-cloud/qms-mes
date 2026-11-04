import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Layout, Menu, Spin } from 'antd'
import { useEffect, useState } from 'react'
import { Link, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchMe, logout } from '../api/auth'
import { ApiError } from '../api/client'
import CommandPalette from '../components/CommandPalette'
import { getRecent } from '../lib/recent'

// 기존 화면 주소 중 React 로 옮긴 것은 새 주소로 보여 준다.
const MOVED: Record<string, string> = {
  '/todo/': '/app/todo',
  '/overview/': '/app/overview',
  '/inspect/': '/app/inspect',
  '/admin/qms/inspectionspec/': '/app/specs',
  '/admin/core/item/': '/app/items',
  '/admin/core/process/': '/app/processes',
  '/admin/qms/controlplan/': '/app/plans',
  '/admin/qms/customerrule/': '/app/customer-rules',
  '/import/': '/app/import',
  '/admin/qms/inspection/?spec__inspection_type__exact=INCOMING': '/app/inspections?tab=INCOMING',
  '/admin/qms/inspection/?spec__inspection_type__exact=PROCESS': '/app/inspections?tab=PROCESS',
  '/admin/qms/inspection/?spec__inspection_type__exact=OUTGOING': '/app/inspections?tab=OUTGOING',
}
const to = (href: string) => MOVED[href] ?? href

export default function AppLayout() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  // data/brand/logo.* 가 없으면 /brand/logo 가 404 라 글자로 보인다 (admin 상단 바와 같다).
  const [logo, setLogo] = useState(true)
  const [palette, setPalette] = useState(false)
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true) }
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  if (me.isPending) return <Spin fullscreen />
  // 로그인하지 않은 상태(세션 만료 포함)에서 /api/auth/me/ 는 403 이다.
  if (me.error instanceof ApiError && me.error.status === 403) {
    return <Navigate to={'/login?next=' + encodeURIComponent('/app' + pathname + search)} replace />
  }
  if (me.isError) return <Alert type="error" title={me.error.message} showIcon style={{ margin: 16 }} />

  const user = me.data
  const recent = getRecent()
  const items = [
    ...(recent.length ? [{ key: 'recent', label: '최근 연 기록', children: recent.map((r) => ({ key: r.href, label: r.label })) }] : []),
    ...user.nav.map((g) => ({
      key: g.group,
      label: g.group,
      children: g.items.map((i) => ({ key: to(i.href), label: i.label })),
    })),
  ]
  // 검사 목록은 탭마다 메뉴가 따로 있다. ?tab 이 없으면 화면처럼 수입검사로 본다.
  const selected = '/app' + pathname + (pathname === '/inspections' ? `?tab=${new URLSearchParams(search).get('tab') || 'INCOMING'}` : '')
  const open = user.nav.filter((g) => g.items.some((i) => to(i.href) === selected)).map((g) => g.group)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px' }}>
        <Link to="/todo" style={{ display: 'flex', color: 'inherit' }}>
          {logo ? <img className="shell-brand" src="/brand/logo" alt="QMS+MES" onError={() => setLogo(false)} />
            : <strong style={{ fontSize: 18 }}>QMS+MES</strong>}
        </Link>
        <span style={{ flex: 1 }} />
        <Button aria-label="명령창 열기" onClick={() => setPalette(true)} className="palette-btn">
          검색 (Ctrl+K)
        </Button>
        <span>{user.name}</span>
        <a href="/todo/">기존 화면</a>
        <Button
          onClick={async () => {
            try {
              await logout()
            } catch {
              // 세션이 이미 만료돼 403 이어도 로그인 화면으로 간다.
            } finally {
              queryClient.clear()
              location.href = '/app/login'
            }
          }}
        >
          로그아웃
        </Button>
      </Layout.Header>
      <Layout>
        <Layout.Sider width={248} breakpoint="md" collapsedWidth={0} theme="light">
          <Menu mode="inline" items={items} selectedKeys={[selected]}
            // 항목 전체가 눌리도록 링크 대신 클릭으로 이동한다. 가운데 클릭·새 탭 열기는 포기한다(사내 업무 화면이라 필요 없다).
            onClick={({ key }) => (key.startsWith('/app/') ? navigate(key.slice(4)) : (location.href = key))}
            defaultOpenKeys={['recent', ...(open.length ? open : [user.nav[0]?.group])]} />
        </Layout.Sider>
        <Layout.Content style={{ padding: 24, minWidth: 0 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </Layout>
  )
}
