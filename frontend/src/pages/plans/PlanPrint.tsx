import { useParams } from 'react-router-dom'
import PrintPage from '../../components/PrintPage'

export default function PlanPrint() {
  const { id } = useParams()
  return <PrintPage docUrl={`/api/qms/plans/${id}/document/`} backTo={`/plans/${id}`} queryKey={['plan-doc', id]} />
}
