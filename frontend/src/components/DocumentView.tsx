import type { DocStruct } from '../api/specs'

// A4 한 장 문서 틀. 검사기준서 외 기록(2묶음 이후)도 같은 부품을 쓴다.
export default function DocumentView({ doc }: { doc: DocStruct }) {
  const s = doc.signoff
  return (
    <div className={doc.landscape ? 'doc-page doc-landscape' : 'doc-page'}>
      {doc.landscape && <style>{'@page { size: A4 landscape; margin: 12mm }'}</style>}
      {doc.draft && <div className="doc-watermark" aria-hidden="true">초안 — 승인 전</div>}
      <div className="doc-top">
        <div>
          <h1 className="doc-title">{doc.title}</h1>
          <div>{[doc.number, doc.revision].filter(Boolean).join(' · ')}</div>
        </div>
        <table className="doc-sign">
          <thead><tr><th></th><th>작성</th><th>승인</th></tr></thead>
          <tbody>
            <tr><th>서명</th><td>{s.written_by}</td><td>{s.approved_by}</td></tr>
            <tr><th>일자</th><td>{s.written_at}</td><td>{s.approved_at}</td></tr>
          </tbody>
        </table>
      </div>
      {doc.head.length > 0 && <table className="doc-table doc-head">
        <tbody>
          {doc.head.map(([k, v]) => (
            <tr key={k}><th>{k}</th><td>{v}</td></tr>
          ))}
        </tbody>
      </table>}
      {doc.tables.map((t, i) => (
        <section key={i}>
          <h2 className="doc-h2">{t.title}</h2>
          {t.columns[0] === '항목' ? (
            // 항목·내용 두 칸 표(기록 양식지)는 머리줄 없이 항목을 머리칸으로
            <table className="doc-table doc-head">
              <tbody>{t.rows.map((r, j) => <tr key={j}><th>{r[0]}</th><td>{r[1]}</td></tr>)}</tbody>
            </table>
          ) : (
            <table className="doc-table">
              <thead><tr>{t.columns.map((c, j) => <th key={j}>{c}</th>)}</tr></thead>
              <tbody>
                {t.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{c}</td>)}</tr>)}
              </tbody>
            </table>
          )}
        </section>
      ))}
      {!!doc.photos?.length && <section>
        <h2 className="doc-h2">사진</h2>
        <div className="doc-photos">
          {doc.photos.map((p, i) => <figure key={i}><img src={p.url} alt={p.caption || `사진 ${i + 1}`} /><figcaption>{p.caption}</figcaption></figure>)}
        </div>
      </section>}
      {doc.body != null && <section>
        <h2 className="doc-h2">본문</h2>
        <div className="doc-body">{doc.body || '—'}</div>
      </section>}
      {doc.revisions && <>
      <h2 className="doc-h2">개정 이력</h2>
      <table className="doc-table">
        <thead><tr><th>개정</th><th>변경 내용</th><th>사유</th><th>요청자</th><th>승인자</th><th>승인일</th></tr></thead>
        <tbody>
          {doc.revisions.map((r, i) => (
            <tr key={i}><td>{r.label}</td><td>{r.changes}</td><td>{r.reason}</td><td>{r.requested_by}</td><td>{r.approved_by}</td><td>{r.approved_at}</td></tr>
          ))}
        </tbody>
      </table>
      </>}
    </div>
  )
}
