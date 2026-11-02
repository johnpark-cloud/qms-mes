import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Layout, Menu, Spin } from 'antd'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchMe, logout } from '../api/auth'
import { ApiError } from '../api/client'

// 기존 화면 주소 중 React 로 옮긴 것은 새 주소로 보여 준다.
const MOVED: Record<string, string> = { '/todo/': '/app/todo', '/overview/': '/app/overview' }
const to = (href: string) => MOVED[href] ?? href

export default function AppLayout() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })

  if (me.isPending) return <Spin fullscreen />
  // 로그인하지 않은 상태(세션 만료 포함)에서 /api/auth/me/ 는 403 이다.
  if (me.error instanceof ApiError && me.error.status === 403) {
    return <Navigate to={'/login?next=' + encodeURIComponent('/app' + pathname + search)} replace />
  }
  if (me.isError) return <Alert type="error" title={me.error.message} showIcon style={{ margin: 16 }} />

  const user = me.data
  const items = user.nav.map((g) => ({
    key: g.group,
    label: g.group,
    children: g.items.map((i) => ({ key: to(i.href), label: i.label })),
  }))
  const selected = '/app' + pathname
  const open = user.nav.filter((g) => g.items.some((i) => to(i.href) === selected)).map((g) => g.group)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px' }}>
        <strong style={{ fontSize: 18 }}>QMS+MES</strong>
        <span style={{ flex: 1 }} />
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
            defaultOpenKeys={open.length ? open : [user.nav[0]?.group]} />
        </Layout.Sider>
        <Layout.Content style={{ padding: 24, minWidth: 0 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
