import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  Alert, Button, Card, Checkbox, Col, Drawer, Empty, Form, Input, InputNumber, Modal, Row, Segmented, Select, Space, Spin, Switch, Tag, Tree, Typography, message,
} from 'antd'
import type { TreeDataNode, TreeProps } from 'antd'
import { useEffect, useMemo, useState, type DragEvent, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import SignModal from '../components/SignModal'

// core/api/users.py OrgView
interface Dept { id: number; code: string; name: string; parent: number | null; active: boolean; sort: number; manager: string; manager_id: number | null }
interface User {
  id: number; username: string; name: string; last_name: string; first_name: string; email: string; active: boolean; admin: boolean
  groups: string[]; last_login: string | null; dept: number | null; employee_no: string; position: string; title: string; phone: string
}
interface Org { depts: Dept[]; users: User[]; groups: string[]; me: number; log?: { at: string; by: string; text: string }[] }

const URL = '/api/core/org/'
const NONE = 'none'  // 부서 없는 인원
const post = (body: object) => api(URL, { method: 'POST', body: JSON.stringify(body) })
const errText = (e: unknown) => (e instanceof ApiError ? e.detail : '처리하지 못했습니다.')

/** 사용자·조직도(시스템 관리자): 조직도(위→아래)에서 부서·인원을 누르면 오른쪽 창에서 고친다.
 * 「목록」 보기는 부서 트리에 인원을 끌어 놓아 배치한다. 삭제 대신 비활성. */
export default function Users() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const userId = Number(useParams().id) || null
  const [deptId, setDeptId] = useState<number | null>(null)
  const [adding, setAdding] = useState<'user' | 'dept' | null>(null)
  const [view, setView] = useState<'chart' | 'list'>('chart')
  const [showOff, setShowOff] = useState(false)
  const [find, setFind] = useState('')
  const q = useQuery({ queryKey: ['org', userId], queryFn: () => api<Org>(userId ? `${URL}?user=${userId}` : URL), placeholderData: (prev) => prev })
  const d = q.data
  const refresh = () => qc.invalidateQueries({ queryKey: ['org'] })

  const tree = useMemo<TreeDataNode[]>(() => {
    if (!d) return []
    const hit = (u: User) => !find || `${u.name}${u.username}${u.position}${u.title}`.includes(find)
    const users = d.users.filter((u) => (showOff || u.active) && hit(u))
    const userNode = (u: User): TreeDataNode => ({
      key: `u${u.id}`, isLeaf: true,
      title: (
        <span style={u.active ? undefined : { opacity: 0.55 }}>
          {u.name} <Typography.Text type="secondary">{[u.position, u.title].filter(Boolean).join(' · ')}</Typography.Text>
          {u.admin && <Tag color="red" style={{ marginInlineStart: 6 }}>관리자</Tag>}
          {!u.active && <Tag style={{ marginInlineStart: 6 }}>비활성</Tag>}
        </span>
      ),
    })
    const deptNode = (x: Dept): TreeDataNode => {
      const mine = users.filter((u) => u.dept === x.id)
      return {
        key: `d${x.id}`,
        title: <span><b>{x.name}</b> <Typography.Text type="secondary">{mine.length}명</Typography.Text>{!x.active && <Tag style={{ marginInlineStart: 6 }}>사용 안 함</Tag>}</span>,
        children: [...d.depts.filter((c) => c.parent === x.id && (showOff || c.active)).map(deptNode), ...mine.map(userNode)],
      }
    }
    const loose = users.filter((u) => u.dept == null)
    return [...d.depts.filter((x) => x.parent == null && (showOff || x.active)).map(deptNode),
      { key: NONE, title: <span><b>부서 없음</b> <Typography.Text type="secondary">{loose.length}명</Typography.Text></span>, children: loose.map(userNode) }]
  }, [d, showOff, find])

  if (q.isLoading) return <Spin />
  if (!d) return <Alert type="error" showIcon title={q.error instanceof ApiError ? q.error.detail : '불러오지 못했습니다.'} />

  const deptOf = (key: string): number | null => {  // 끌어 놓은 곳의 부서
    if (key === NONE) return null
    if (key.startsWith('d')) return Number(key.slice(1))
    return d.users.find((u) => `u${u.id}` === key)?.dept ?? null
  }
  const onDrop: TreeProps['onDrop'] = (info) => {
    const from = String(info.dragNode.key), to = String(info.node.key)
    // 형제 사이(틈)에 놓으면 그 노드의 상위 부서로, 부서 위에 놓으면 그 부서로
    return move(from, info.dropToGap && to.startsWith('d') ? d.depts.find((x) => `d${x.id}` === to)?.parent ?? null : deptOf(to))
  }
  /** 사람(u…)이나 부서(d…)를 target 부서로 옮긴다. 순환은 서버(Department.clean)가 막는다 */
  const move = async (from: string, target: number | null) => {
    try {
      if (from.startsWith('u')) await post({ action: 'move_user', id: Number(from.slice(1)), dept: target })
      else if (from.startsWith('d')) await post({ action: 'move_dept', id: Number(from.slice(1)), parent: target })
      else return
      message.success('옮겼습니다.')
      await refresh()
    } catch (e) {
      message.error(errText(e))
    }
  }
  const select = (key: string) => {
    setAdding(null)
    if (key.startsWith('u')) nav(`/users/${key.slice(1)}`)
    else {
      setDeptId(key === NONE ? null : Number(key.slice(1)))
      if (userId) nav('/users')
    }
  }
  const user = d.users.find((u) => u.id === userId)
  const dept = d.depts.find((x) => x.id === deptId)
  const add = (what: 'user' | 'dept') => { setAdding(what); setDeptId(null); if (userId) nav('/users') }
  const close = () => { setAdding(null); setDeptId(null); if (userId) nav('/users') }
  const panel = adding === 'user' ? <UserForm key="new" org={d} onDone={async (id) => { setAdding(null); await refresh(); nav(`/users/${id ?? ''}`) }} />
    : adding === 'dept' ? <DeptForm key="new-dept" org={d} onDone={async (id) => { setAdding(null); await refresh(); setDeptId(id ?? null) }} />
      : user ? <UserForm key={user.id} org={d} user={user} onDone={refresh} />
        : dept ? <DeptForm key={dept.id} org={d} dept={dept} onDone={refresh} />
          : null
  const tools = (
    <Space wrap style={{ marginBottom: 12 }}>
      <Segmented value={view} onChange={(v) => setView(v as 'chart' | 'list')} options={[{ value: 'chart', label: '조직도' }, { value: 'list', label: '목록' }]} />
      <Input.Search allowClear placeholder="이름·아이디·직위" aria-label="인원 찾기" onChange={(e) => setFind(e.target.value)} style={{ width: 200 }} />
      <Checkbox checked={showOff} onChange={(e) => setShowOff(e.target.checked)}>비활성·사용 안 함 포함</Checkbox>
      <Button onClick={() => add('dept')}>부서 추가</Button>
      <Button type="primary" onClick={() => add('user')}>사용자 추가</Button>
    </Space>
  )

  if (view === 'chart') return (
    <div>
      <h1 className="page-title">사용자·조직도</h1>
      {tools}
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
        사람이나 부서 이름을 끌어 다른 부서 상자에 놓으면 옮겨집니다. 부서를 빈 곳에 놓으면 최상위 부서가 됩니다.
      </Typography.Paragraph>
      <OrgChart org={d} showOff={showOff} find={find} picked={user ? `u${user.id}` : dept ? `d${dept.id}` : ''} onPick={select} onMove={move} />
      <Drawer open={!!panel} onClose={close} size="large" destroyOnHidden>{panel}</Drawer>
    </div>
  )
  return (
    <div>
      <h1 className="page-title">사용자·조직도</h1>
      {tools}
      <Row gutter={16}>
        <Col xs={24} lg={10}>
          <Card size="small" title="조직도">
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              인원이나 부서를 끌어 다른 부서 위에 놓으면 옮겨집니다.
            </Typography.Paragraph>
            <Tree blockNode draggable={{ icon: false }} showLine defaultExpandAll key={`${showOff}${find}`} treeData={tree}
              selectedKeys={user ? [`u${user.id}`] : dept ? [`d${dept.id}`] : []}
              allowDrop={({ dropNode, dropPosition }) => !(String(dropNode.key).startsWith('u') && dropPosition === 0)}
              onDrop={onDrop} onSelect={(keys) => keys[0] != null && select(String(keys[0]))} />
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          {panel ?? <Card size="small"><Empty description="왼쪽 조직도에서 부서나 인원을 고르세요." /></Card>}
        </Col>
      </Row>
    </div>
  )
}

