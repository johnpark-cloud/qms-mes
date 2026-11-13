import { useQuery } from '@tanstack/react-query'
import { Input, Modal } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { addRecent, getRecent } from '../lib/recent'

type Hit = { label: string; sub?: string; url: string }

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250)
    return () => clearTimeout(t)
  }, [text])
  useEffect(() => {
    if (open) { setText(''); setQ(''); setIdx(0) }
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
    <Modal open={open} onCancel={onClose} footer={null} closable={false} destroyOnHidden width={560}>
      <Input
        autoFocus
        placeholder="LOT·품번·번호 또는 동작"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // 한글 조합을 확정하는 Enter·방향키는 이동으로 쓰지 않는다(229 는 옛 브라우저의 조합 키 코드).
          if (e.nativeEvent.isComposing || e.keyCode === 229) return
          if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
          else if (e.key === 'Enter' && hits[idx]) go(hits[idx])
        }}
      />
      <div role="listbox" style={{ marginTop: 8 }}>
        {empty && hits.length > 0 && <div className="palette-sub">최근 연 기록</div>}
        {hits.map((h, i) => (
          <div key={h.url} role="option" aria-selected={i === idx} data-palette-item className="palette-item"
            onMouseEnter={() => setIdx(i)} onClick={() => go(h)}>
            <div>{h.label}</div>
            {h.sub && <div className="palette-sub">{h.sub}</div>}
          </div>
        ))}
        {!empty && settled && hits.length === 0 && <div className="palette-sub">찾는 기록이 없습니다</div>}
      </div>
    </Modal>
  )
}
