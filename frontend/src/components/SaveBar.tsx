import { Button, Space } from 'antd'
import { useEffect, useRef } from 'react'

interface Props {
  count: number
  saving: boolean
  conflict: string
  onSave: () => void
  onCancel: () => void
  onReload: () => void
}

// 고친 것이 있을 때만 바닥에 붙는 저장 띠.
export default function SaveBar({ count, saving, conflict, onSave, onCancel, onReload }: Props) {
  const save = useRef(onSave)
  save.current = onSave
  const active = count > 0 && !saving
  useEffect(() => {
    if (!active) return
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        save.current()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [active])

  if (count === 0 && !conflict) return null
  return (
    <div
      role="region"
      aria-label="저장 띠"
      style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 100, padding: '12px 24px', background: 'var(--app-warning-bg)', borderTop: '1px solid var(--app-border)' }}
    >
      <Space wrap>
        <strong>변경 {count}건</strong>
        {conflict ? (
          <>
            <span style={{ color: 'var(--app-error)' }}>{conflict}</span>
            <Button onClick={onReload}>다시 불러오기</Button>
          </>
        ) : (
          <>
            <Button type="primary" loading={saving} onClick={onSave}>
              저장 (Ctrl+S)
            </Button>
            <Button disabled={saving} onClick={onCancel}>
              취소
            </Button>
          </>
        )}
      </Space>
    </div>
  )
}