/** 위에서 아래로 내려가는 조직도: 부서 상자(부서장·인원 직위)를 선으로 잇는다. 누르면 오른쪽 창 */
function OrgChart({ org, showOff, find, picked, onPick, onMove }: {
  org: Org; showOff: boolean; find: string; picked: string; onPick: (key: string) => void; onMove: (from: string, target: number | null) => void
}) {
  const [drag, setDrag] = useState('')  // 끌고 있는 u…/d…
  const [over, setOver] = useState('')  // 놓일 곳(부서 상자 d…, 부서 없음 none, 빈 곳 root)
  // Chromium은 <button>에서 끌기를 시작하지 않아 div role=button으로 둔다(Enter·Space로도 연다)
  const grab = (key: string) => ({
    role: 'button', tabIndex: 0, draggable: true,
    onClick: () => onPick(key),
    onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(key) } },
    onDragStart: (e: DragEvent) => { e.stopPropagation(); e.dataTransfer.setData('text/plain', key); e.dataTransfer.effectAllowed = 'move'; setDrag(key) },
    onDragEnd: () => { setDrag(''); setOver('') },
  })
  // 사람은 부서 상자·부서 없음에, 부서는 다른 부서 상자·빈 곳(최상위)에 놓는다
  const zone = (key: string, target: number | null) => {
    const ok = () => !!drag && drag !== key && (drag.startsWith('u') ? key !== 'root' : key !== 'none')
    return {
      onDragOver: (e: DragEvent) => { if (!ok()) return; e.preventDefault(); e.stopPropagation(); setOver(key) },
      onDrop: (e: DragEvent) => {
        if (!ok()) return
        e.preventDefault(); e.stopPropagation()
        const from = drag
        setDrag(''); setOver('')
        const now = from.startsWith('u') ? org.users.find((u) => `u${u.id}` === from)?.dept : org.depts.find((x) => `d${x.id}` === from)?.parent
        if ((now ?? null) !== target) onMove(from, target)
      },
    }
  }
  const hot = (key: string) => (drag && over === key ? ' org-drop' : '')
  const users = org.users.filter((u) => (showOff || u.active) && (!find || `${u.name}${u.username}${u.position}${u.title}`.includes(find)))
  const kids = (p: number | null) => org.depts.filter((x) => x.parent === p && (showOff || x.active))
  const cls = (base: string, key: string, on: boolean) => `${base}${picked === key ? ' org-picked' : ''}${on ? '' : ' org-off'}`
  const person = (u: User) => (
    <div key={u.id} className={cls('org-person', `u${u.id}`, u.active)} {...grab(`u${u.id}`)}>
      {u.name} <span className="flow-sub">{[u.position, u.title].filter(Boolean).join(' · ')}</span>
    </div>
  )
  // 부서장 → 직책 있는 사람 → 나머지
  const people = (dept: number | null, head: number | null) => users.filter((u) => u.dept === dept)
    .sort((a, b) => Number(b.id === head) - Number(a.id === head) || Number(!!b.title) - Number(!!a.title))
  const node = (x: Dept) => (
    <li key={x.id}>
      <div className={cls('org-node', `d${x.id}`, x.active) + hot(`d${x.id}`)} {...zone(`d${x.id}`, x.id)}>
        <div className="org-dept" {...grab(`d${x.id}`)}>
          {x.name}{x.manager && <span className="flow-sub">부서장 {x.manager}</span>}
        </div>
        {people(x.id, x.manager_id).map(person)}
      </div>
      {kids(x.id).length > 0 && <ul>{kids(x.id).map(node)}</ul>}
    </li>
  )
  const loose = people(null, null)
  return (
    <div className={'org-chart' + hot('root')} aria-label="조직도" {...zone('root', null)}>
      {kids(null).length > 0 && <ul>{kids(null).map(node)}</ul>}
      {(loose.length > 0 || drag.startsWith('u')) && (
        <div className={'org-node org-loose' + hot('none')} {...zone('none', null)}><span className="org-dept">부서 없음</span>{loose.map(person)}</div>
      )}
    </div>
  )
}

