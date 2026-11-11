import { Typography } from 'antd'
import MemoPanel from '../components/MemoPanel'

// 미분류 메모: 대상 기록 없이 적어 둔 메모. 종류 + 번호로 기록에 붙이면 여기서 빠진다.
export default function Memos() {
  return (
    <div style={{ maxWidth: 720 }}>
      <h1 className="page-title">미분류 메모</h1>
      <Typography.Paragraph type="secondary">급할 때 먼저 적고, 나중에 LOT·부적합 같은 기록에 연결합니다.</Typography.Paragraph>
      <MemoPanel link />
    </div>
  )
}
