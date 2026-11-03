import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Spin } from 'antd'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { DocStruct } from '../api/specs'
import DocumentView from './DocumentView'

// 문서 API(docUrl)를 받아 A4 인쇄 화면을 그린다. 검사기준서·검사 성적서가 같이 쓴다.
export default function PrintPage({ docUrl, backTo, queryKey }: { docUrl: string; backTo: string; queryKey: unknown[] }) {
  const q = useQuery({ queryKey, queryFn: () => api<DocStruct>(docUrl) })
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '문서를 불러오지 못했습니다.'} />
  if (!q.data) return <Spin />
  return (
    <>
      <div className="print-bar">
        <Link to={backTo}>← {q.data.title}</Link>
        <Button type="primary" onClick={() => window.print()}>인쇄 / PDF로 저장</Button>
        <a href={docUrl + '?export=xlsx'} download>.xlsx 받기</a>
      </div>
      <DocumentView doc={q.data} />
    </>
  )
}
