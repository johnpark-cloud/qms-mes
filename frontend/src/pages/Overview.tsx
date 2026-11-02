import { useQuery } from '@tanstack/react-query'
import { Alert, Empty, Spin, Typography } from 'antd'
import { api } from '../api/client'
import Tile, { type TileData } from '../components/Tile'

interface Card extends TileData {
  title: string
}
interface Overview {
  sections: { name: string; cards: Card[] }[]
}

export default function Overview() {
  const q = useQuery({ queryKey: ['overview'], queryFn: () => api<Overview>('/api/qms/overview/') })
  if (q.isPending) return <Spin />
  if (q.isError) return <Alert type="error" title={q.error.message} showIcon />

  const sections = q.data.sections.filter((s) => s.cards.length)
  return (
    <div style={{ display: 'grid', gap: 24 }}>
      <Typography.Title level={3} style={{ margin: 0 }}>공장 종합현황</Typography.Title>
      {sections.length === 0 && <Empty description="볼 수 있는 현황이 없습니다." />}
      {sections.map((s) => (
        <section key={s.name} style={{ display: 'grid', gap: 12 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>{s.name}</Typography.Title>
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill, minmax(min(280px, 100%), 1fr))' }}>
            {s.cards.map((c) => (
              <div key={c.title} data-card>
                <Tile title={c.title} tile={c} details />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
