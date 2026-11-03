import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { SpecDetail } from '../../api/specs'

// Task 8 에서 기록 페이지로 바뀐다.
export default function SpecPage() {
  const { id } = useParams()
  const { data } = useQuery({ queryKey: ['spec', Number(id)], queryFn: () => api<SpecDetail>(`/api/qms/specs/${id}/`) })
  return <h1 className="page-title">{data ? data.title : '불러오는 중'}</h1>
}
