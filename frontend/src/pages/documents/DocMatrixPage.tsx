import { Button, Card, Empty, Input, Space, Table, Tag, Tooltip } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'

interface FormChip { id: number; code: string; name: string; revision: string; target_display: string; url: string }
interface DocRow { id: number; number: string; title: string; doc_type: string; url: string; inputs: FormChip[]; outputs: FormChip[] }
interface Dept { id: number | null; name: string; documents: DocRow[] }

// 서버 주소는 /app/...; 라우터 Link는 basename(/app) 아래 경로를 받는다
const inApp = (url: string) => url.replace(/^\/app/, '')

function Chips({ forms }: { forms: FormChip[] }) {
  if (!forms.length) return <span className="doc-hint">—</span>
  return (
    <Space size={[4, 4]} wrap>
      {forms.map((f) => (
        <Tooltip key={f.id} title={f.target_display ? `${f.code} → ${f.target_display}` : `${f.code} (양식 기록)`}>
          <Link to={inApp(f.url)}>
            <Tag color={f.target_display ? 'blue' : undefined} className="form-chip">
              <span className="form-chip-code">{f.code}</span> {f.name}
            </Tag>
          </Link>
        </Tooltip>
      ))}
    </Space>
  )
}

// 문서 체계(P6a): 부서별 결재서 행 × 입력·출력 양식 칩. 파란 칩 = 시스템 기록·대장에 연결된 양식(누르면 그 화면에서 바로 쓴다).
export default function DocMatrixPage() {
  const [q, setQ] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['doc-matrix', q],
    queryFn: () => api<{ departments: Dept[] }>(`/api/qms/documents/matrix/?q=${encodeURIComponent(q)}`),
  })
  const depts = data?.departments ?? []
  return (
    <div>
      <h1 className="page-title">문서 체계</h1>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search style={{ width: 260 }} allowClear placeholder="문서번호·양식 번호·이름" onSearch={setQ} aria-label="문서 검색" />
        <Link to="/r/qms/document/new"><Button>결재서 추가</Button></Link>
        <Link to="/r/qms/documentform/new"><Button>양식 추가</Button></Link>
        <span className="doc-hint">파란 양식은 시스템 기록과 연결되어 있어 누르면 그 대장에서 바로 작성합니다.</span>
      </Space>
      {!isLoading && !depts.length && <Empty description="등록된 결재서가 없습니다." />}
      {depts.map((d) => (
        <Card key={d.id ?? 'none'} size="small" title={`${d.name} · ${d.documents.length}건`} style={{ marginBottom: 12 }}>
          <Table<DocRow>
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={d.documents}
            scroll={{ x: 720 }}
            columns={[
              {
                title: '결재서', width: 280,
                render: (_, r) => <Link to={inApp(r.url)}><b>{r.number}</b> {r.title}</Link>,
              },
              { title: '입력 양식', render: (_, r) => <Chips forms={r.inputs} /> },
              { title: '출력 양식', render: (_, r) => <Chips forms={r.outputs} /> },
            ]}
          />
        </Card>
      ))}
    </div>
  )
}
