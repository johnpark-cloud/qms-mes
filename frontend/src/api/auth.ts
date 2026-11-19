import { api } from './client'

export interface NavGroup {
  group: string
  hub: boolean // 묶음 제목을 누르면 한눈에 보기(/app/hub/<묶음>)
  items: { label: string; href: string; parent?: string }[] // parent: 상위 메뉴(사이드바엔 안 보이고 그 화면 위 탭)
}

export interface Me {
  username: string
  name: string
  is_superuser: boolean
  is_approver: boolean
  groups: string[]
  perms: string[]
  nav: NavGroup[]
  modules: Record<string, boolean> // 모듈 키 → 켜짐 (core/modules.py)
}

export const fetchMe = () => api<Me>('/api/auth/me/')

export const login = (username: string, password: string) =>
  api<Me>('/api/auth/login/', { method: 'POST', body: JSON.stringify({ username, password }) })

export const logout = () => api<void>('/api/auth/logout/', { method: 'POST' })
