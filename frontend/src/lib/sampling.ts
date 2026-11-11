// 자주 쓰는 샘플링 방식. 목록에 없는 방식은 그대로 직접 입력한다(서버는 자유 입력을 받는다).
export const SAMPLING = [
  '전수검사',
  'n=1',
  'n=3',
  'n=5',
  'n=13',
  'AQL 0.65 일반검사수준 II',
  'AQL 1.0 일반검사수준 II',
  'AQL 2.5 일반검사수준 II',
  'C=0',
  '초·중·종물',
].map((value) => ({ value, label: value }))
