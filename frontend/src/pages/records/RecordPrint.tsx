import { useParams } from 'react-router-dom'
import PrintPage from '../../components/PrintPage'

// 기록 양식지(A4 한 장): 부적합 보고서·CAPA·8D 등. 옛 /print/ 화면이 여기로 넘어온다(W3)
export default function RecordPrint() {
  const { app, model, id } = useParams()
  return <PrintPage docUrl={`/api/records/${app}.${model}/${id}/document/`} backTo={`/r/${app}/${model}/${id}`} queryKey={['record-doc', app, model, id]} />
}