/** 부서 추가·수정(오른쪽 창). 순환·코드 중복은 서버(Department.clean)가 막는다 */
function DeptForm({ org, dept, onDone }: { org: Org; dept?: Dept; onDone: (id?: number) => void | Promise<void> }) {
  const [form] = Form.useForm()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const save = async (v: object) => {
    setBusy(true)
    setErr('')
    try {
      const r = await post({ action: 'save_dept', id: dept?.id, ...v }) as { id: number }
      message.success(dept ? '저장했습니다.' : '부서를 만들었습니다.')
      await onDone(r.id)
    } catch (e) {
      if (e instanceof ApiError) form.setFields(Object.entries(e.fields).filter(([k]) => k !== '__all__').map(([name, errors]) => ({ name, errors })))
      setErr(errText(e))
    } finally {
      setBusy(false)
    }
  }
  const members = dept ? org.users.filter((u) => u.dept === dept.id && u.active) : []
  return (
    <Card size="small" title={dept ? `${dept.name} (${dept.code})` : '새 부서'}>
      <Form form={form} layout="vertical" onFinish={save}
        initialValues={dept ? { code: dept.code, name: dept.name, parent: dept.parent, manager: dept.manager_id, sort: dept.sort, active: dept.active }
          : { code: '', name: '', parent: null, manager: null, sort: 0, active: true }}>
        <Row gutter={12}>
          <Col span={16}><Form.Item label="부서 이름" name="name" rules={[{ required: true, message: '부서 이름을 입력하세요.' }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item label="부서 코드" name="code" rules={[{ required: true, message: '부서 코드를 입력하세요.' }]}><Input /></Form.Item></Col>
          <Col span={12}><Form.Item label="상위 부서" name="parent">
            <Select allowClear showSearch optionFilterProp="label" placeholder="없음(맨 위)"
              options={org.depts.filter((x) => x.id !== dept?.id).map((x) => ({ value: x.id, label: x.name }))} />
          </Form.Item></Col>
          <Col span={12}><Form.Item label="부서장" name="manager">
            <Select allowClear showSearch optionFilterProp="label" placeholder="없음"
              options={org.users.filter((u) => u.active || u.id === dept?.manager_id).map((u) => ({ value: u.id, label: `${u.name} (${u.username})` }))} />
          </Form.Item></Col>
          <Col span={12}><Form.Item label="정렬" name="sort" extra="작을수록 왼쪽"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item label="사용" name="active" valuePropName="checked"><Switch /></Form.Item></Col>
        </Row>
        {err && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} />}
        <Button type="primary" htmlType="submit" loading={busy}>{dept ? '저장' : '만들기'}</Button>
      </Form>
      {dept && (
        <>
          <h3 className="form-section" style={{ marginTop: 24 }}>인원 {members.length}명</h3>
          {members.length ? <ul className="plain-list">{members.map((u) => (
            <li key={u.id}><Link to={`/users/${u.id}`}>{u.name}</Link> <Typography.Text type="secondary">{[u.position, u.title].filter(Boolean).join(' · ')}</Typography.Text></li>
          ))}</ul> : <Typography.Text type="secondary">인원이 없습니다. 사용자 창의 「부서」에서 배치합니다.</Typography.Text>}
        </>
      )}
    </Card>
  )
}

type Values = Omit<User, 'id' | 'name' | 'last_login'> & { password?: string }

function UserForm({ org, user, onDone }: { org: Org; user?: User; onDone: (id?: number) => void | Promise<void> }) {
  const [form] = Form.useForm<Values>()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [sign, setSign] = useState<Values | null>(null)
  const [reset, setReset] = useState(false)
  useEffect(() => setErr(''), [user])
  const isMe = user?.id === org.me

  const save = async (v: Values, adminPassword?: string) => {
    setBusy(true)
    setErr('')
    try {
      await post({ action: 'save_user', id: user?.id, ...v, admin_password: adminPassword })
      message.success(user ? '저장했습니다.' : '사용자를 만들었습니다.')
      const fresh = user ? undefined : (await api<Org>(URL)).users.find((u) => u.username === v.username)?.id
      await onDone(fresh)
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).some((k) => k !== 'admin_password')) {
        form.setFields(Object.entries(e.fields).filter(([k]) => k !== '__all__').map(([name, errors]) => ({ name: name as keyof Values, errors })))
      }
      setErr(errText(e))
      throw e
    } finally {
      setBusy(false)
    }
  }
  // 새 사용자, 역할·관리자 권한 변경은 관리자 비밀번호를 다시 받는다(서버도 검사)
  const submit = (v: Values) => {
    const roles = (a: string[]) => [...a].sort().join()
    const needSign = !user || roles(v.groups) !== roles(user.groups) || v.admin !== user.admin
    if (needSign) setSign(v)
    else save(v).catch(() => {})
  }

  return (
    <Card size="small" title={user ? `${user.name} (${user.username})` : '새 사용자'}
      extra={user && <Button size="small" onClick={() => setReset(true)}>비밀번호 초기화</Button>}>
      <Form form={form} layout="vertical" onFinish={submit}
        initialValues={user ?? { username: '', last_name: '', first_name: '', email: '', dept: null, employee_no: '', position: '', title: '', phone: '', groups: [], admin: false, active: true }}>
        <h3 className="form-section">인사 정보</h3>
        <Row gutter={12}>
          <Col span={6}><Form.Item label="성" name="last_name"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item label="이름" name="first_name"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item label="부서" name="dept">
            <Select allowClear showSearch optionFilterProp="label" placeholder="부서 없음"
              options={org.depts.filter((x) => x.active || x.id === user?.dept).map((x) => ({ value: x.id, label: x.name }))} />
          </Form.Item></Col>
          <Col span={6}><Form.Item label="사번" name="employee_no"><Input /></Form.Item></Col>
          <Col span={6}><Form.Item label="직위" name="position"><Input placeholder="사원·대리·과장" /></Form.Item></Col>
          <Col span={6}><Form.Item label="직책" name="title"><Input placeholder="팀장·파트장" /></Form.Item></Col>
          <Col span={6}><Form.Item label="연락처" name="phone"><Input /></Form.Item></Col>
        </Row>
        <h3 className="form-section">계정</h3>
        <Row gutter={12}>
          <Col span={8}><Form.Item label="아이디" name="username" rules={[{ required: true, message: '아이디를 입력하세요.' }]}><Input autoComplete="off" /></Form.Item></Col>
          <Col span={16}><Form.Item label="메일" name="email"><Input type="email" /></Form.Item></Col>
          {!user && <Col span={8}><Form.Item label="초기 비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}><Input.Password autoComplete="new-password" /></Form.Item></Col>}
          <Col span={8}><Form.Item label="계정 사용" name="active" valuePropName="checked"><Switch disabled={isMe} /></Form.Item></Col>
          <Col span={8}><Form.Item label="시스템 관리자" name="admin" valuePropName="checked"><Switch disabled={isMe} /></Form.Item></Col>
        </Row>
        <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
          {isMe ? '자기 계정은 끄거나 관리자 권한을 뗄 수 없습니다.' : '사용자는 지우지 않고 「계정 사용」을 끕니다. 끄면 로그인할 수 없고 기록은 남습니다.'}
        </Typography.Paragraph>
        <h3 className="form-section">역할</h3>
        <Form.Item name="groups" extra="품질팀장 = 승인자. 역할·관리자 권한을 바꾸면 관리자 비밀번호를 다시 묻습니다.">
          <Checkbox.Group options={org.groups} />
        </Form.Item>
        {err && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} />}
        <Button type="primary" htmlType="submit" loading={busy}>{user ? '저장' : '만들기'}</Button>
      </Form>
      {user && (
        <>
          <h3 className="form-section" style={{ marginTop: 24 }}>계정 변경 기록</h3>
          {org.log?.length ? (
            <ul className="plain-list">{org.log.map((l, i) => <li key={i}>{dayjs(l.at).format('YYYY-MM-DD HH:mm')} · {l.by} · {l.text}</li>)}</ul>
          ) : <Typography.Text type="secondary">기록이 없습니다.</Typography.Text>}
          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
            마지막 로그인 {user.last_login ? dayjs(user.last_login).format('YYYY-MM-DD HH:mm') : '없음'}
          </Typography.Paragraph>
        </>
      )}
      <SignModal open={!!sign} onClose={() => setSign(null)} title="관리자 비밀번호 확인"
        onSubmit={async (pw) => { if (sign) await save(sign, pw) }} />
      {user && <ResetModal open={reset} user={user} onClose={() => setReset(false)} onDone={onDone} />}
    </Card>
  )
}

function ResetModal({ open, user, onClose, onDone }: { open: boolean; user: User; onClose: () => void; onDone: () => void | Promise<void> }) {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (v: { password: string; admin_password: string }) => {
    setBusy(true)
    setErr('')
    try {
      await post({ action: 'reset_password', id: user.id, ...v })
      message.success('비밀번호를 바꿨습니다. 새 비밀번호를 본인에게 알려 주세요.')
      onClose()
      await onDone()
    } catch (e) {
      setErr(e instanceof ApiError ? Object.values(e.fields).flat().join(' ') || e.detail : '바꾸지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title={`${user.name} 비밀번호 초기화`} footer={null} destroyOnHidden>
      <Form layout="vertical" onFinish={submit}>
        <Form.Item label="새 비밀번호" name="password" rules={[{ required: true, message: '새 비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item label="관리자 비밀번호" name="admin_password" rules={[{ required: true, message: '관리자 비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {err && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={busy}>바꾸기</Button>
          <Button onClick={onClose}>취소</Button>
        </Space>
      </Form>
    </Modal>
  )
}
