import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ListFilter } from './DataList'

type Opt = { value: string; label: string }

// 품번·검사기준서·관리계획서 목록의 프로젝트 거르기 선택지(core/api/master.py ProjectOptionsView). 첫 줄은 '프로젝트 없음'
export function useProjectOptions(): Opt[] {
  const { data } = useQuery({
    queryKey: ['project-options'],
    queryFn: () => api<Opt[]>('/api/core/items/projects/'),
    staleTime: 60_000,
    retry: false,
  })
  return data ?? []
}

export default function useProjectFilter(): ListFilter[] {
  const options = useProjectOptions()
  return options.length > 1 ? [{ key: 'project', label: '프로젝트', type: 'choice', options }] : []
}
