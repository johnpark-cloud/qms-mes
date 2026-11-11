import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Tag } from 'antd'
import { api } from '../api/client'
import type { LotInfo } from '../api/inspect'

// LOT 고르기 목록: 번호·품번·품명·협력사 일부로 찾는다. 빈 검색어면 최근 LOT 20건이다.
// shortcut: 글자마다 한 번씩 조회한다(사내망·SQLite 기준). 느려지면 입력 지연(debounce)을 넣는다.
export function useLotOptions(text: string) {
  const q = text.trim()
  const { data } = useQuery({
    queryKey: ['lots', q],
    queryFn: () => api<{ results: LotInfo[] }>(`/api/core/lots/?q=${encodeURIComponent(q)}`),
    placeholderData: keepPreviousData,
  })
  return (data?.results ?? []).map((l) => ({
    value: l.number,
    label: (
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
        <b>{l.number}</b>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', opacity: 0.75 }}>
          {l.item_code} {l.item_name}
          {l.supplier && ` · ${l.supplier}`}
        </span>
        {l.on_hold && <Tag color="red" style={{ margin: 0 }}>보류</Tag>}
      </div>
    ),
  }))
}
