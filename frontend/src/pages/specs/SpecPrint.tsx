import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Spin } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type { DocStruct } from '../../api/specs'
import DocumentView from '../../components/DocumentView'

export default function SpecPrint() {
  const { id } = useParams()
  const q = useQuery({ queryKey: ['spec-doc', id], queryFn: () => api<DocStruct>(`/api/qms/specs/${id}/document/`) })
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '문서를 불러오지 못했습니다.'} />
  if (!q.data) return <Spin />
  return (
    <>
      <div className="print-bar">
        <Link to={`/specs/${id}`}>← {q.data.title}</Link>
        <Button type="primary" onClick={() => window.print()}>인쇄 / PDF로 저장</Button>
        <a href={`/api/qms/specs/${id}/document/?export=xlsx`} download>.xlsx 받기</a>
      </div>
      <DocumentView doc={q.data} />
    </>
  )
}
