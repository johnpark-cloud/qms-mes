import { useParams, useSearchParams } from 'react-router-dom'
import PrintPage from '../../components/PrintPage'

export default function PlanPrint() {
  const { id } = useParams()
  const pfmea = useSearchParams()[0].get('kind') === 'pfmea'
  return <PrintPage docUrl={`/api/qms/plans/${id}/document/${pfmea ? '?kind=pfmea' : ''}`} backTo={`/plans/${id}`} queryKey={['plan-doc', id, pfmea]} />
}
