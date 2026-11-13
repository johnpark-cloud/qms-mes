// num.ts 자체 점검: `node src/lib/num.check.ts` (Node 24는 타입을 지우고 바로 실행한다). 빌드에는 들어가지 않는다.
import assert from 'node:assert/strict'
import { center, decimalsOf, fmtNum, specPosition } from './num.ts'

assert.equal(fmtNum('10', 1), '10.0')
assert.equal(fmtNum('10.14', 1), '10.14') // 자릿수를 줄이지 않는다
assert.equal(fmtNum(null, 2), '—')
assert.equal(fmtNum('OK', 1), 'OK')
assert.equal(decimalsOf('9.9', '10.15'), 2)
assert.equal(decimalsOf(null, '10'), 0)
assert.equal(center('9.9', '10.1', 1), '10.0')
assert.equal(center('0.05', '0.10', 2), '0.075')
assert.equal(center(null, '10.1', 1), '—')
assert.equal(Math.round(specPosition('9.9', '10.1', '10.0')!.pct), 50)
assert.equal(specPosition('9.9', '10.1', '10.0')?.tone, 'ok')
assert.equal(specPosition('9.9', '10.1', '10.09')?.tone, 'warn')
assert.equal(specPosition('9.9', '10.1', '11')?.tone, 'bad')
assert.equal(specPosition('9.9', '10.1', '11')?.pct, 100)
assert.equal(specPosition(null, '10.1', '10'), null)
assert.equal(specPosition('9.9', '10.1', 'OK'), null)
console.log('num.ts OK')
