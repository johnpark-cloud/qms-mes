import { useQuery } from '@tanstack/react-query'
import { Input, Modal, Segmented } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMe } from '../api/auth'
import { api } from '../api/client'
import type { ListPage } from '../pages/records/RecordList'
import { addRecent, getRecent } from '../lib/recent'

type Hit = { label: string; sub?: string; url: string }

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const [mode, setMode] = useState<'find' | 'tree'>('find')

  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250)
    return () => clearTimeout(t)
  }, [text])
  useEffect(() => {
    if (open) { setText(''); setQ(''); setIdx(0); setMode('find') }
  }, [open])
  useEffect(() => setIdx(0), [q])

  const search = useQuery({
    queryKey: ['search', q],
    queryFn: () => api<{ results: Hit[] }>('/api/search/?q=' + encodeURIComponent(q)),
    enabled: open && q !== '',
  })
  const typed = text.trim()
  const empty = typed === ''
  // 입력이 검색어와 아직 다르면(250ms 대기 중) 이전 결과로 Enter 가 열리지 않게 비워 둔다.
  const settled = q === typed && !search.isFetching
  const hits: Hit[] = empty
    ? getRecent().map((r) => ({ label: r.label, url: r.href }))
    : settled ? (search.data?.results ?? []) : []

  const go = (h: Hit) => {
    if (!h.url) return // 비활성 모듈 기록 건수 줄은 열 곳이 없다
    addRecent({ label: h.label, href: h.url })
    onClose()
    if (h.url.startsWith('/app/')) navigate(h.url.slice(4))
    else location.href = h.url
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} destroyOnHidden width={mode === 'tree' ? 960 : 560}>
      <Segmented block style={{ marginBottom: 8 }} value={mode} onChange={(v) => setMode(v as 'find' | 'tree')}
        options={[{ value: 'find', label: '기록 찾기' }, { value: 'tree', label: '전체 메뉴' }]} />
      <Input
        autoFocus
        placeholder={mode === 'tree' ? '메뉴 이름 거르기' : 'LOT·품번·번호 또는 동작'}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // 한글 조합을 확정하는 Enter·방향키는 이동으로 쓰지 않는다(229 는 옛 브라우저의 조합 키 코드).
          if (e.nativeEvent.isComposing || e.keyCode === 229 || mode === 'tree') return
          if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
          else if (e.key === 'Enter' && hits[idx]) go(hits[idx])
        }}
      />
      {mode === 'tree' ? <MenuTree filter={typed} go={go} /> : <div role="listbox" style={{ marginTop: 8 }}>
        {empty && hits.length > 0 && <div className="palette-sub">최근 연 기록</div>}
        {hits.map((h, i) => (
          <div key={h.url} role="option" aria-selected={i === idx} data-palette-item className="palette-item"
            onMouseEnter={() => setIdx(i)} onClick={() => go(h)}>
            <div>{h.label}</div>
            {h.sub && <div className="palette-sub">{h.sub}</div>}
          </div>
        ))}
        {!empty && settled && hits.length === 0 && <div className="palette-sub">찾는 기록이 없습니다</div>}
      </div>}
    </Modal>
  )
}

/** 전체 메뉴(밀러 열): 묶음 → 메뉴(하위 메뉴는 들여 씀) → 그 목록의 최근 기록. 입력하면 메뉴 이름으로 거른다 */
function MenuTree({ filter, go }: { filter: string; go: (h: Hit) => void }) {
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity }).data
  const f = filter.toLowerCase()
  const groups = (me?.nav ?? [])
    .map((g) => ({ ...g, items: g.items.filter((i) => !f || i.label.toLowerCase().includes(f) || g.group.toLowerCase().includes(f)) }))
    .filter((g) => g.items.length)
  const [gSel, setG] = useState('')
  const [iSel, setI] = useState('')
  const g = groups.find((x) => x.group === gSel) ?? groups[0]
  const item = g?.items.find((i) => i.href === iSel) ?? g?.items[0]
  const [path, query = ''] = item?.href.slice(4).split('?') ?? ['']
  const isList = item?.href.startsWith('/app/r/')
  const ct = path.split('/').slice(2, 4).join('.')
  const rows = useQuery({ queryKey: ['hub', item?.href], enabled: !!isList,
    queryFn: () => api<ListPage>(`/api/records/${ct}/${query ? '?' + query : ''}`) })
  if (!groups.length) return <div className="palette-sub" style={{ marginTop: 8 }}>맞는 메뉴가 없습니다</div>
  const col = (key: string, label: string, on: boolean, sel: () => void, open: () => void, sub?: string) => (
    <div key={key} className="palette-item miller-item" aria-selected={on} onMouseEnter={sel} onClick={open}>
      <div>{label}</div>{sub && <div className="palette-sub">{sub}</div>}
    </div>
  )
  return (
    <div className="miller">
      <div className="miller-col">
        {groups.map((x) => col(x.group, x.group, x === g, () => { setG(x.group); setI('') }, () => { setG(x.group); setI('') }))}
      </div>
      <div className="miller-col">
        {g?.items.map((i) => col(i.href, (i.parent ? '└ ' : '') + i.label, i === item, () => setI(i.href), () => go({ label: i.label, url: i.href })))}
      </div>
      <div className="miller-col">
        {!isList && item && col('open', `${item.label} 열기`, false, () => {}, () => go({ label: item.label, url: item.href }))}
        {isList && rows.data && <>
          <div className="palette-sub" style={{ padding: '4px 8px' }}>최근 {rows.data.title} (전체 {rows.data.count})</div>
          {rows.data.results.slice(0, 8).map((r) => col(String(r.id), Object.values(r.cells)[0] || String(r.id), false, () => {},
            () => go({ label: Object.values(r.cells)[0] || '', url: `/app${path}/${r.id}` }), Object.values(r.cells).slice(1, 3).join(' · ')))}
          {col('all', '전체 보기', false, () => {}, () => go({ label: item!.label, url: item!.href }))}
        </>}
      </div>
    </div>
  )
}
