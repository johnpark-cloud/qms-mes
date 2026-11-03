// 엑셀·시트에서 복사한 글(탭으로 칸, 줄바꿈으로 줄)을 푼다. 큰따옴표로 감싼 칸 안의 탭·줄바꿈·""는 엑셀 규칙대로 푼다.
export function parseTsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false // 큰따옴표 칸 안
  let i = 0
  const endCell = () => {
    row.push(cell)
    cell = ''
  }
  while (i < text.length) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"'
        i += 2
        continue
      }
      if (c === '"') quoted = false
      else cell += c
    } else if (c === '"' && cell === '') {
      quoted = true // 칸의 맨 앞에서만 따옴표 칸이 시작된다
    } else if (c === '\t') {
      endCell()
    } else if (c === '\n' || (c === '\r' && text[i + 1] === '\n')) {
      if (c === '\r') i++
      endCell()
      rows.push(row)
      row = []
    } else {
      cell += c
    }
    i++
  }
  if (cell !== '' || row.length) {
    endCell()
    rows.push(row)
  }
  while (rows.length && rows[rows.length - 1].length === 1 && rows[rows.length - 1][0] === '') rows.pop()
  return rows
}
