import { useParams } from 'react-router-dom'
import PrintPage from '../../components/PrintPage'

export default function SpecPrint() {
  const { id } = useParams()
  return <PrintPage docUrl={`/api/qms/specs/${id}/document/`} backTo={`/specs/${id}`} queryKey={['spec-doc', id]} />
}
