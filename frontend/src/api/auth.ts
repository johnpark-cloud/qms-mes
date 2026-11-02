import { api } from './client'

export interface NavGroup {
  group: string
  items: { label: string; href: string }[]
}

export interface Me {
  username: string
  name: string
  is_superuser: boolean
  is_approver: boolean
  groups: string[]
  perms: string[]
  nav: NavGroup[]
}

export const fetchMe = () => api<Me>('/api/auth/me/')

export const login = (username: string, password: string) =>
  api<Me>('/api/auth/login/', { method: 'POST', body: JSON.stringify({ username, password }) })

export const logout = () => api<void>('/api/auth/logout/', { method: 'POST' })
