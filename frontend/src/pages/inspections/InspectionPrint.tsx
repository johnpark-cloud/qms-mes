import { useParams } from 'react-router-dom'
import PrintPage from '../../components/PrintPage'

export default function InspectionPrint() {
  const { id } = useParams()
  return <PrintPage docUrl={`/api/qms/inspections/${id}/document/`} backTo={`/inspections/${id}`} queryKey={['inspection-doc', id]} />
}
