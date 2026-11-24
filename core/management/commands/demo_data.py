"""메뉴별 사용성 검토용 예시 데이터. 자동차 부품 공장(ISO 9001·IATF 16949) 가정.
행만 더한다: 기존 행은 지우거나 바꾸지 않고, 이 명령이 만든 행(품번·LOT·번호의 EX- 머리글)은 다시 돌려도 중복되지 않는다.
모델의 save()/clean()과 qms/rules.py의 규칙 함수를 거치므로 업무 규칙(보류 인터록·승인 잠금·검사 자격)이 그대로 적용된다.
주의: 검사원 자격·계측기가 등록되면 그 규칙(자격자만 판정, 계량형 항목은 계측기 필수)이 이 DB 전체에 적용된다."""
import datetime
from collections import Counter
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (BomLine, CodeValue, Department, FieldDef, ImportProfile, Item, Lot, LotLink, Nonconformance,
                         NumberRule, Partner, Process, RoutingStep, Shipment, WorkOrder, WorkResult)
from qms.models import (AuditChecklist, AuditFinding, AuditItem, Capa, Characteristic, ChangeRequest, ControlPlan,
                        ControlPlanLine, CustomerClaim, CustomerRule, Document, Evidence, Gauge, GaugeCalibration,
                        InternalAudit, Inspection, InspectionSpec, Memo, PpapSubmission, Qualification, Scar, add_months)
from qms.rules import new_spec_revision, receive_lot, submit_inspection

D = Decimal

# 메뉴 중 데이터를 넣지 않는 것과 이유
SKIPPED = [
    ('내 할 일 · 공장 종합현황 · 품질 KPI · 공급자 평가 · LOT 추적 · 심사 자료 출력', '다른 기록에서 계산해 보여 주는 화면이라 넣을 행이 없다'),
    ('엑셀 보고서 양식', '엑셀 양식 파일(.xlsx)이 있어야 해서 건너뜀'),
    ('문서 개정(문서 관리 하위)', '원본 파일 첨부가 필수라 건너뜀(문서 자체는 넣음)'),
    ('사용자 · 모듈 설정 · 관리자 화면 · 감사 추적', '보안·설정 화면이라 건너뜀(서명용 예시 사용자 3명만 사용 불가 비밀번호로 만듦)'),
]


class Command(BaseCommand):
    help = '모든 하위 메뉴에 예시 데이터를 채운다(행만 추가, 다시 실행해도 중복 없음).'

    def handle(self, *args, **opts):
        before = self._counts()
        with transaction.atomic():
            self.now, self.today = timezone.now(), timezone.localdate()
            self.users()
            self.masters()
            self.items()
            self.gauges()
            self.plans_and_specs()
            self.production()
            self.inspections()
            self.shipments()
            self.changes()
            self.quality()
            self.documents_and_audits()
            self.memos()
            self.personal()
        after = self._counts()
        self.stdout.write('예시 데이터 생성 결과 (모델: 새로 만든 행)')
        for model, n in after.items():
            if n > before[model]:
                self.stdout.write(f'  {model._meta.verbose_name}: {n - before[model]}건')
        if after == before:
            self.stdout.write('  새로 만든 행 없음(이미 있음)')
        for menu, why in SKIPPED:
            self.stdout.write(f'건너뜀 - {menu}: {why}')

    @staticmethod
    def _counts():
        out = Counter()
        for app in ('core', 'qms', 'personal'):
            for m in apps.get_app_config(app).get_models():
                if not m.__name__.startswith('Historical'):
                    out[m] = m.objects.count()
        return out

    def get(self, model, lookup, **defaults):
        return model.objects.get_or_create(**lookup, defaults=defaults)[0]

    # ---------- 사용자(서명용, 비밀번호 사용 불가) ----------
    def users(self):
        User = get_user_model()
        self.u = {}
        for key, name, group in (('inspector', '검사원', '검사원'), ('lead', '팀장', '품질팀장'), ('engineer', '엔지니어', '품질엔지니어')):
            user, new = User.objects.get_or_create(username=f'ex_{key}', defaults={'last_name': '예시', 'first_name': name})
            if new:
                user.set_unusable_password()
                user.save()
                user.groups.add(Group.objects.get_or_create(name=group)[0])
            self.u[key] = user

    # ---------- 기준정보: 부서·사용자 정의 필드·거래처·채번 ----------
    def masters(self):
        root = self.get(Department, {'code': 'EX-D00'}, name='예시 공장', sort=0)
        for code, name, parent in (('EX-D10', '품질팀', root), ('EX-D20', '생산팀', root), ('EX-D30', '설비팀', root)):
            self.get(Department, {'code': code}, name=name, parent=parent, sort=int(code[-2:]), manager=self.u['lead'] if code == 'EX-D10' else None)
        self.get(Department, {'code': 'EX-D11'}, name='품질보증 파트', parent=Department.objects.get(code='EX-D10'), sort=11)
        self.dept = Department.objects.get(code='EX-D10')

        pct, dct = ContentType.objects.get_for_model(Partner), ContentType.objects.get_for_model(Department)
        self.get(FieldDef, {'target': pct, 'key': 'ex_region'}, label='권역', kind='choice', choices=['수도권', '영남', '호남'], sort=1)
        self.get(FieldDef, {'target': pct, 'key': 'ex_since'}, label='거래 시작일', kind='date', sort=2)
        self.get(FieldDef, {'target': dct, 'key': 'ex_cost_center'}, label='원가 센터', kind='text', sort=1)

        cs = lambda **kw: [{'role': '품질', 'name': kw['n'], 'phone': kw['p'], 'email': kw['e']}]
        P = lambda code, **kw: self.get(Partner, {'code': code}, **kw)
        self.supplier = P('EX-S01', name='한성소재(주)', is_supplier=True, status='approved', grade='A', evaluated_on=self.today,
                          contacts=cs(n='오지훈', p='031-555-0101', e='oh@example.com'), extra={'ex_region': '수도권', 'ex_since': '2019-03-01'})
        P('EX-S02', name='대진금속(주)', is_supplier=True, is_outsource=True, status='conditional', grade='C', evaluated_on=self.today,
          contacts=cs(n='최민수', p='053-555-0202', e='choi@example.com'), extra={'ex_region': '영남'})
        self.cust = {n: P(c, name=n, is_customer=True, status='approved', grade='A',
                          contacts=cs(n=q, p='02-555-03%02d' % i, e=f'qa{i}@example.com'), extra={'ex_region': '수도권'})
                     for i, (c, n, q) in enumerate((('EX-C01', '가온모터스(주)', '정하늘'), ('EX-C02', '한빛자동차(주)', '송도윤'),
                                                    ('EX-C03', '누리오토(주)', '임서연')), 1)}
        P('EX-K01', name='한국계측교정원', is_calibrator=True, status='approved', grade='A',
          contacts=cs(n='배진우', p='042-555-0401', e='cal@example.com'))
        for (name, h, d), partner in zip((('가온모터스(주)', 24, 10), ('한빛자동차(주)', 12, 7), ('누리오토(주)', 48, 14)), self.cust.values()):
            self.get(CustomerRule, {'customer': name}, partner=partner, containment_hours=h, corrective_days=d)

        # 채번 규칙·코드값: 이 명령이 만든 것만 EX 머리글로 (본 규칙은 건드리지 않는다)
        for name, target, pattern in (('EX-품번', 'ITEM', 'EX-{일련3}'), ('EX-문서', 'DOC', 'EX-DOC-{일련4}')):
            if not NumberRule.objects.filter(name=name).exists():
                r = NumberRule(name=name, target=target, pattern=pattern, sort=900)
                r.full_clean()
                r.save()
        for code, name in (('EX', '예시 고객사 A'), ('EY', '예시 고객사 B'), ('EZ', '예시 고객사 C')):
            if not CodeValue.objects.filter(group='customer', code=code).exists():
                c = CodeValue(group='customer', code=code, name=name, sort=900)
                c.full_clean()
                c.save()
        for name, target, header, mapping in (
                ('EX-품번 가져오기', 'item', 1, {'code': '품번', 'name': '품명', 'item_type': '구분'}),
                ('EX-작업지시 가져오기', 'work_order', 1, {'number': '지시번호', 'item': '품번', 'planned_qty': '수량', 'due_date': '납기'}),
                ('EX-작업지시(제목 2행)', 'work_order', 2, {'number': 'WO', 'item': 'PN', 'planned_qty': 'QTY'})):
            self.get(ImportProfile, {'name': name}, target=target, header_row=header, mapping=mapping)

    # ---------- 품목·BOM·라우팅·공정 ----------
    def items(self):
        I = lambda code, name, t: self.get(Item, {'code': code}, name=name, item_type=t)
        self.r100, self.s200 = I('EX-R100', 'SPCC 강판 1.2t', 'RAW'), I('EX-S200', '브래킷 프레스 성형품', 'SEMI')
        self.f300, self.f310 = I('EX-F300', '시트 레일 어셈블리', 'FIN'), I('EX-F310', '도어 힌지 어셈블리', 'FIN')
        self.p = {c: self.get(Process, {'code': c}, name=n) for c, n in
                  (('EX-P10', '프레스'), ('EX-P20', '용접'), ('EX-P30', '조립'), ('EX-P40', '최종검사'))}
        for parent, comp, qty in ((self.s200, self.r100, '1.5'), (self.f300, self.s200, '2'), (self.f310, self.s200, '1')):
            self.get(BomLine, {'parent': parent, 'component': comp}, qty=D(qty))
        self.step = {}
        for item, steps in ((self.s200, (10,)), (self.f300, (10, 20, 30)), (self.f310, (10, 20))):
            procs = {self.s200: ['EX-P10'], self.f300: ['EX-P20', 'EX-P30', 'EX-P40'], self.f310: ['EX-P30', 'EX-P40']}[item]
            for seq, pc in zip(steps, procs):
                self.step[item.code, seq] = self.get(RoutingStep, {'item': item, 'seq': seq}, process=self.p[pc])

    # ---------- 계측기·교정·검사원 자격 ----------
    def gauges(self):
        t, near, far = self.today, None, None
        near = add_months(t, -12) + datetime.timedelta(days=10)   # 교정 기한이 10일 뒤
        far = add_months(t, -14)                                  # 기한이 2개월 전에 지남
        rows = (('EX-G001', '마이크로미터 0-25mm', '외측 마이크로미터', '미쓰토요', 'MDC-25MX', '0-25mm', '0.001mm', add_months(t, -2), 12, 'EXTERNAL'),
                ('EX-G002', '버니어캘리퍼스 0-150mm', '버니어캘리퍼스', '블루프린트', 'BP-150', '0-150mm', '0.01mm', near, 12, 'EXTERNAL'),
                ('EX-G003', '하이트게이지 0-300mm', '하이트게이지', '미쓰토요', 'HDS-30C', '0-300mm', '0.01mm', far, 12, 'EXTERNAL'),
                ('EX-G004', '디지털 토크 테스터', '토크 테스터', '토닉', 'TT-5', '0-5N·m', '0.01N·m', add_months(t, -1), 6, 'INTERNAL'))
        self.g = {}
        for i, (no, name, kind, maker, model, rng, res, last, months, cal) in enumerate(rows, 1):
            self.g[no] = self.get(Gauge, {'number': no}, name=name, kind=kind, maker=maker, model_no=model, serial_no=f'SN-EX-{i:04d}',
                                  measuring_range=rng, resolution=res, last_calibrated=last, interval_months=months, department=self.dept,
                                  location='품질팀 계측실', owner=self.u['inspector'], cal_type=cal,
                                  cal_agency='' if cal == 'INTERNAL' else '한국계측교정원')
            # 교정 이력은 최근 교정일 이하로만 넣어 계측기의 최근 교정일·기한을 바꾸지 않는다
            if not self.g[no].calibrations.exists():
                for k, when in enumerate((add_months(last, -months), last)):
                    GaugeCalibration.objects.create(gauge=self.g[no], calibrated_on=when, cal_type=cal, result='PASS',
                                                    agency='' if cal == 'INTERNAL' else '한국계측교정원', cert_no=f'EX-CAL-{i}{k + 1}',
                                                    note='정기 교정, 기준 이내')
        until = self.today + datetime.timedelta(days=365)
        for typ, basis in (('INCOMING', '수입검사 교육 이수·실기 평가 합격'), ('PROCESS', '공정검사 교육 이수'), ('OUTGOING', '출하검사 교육 이수')):
            self.get(Qualification, {'user': self.u['inspector'], 'inspection_type': typ}, valid_until=until, basis=basis)
        self.get(Qualification, {'user': self.u['lead'], 'inspection_type': 'OUTGOING'}, valid_until=self.today - datetime.timedelta(days=30),
                 basis='출하검사 교육 이수(유효기한 지남, 갱신 필요)')

    # ---------- 관리계획서·검사기준서 ----------
    def approve(self, obj):
        obj.approved_by, obj.approved_at = self.u['lead'], self.now
        obj.save()

    def make_plan(self, item, lines):
        if ControlPlan.objects.filter(item=item, stage='PRODUCTION', revision=1).exists():
            return
        plan = ControlPlan.objects.create(item=item, stage='PRODUCTION', revision=1)
        for proc, char, sp, lsl, usl, unit, method, samp, typ, react, mode, s, o, d in lines:
            ControlPlanLine.objects.create(plan=plan, process=self.p[proc], characteristic=char, special=sp, lsl=lsl, usl=usl, unit=unit,
                                           method=method, sampling=samp, inspection_type=typ, reaction=react, failure_mode=mode,
                                           severity=s, occurrence=o, detection=d)
        self.approve(plan)

    def make_spec(self, item, typ, sampling, chars):
        if InspectionSpec.objects.filter(item=item, inspection_type=typ, revision=1).exists():
            return
        spec = InspectionSpec.objects.create(item=item, inspection_type=typ, revision=1, sampling=sampling, note='예시 데이터')
        plan = ControlPlan.objects.filter(item=item, stage='PRODUCTION').first()
        for name, lsl, usl, unit, sp, gk in chars:
            line = plan and plan.lines.filter(characteristic=name).first()
            Characteristic.objects.create(spec=spec, name=name, lsl=lsl, usl=usl, unit=unit, special=sp, plan_line=line, gauge_kind=gk)
        self.approve(spec)

    def plans_and_specs(self):
        # (공정, 특성, 특별특성, 하한, 상한, 단위, 측정방법, 샘플링, 검사구분, 이상 시 조치, 잠재 고장모드, S, O, D)
        self.make_plan(self.s200, [
            ('EX-P10', '홀 직경', 'SC', D('9.95'), D('10.05'), 'mm', '핀게이지', 'n=5/2h', 'PROCESS', '전수 선별 후 금형 점검', '홀 직경 불량', 7, 4, 4),
            ('EX-P10', '평탄도', '', None, D('0.2'), 'mm', '하이트게이지', 'n=3/4h', 'PROCESS', '격리 후 보고', '변형', 5, 3, 5)])
        self.make_plan(self.f300, [
            ('EX-P20', '전장', 'CC', D('249.7'), D('250.3'), 'mm', '버니어캘리퍼스', 'n=5/LOT', 'OUTGOING', '출하 보류', '치수 불량', 9, 3, 4),
            ('EX-P30', '슬라이드 하중', '', D('800'), None, 'N', '하중 시험기', 'n=3/LOT', 'OUTGOING', '재시험 후 보류', '작동 불량', 8, 2, 5)])
        self.make_plan(self.f310, [
            ('EX-P30', '개폐 토크', 'SC', D('1.0'), D('2.0'), 'N·m', '토크 테스터', 'n=5/LOT', 'OUTGOING', '출하 보류', '개폐 불량', 7, 3, 4)])
        self.make_spec(self.r100, 'INCOMING', 'AQL 0.65 일반검사수준 II, n=5',
                       [('두께', D('1.15'), D('1.25'), 'mm', '', '외측 마이크로미터'), ('폭', D('99.8'), D('100.2'), 'mm', '', '버니어캘리퍼스'),
                        ('외관', None, None, '', '', '')])
        self.make_spec(self.s200, 'PROCESS', 'n=5/2h',
                       [('홀 직경', D('9.95'), D('10.05'), 'mm', 'SC', '핀게이지'), ('평탄도', None, D('0.2'), 'mm', '', '하이트게이지'),
                        ('외관', None, None, '', '', '')])
        self.make_spec(self.f300, 'OUTGOING', 'n=5/LOT',
                       [('전장', D('249.7'), D('250.3'), 'mm', 'CC', '버니어캘리퍼스'), ('슬라이드 하중', D('800'), None, 'N', '', ''),
                        ('외관', None, None, '', '', '')])
        self.make_spec(self.f310, 'OUTGOING', 'n=5/LOT', [('개폐 토크', D('1.0'), D('2.0'), 'N·m', 'SC', '토크 테스터'), ('외관', None, None, '', '', '')])

    # ---------- 작업지시·LOT·계보·생산실적 ----------
    def production(self):
        t = self.now
        due = lambda d: self.today + datetime.timedelta(days=d)
        wo = {n: self.get(WorkOrder, {'number': n}, item=i, process=pr, planned_qty=D(q), due_date=due(d))
              for n, i, pr, q, d in (('EX-WO-001', self.f300, self.p['EX-P20'], 500, 14), ('EX-WO-002', self.s200, self.p['EX-P10'], 3000, 7),
                                     ('EX-WO-003', self.f310, self.p['EX-P30'], 300, 21), ('EX-WO-004', self.f310, self.p['EX-P30'], 400, 30))}
        # 원자재 입고(receive_lot) → 반제품 → 완제품 (병합·분할 계보)
        for no, qty in (('EX-L-R100-01', '5000'), ('EX-L-R100-02', '3000'), ('EX-L-R100-03', '2000')):
            lot, new = receive_lot(no, self.r100, qty, self.supplier.name)
            if new:
                lot.partner = self.supplier
                lot.save()
        L = lambda no, item, w, qty: self.get(Lot, {'number': no}, item=item, work_order=wo[w], qty=D(qty))
        for no, w, q in (('EX-L-S200-01', 'EX-WO-002', 1000), ('EX-L-S200-02', 'EX-WO-002', 800), ('EX-L-S200-03', 'EX-WO-002', 500)):
            L(no, self.s200, w, q)
        for no, w, q in (('EX-L-F300-01', 'EX-WO-001', 200), ('EX-L-F300-02', 'EX-WO-001', 300), ('EX-L-F300-03', 'EX-WO-001', 150),
                         ('EX-L-F300-04', 'EX-WO-001', 100)):
            L(no, self.f300, w, q)
        for no, w, q in (('EX-L-F310-01', 'EX-WO-003', 120), ('EX-L-F310-02', 'EX-WO-003', 80)):
            L(no, self.f310, w, q)
        lot = lambda no: Lot.objects.get(number=no)
        for parent, child, qty in (('R100-01', 'S200-01', 1200), ('R100-02', 'S200-01', 800), ('R100-02', 'S200-02', 1000), ('R100-01', 'S200-03', 500),
                                   ('S200-01', 'F300-01', 400), ('S200-01', 'F300-02', 600), ('S200-01', 'F300-03', 300),
                                   ('S200-02', 'F300-04', 200), ('S200-02', 'F310-01', 120), ('S200-02', 'F310-02', 80)):
            self.get(LotLink, {'parent': lot(f'EX-L-{parent}'), 'child': lot(f'EX-L-{child}')}, qty=D(qty))
        # 생산실적: 라우팅 순서대로(이전 공정 양품 실적이 있어야 다음 공정 등록)
        hour = lambda h: t - datetime.timedelta(hours=h)
        for w, item, seq, lno, inp, good, bad, h in (
                ('EX-WO-002', self.s200, 10, 'S200-01', 1020, 1000, 20, 40), ('EX-WO-002', self.s200, 10, 'S200-02', 820, 800, 20, 36),
                ('EX-WO-002', self.s200, 10, 'S200-03', 520, 500, 20, 32),
                ('EX-WO-001', self.f300, 10, 'F300-01', 210, 205, 5, 30), ('EX-WO-001', self.f300, 10, 'F300-02', 310, 300, 10, 28),
                ('EX-WO-001', self.f300, 20, 'F300-01', 205, 200, 5, 24), ('EX-WO-001', self.f300, 30, 'F300-01', 200, 200, 0, 20),
                ('EX-WO-003', self.f310, 10, 'F310-01', 125, 120, 5, 16), ('EX-WO-003', self.f310, 20, 'F310-01', 120, 118, 2, 12),
                ('EX-WO-003', self.f310, 10, 'F310-02', 82, 80, 2, 10)):
            step, l = self.step[item.code, seq], lot(f'EX-L-{lno}')
            if not WorkResult.objects.filter(work_order=wo[w], step=step, lot=l).exists():
                WorkResult.objects.create(work_order=wo[w], step=step, lot=l, input_qty=D(inp), good_qty=D(good), defect_qty=D(bad),
                                          operator=self.u['inspector'], started_at=hour(h + 3), ended_at=hour(h))
        WorkOrder.objects.filter(number='EX-WO-002', status='RUNNING').update(status='DONE')  # 실적 등록이 이미 진행으로 올렸다, 완료 상태 예시 1건

    # ---------- 검사 실적(입고·공정·출하) ----------
    def inspect(self, lot_no, typ, gauge, vals, defect_type=''):
        lot = Lot.objects.get(number=lot_no)
        if Inspection.objects.filter(lot=lot, spec__inspection_type=typ).exists():
            return
        spec = InspectionSpec.current(lot.item, typ)
        values = {c.pk: vals[c.name] for c in spec.characteristics.all()}
        submit_inspection(lot, spec, self.u['inspector'], self.g[gauge], values, defect_type=defect_type, defect_qty='1')

    def inspections(self):
        for no, th, w in (('01', '1.20', '100.0'), ('02', '1.19', '100.1')):
            self.inspect(f'EX-L-R100-{no}', 'INCOMING', 'EX-G001', {'두께': th, '폭': w, '외관': 'OK'})
        for no, h, f in (('01', '10.00', '0.08'), ('02', '10.01', '0.10'), ('03', '9.99', '0.07')):
            self.inspect(f'EX-L-S200-{no}', 'PROCESS', 'EX-G001', {'홀 직경': h, '평탄도': f, '외관': 'OK'})
        for no, ln, load in (('01', '250.0', '1200'), ('02', '250.1', '1180'), ('03', '249.9', '1210')):
            self.inspect(f'EX-L-F300-{no}', 'OUTGOING', 'EX-G002', {'전장': ln, '슬라이드 하중': load, '외관': 'OK'})
        for no, tq in (('01', '1.5'), ('02', '1.6')):
            self.inspect(f'EX-L-F310-{no}', 'OUTGOING', 'EX-G004', {'개폐 토크': tq, '외관': 'OK'})
        # 불합격 2건 → 부적합 자동 등록 → LOT 보류(하위 계보 없는 LOT)
        self.inspect('EX-L-R100-03', 'INCOMING', 'EX-G001', {'두께': '1.35', '폭': '100.0', '외관': 'OK'}, '치수(두께)')
        self.inspect('EX-L-F300-04', 'OUTGOING', 'EX-G002', {'전장': '250.8', '슬라이드 하중': '1190', '외관': 'OK'}, '치수(전장)')
        # 승인 기준서의 다음 개정(초안)
        spec = InspectionSpec.objects.get(item=self.f300, inspection_type='OUTGOING', revision=1)
        if not InspectionSpec.objects.filter(item=self.f300, inspection_type='OUTGOING', revision=2).exists():
            new_spec_revision(spec)
        # 불합격 부적합 처분: 입고 불량은 폐기(보류 유지)
        nc = Inspection.objects.get(lot__number='EX-L-R100-03', spec__inspection_type='INCOMING').nonconformance
        if nc and not nc.disposition:
            nc.origin, nc.process = 'INCOMING', None
            nc.disposition, nc.approved_by, nc.approved_at = 'SCRAP', self.u['lead'], self.now
            nc.cost, nc.capa_required = 1500000, True
            nc.save()

    # ---------- 출하 (4M 변경·클레임보다 먼저) ----------
    def shipments(self):
        c = list(self.cust.values())
        for lno, cust, qty, days in (('EX-L-F300-01', c[0], 200, 5), ('EX-L-F300-02', c[0], 300, 4), ('EX-L-F310-01', c[1], 120, 3)):
            if not Shipment.objects.filter(lot__number=lno).exists():
                Shipment.objects.create(lot=Lot.objects.get(number=lno), customer=cust.name, partner=cust, qty=D(qty),
                                        shipped_at=self.now - datetime.timedelta(days=days))

    # ---------- 4M 변경 ----------
    def changes(self):
        ago = lambda d: self.now - datetime.timedelta(days=d)
        for no, item, cat, desc, notice, ref, eff, ok in (
                ('EX-CR-001', self.s200, 'MACHINE', '프레스 금형 교체(마모 보수)', True, 'EX-CUST-APR-001', ago(3), True),
                ('EX-CR-002', self.f300, 'METHOD', '용접 순서 변경', False, '', ago(2), True),
                ('EX-CR-003', self.f310, 'MATERIAL', '힌지 핀 재질 변경(SUS304 → SUS316)', True, '', self.now + datetime.timedelta(days=10), False)):
            if not ChangeRequest.objects.filter(number=no).exists():
                cr = ChangeRequest(number=no, item=item, category=cat, description=desc, customer_notice=notice, customer_approval_ref=ref,
                                   effective_at=eff)
                if ref:
                    cr.customer_status = ChangeRequest.C_APPROVED
                if ok:
                    cr.approved_by, cr.approved_at = self.u['lead'], self.now
                else:  # 승인 전 = 진행 단계로 표시(W6)
                    cr.stage, cr.customer_status, cr.reviewer = ChangeRequest.REVIEW, ChangeRequest.C_REQUESTED, self.u['lead']
                    cr.review_comment = '내식성 시험 성적서 받은 뒤 승인 서명'
                cr.save()

    # ---------- 부적합·클레임·CAPA·SCAR·PPAP ----------
    def nc(self, lot_no, tag, **kw):
        if not Nonconformance.objects.filter(lot__number=lot_no, description__startswith=f'[예시] {tag}').exists():
            return Nonconformance.objects.create(lot=Lot.objects.get(number=lot_no), detected_by=self.u['inspector'],
                                                 description=f'[예시] {tag}', **kw)

    def quality(self):
        nc = self.nc('EX-L-S200-03', '프레스 홀 버(burr) 발생', origin='PROCESS', process=self.p['EX-P10'], defect_type='외관(버)',
                     defect_qty=D(12), inspected_qty=D(500), contained_qty=D(12), sorting_result='재공 전수 선별, 12개 격리',
                     measured_value='버 높이 0.15mm (규격 0.1 이하)')
        if nc:  # 특채: 고객 승인번호 + MRB 승인 → 보류 해제
            nc.disposition, nc.customer_approval_ref = 'CONCESSION', 'EX-CUST-APR-002'
            nc.approved_by, nc.approved_at, nc.capa_required = self.u['lead'], self.now, False
            nc.save()
        nc = self.nc('EX-L-F300-03', '출하 전 도금 외관 얼룩', origin='OUTGOING', process=self.p['EX-P40'], defect_type='외관(얼룩)',
                     defect_qty=D(6), inspected_qty=D(150), contained_qty=D(6), sorting_result='재고 150개 선별, 6개 격리', special_char='SC')
        nc = self.nc('EX-L-F310-02', '고객 반품 - 힌지 소음', origin='RETURN', defect_type='소음', defect_qty=D(4), inspected_qty=D(80),
                     contained_qty=D(4), sorting_result='반품 4개 격리')
        if nc:
            nc.disposition, nc.approved_by, nc.approved_at = 'RETURN', self.u['lead'], self.now
            nc.save()

        # 고객 클레임(8D): 접수 = 부적합 자동 등록 + LOT 보류
        c = list(self.cust.values())
        full = dict(d1_team='품질 팀장·생산 반장·설비 담당', d2_problem='시트 레일 전장이 도면 상한보다 큼', d3_containment='재고·재공·출하분 선별, 의심 LOT 격리',
                    d4_root_cause='용접 지그 마모로 위치 편차', d5_corrective='지그 교체, 설비 점검 주기 단축', d6_verification='3개 LOT 전수 측정 합격',
                    d7_prevention='지그 수명 관리표 도입', d8_closure='팀 인정, 종결')
        for no, cust, lno, desc, qty, extra in (
                ('EX-CLM-001', c[0], 'EX-L-F300-01', '시트 레일 전장 규격 초과', 8, {**full, 'closed_at': self.now}),
                ('EX-CLM-002', c[1], 'EX-L-F310-01', '도어 힌지 개폐 소음', 5, {'d1_team': '품질·생산·설비', 'd2_problem': '개폐 시 소음 발생',
                                                                                'd3_containment': '출하 재고 선별 중'}),
                ('EX-CLM-003', c[0], 'EX-L-F300-02', '시트 레일 도금 얼룩', 3, {})):
            if not CustomerClaim.objects.filter(number=no).exists():
                CustomerClaim.objects.create(number=no, customer=cust.name, partner=cust, lot=Lot.objects.get(number=lno), description=desc,
                                             defect_qty=D(qty), received_at=self.now - datetime.timedelta(days=4), **extra)

        # SCAR
        r = lambda n: Lot.objects.get(number=f'EX-L-R100-{n}')
        ncin = r('03').nonconformances.first()
        for no, lno, req, due, resp in (
                ('EX-SCAR-001', '03', '두께 불량 LOT의 원인 분석과 재발 방지 대책 회신', 14, ''),
                ('EX-SCAR-002', '02', '표면 녹 발생 이력 조사', -3, ''),
                ('EX-SCAR-003', '01', '코일 폭 편차 개선 요청', 20, '압연기 롤 교체, 폭 관리 한계 강화')):
            if not Scar.objects.filter(number=no).exists():
                Scar.objects.create(number=no, supplier=self.supplier.name, partner=self.supplier, lot=r(lno), nonconformance=ncin if lno == '03' else None,
                                    request=req, response_due=self.today + datetime.timedelta(days=due), response=resp,
                                    responded_at=self.today if resp else None, closed_at=self.today if resp else None)

        # CAPA
        ncct = ContentType.objects.get_for_model(Nonconformance)
        d = lambda n: self.today + datetime.timedelta(days=n)
        for title, src, due, done, eff in (
                ('입고 두께 불량 재발 방지(공급자 관리)', 'SCAR', d(20), None, None),
                ('프레스 금형 마모 점검 주기 단축', 'NC', d(-5), None, None),
                ('용접 지그 교체 및 수명 관리', '8D', d(-20), d(-10), True)):
            if not Capa.objects.filter(title=title).exists():
                kw = dict(root_cause='원인 분석 중' if not done else '지그 마모로 위치 편차', action='점검 주기 단축·교육 시행', owner=self.u['engineer'])
                if done:
                    kw.update(done_at=done, effective=True, verified_at=d(-2), verified_by=self.u['lead'], closed_at=d(-1),
                              verification_note='3개월간 재발 0건')
                if src == 'NC' and ncin:
                    kw.update(source_type=ncct, source_id=ncin.pk)
                Capa.objects.create(title=title, source=src, due_date=due, **kw)

        # PPAP (승인 서명은 증적이 모두 있어야 해서 초안으로 둔다)
        for item, cust, level, reason in ((self.f300, c[0], 3, '신규 부품'), (self.f310, c[1], 2, '4M 변경(재질 변경)'), (self.s200, c[2], 1, '설계 변경')):
            if not PpapSubmission.objects.filter(item=item, customer=cust.name, reason=reason).exists():
                PpapSubmission.objects.create(item=item, customer=cust.name, partner=cust, level=level, reason=reason, due_date=d(30))

    # ---------- 문서·심사 ----------
    def documents_and_audits(self):
        docs = [self.get(Document, {'number': n}, title=t, doc_type=k) for n, t, k in (
            ('EX-DOC-001', '품질 매뉴얼', '품질매뉴얼'), ('EX-DOC-002', '수입검사 작업표준서', '작업표준서'), ('EX-DOC-003', '부적합품 관리 절차서', '절차서'))]
        lists = (('IATF 16949 내부심사', 'IATF 16949:2016', (('8.5.1', '생산 관리계획서 운영'), ('8.7', '부적합 출력물 관리'), ('9.2.2', '내부심사 프로그램'))),
                 ('고객사 QSA 2026', 'QSA', (('4.1', '품질 방침 공유'), ('7.1.5', '측정 시스템 교정 관리'), ('8.4', '공급자 관리'))),
                 ('ISO 9001 공정심사', 'ISO 9001:2015', (('7.2', '인적 자격 관리'), ('8.5.2', '식별·추적성'), ('10.2', '부적합·시정조치'))))
        cl = []
        for name, std, items in lists:
            ck, new = AuditChecklist.objects.get_or_create(name=name, defaults={'standard': std})
            cl.append(ck)
            if new:
                for i, (clause, req) in enumerate(items):
                    it = AuditItem.objects.create(checklist=ck, clause=clause, requirement=req)
                    Evidence.objects.create(item=it, document=docs[i % 3], note='예시 증적')
        d = lambda n: self.today + datetime.timedelta(days=n)
        audits = (('2026 상반기 공정심사 - 프레스', 'INTERNAL', cl[0], d(-60), d(-58), '프레스 공정 8.5·8.7', '생산팀'),
                  ('가온모터스 고객 심사(QSA)', 'CUSTOMER', cl[1], d(-20), d(-19), '공급자 관리·계측기 교정', '품질팀'),
                  ('ISO 9001 사후심사 준비', 'CERT', cl[2], d(30), None, '전 부서', '품질팀'))
        for name, kind, ck, plan, done, scope, dept in audits:
            if InternalAudit.objects.filter(name=name).exists():
                continue
            a = InternalAudit.objects.create(name=name, kind=kind, checklist=ck, planned_date=plan, performed_at=done, scope=scope,
                                             auditor='김심사', auditor_user=self.u['engineer'], auditee=dept, auditee_dept=Department.objects.get(code='EX-D10'))
            if name.startswith('2026'):
                major = AuditFinding.objects.create(audit=a, clause='8.7', grade='MAJOR', description='부적합품 격리 표지가 일부 누락됨')
                AuditFinding.objects.create(audit=a, clause='8.5.1', grade='OBS', description='관리계획서 최신본 비치 확인 필요')
                Capa.objects.create(title='부적합품 격리 표지 관리 강화(심사 지적)', source='AUDIT', due_date=d(30), action='격리 구역 표지 표준화',
                                    owner=self.u['engineer'], source_type=ContentType.objects.get_for_model(AuditFinding), source_id=major.pk)
                a.closed_at = d(-50)
                a.save()
            elif kind == 'CUSTOMER':
                AuditFinding.objects.create(audit=a, clause='7.1.5', grade='MINOR', description='계측기 EX-G003 교정 기한 초과')
                AuditFinding.objects.create(audit=a, clause='8.4', grade='OFI', description='공급자 평가 주기 단축 제안')

    # ---------- 미분류 메모 ----------
    def memos(self):
        for body, kind, who in (('고객 심사원: 격리 구역 표지를 더 눈에 띄게 해 달라고 함', 'CUSTOMER', '정하늘'),
                                ('감독관 구두 지적: 계측기 교정 스티커 위치 통일', 'INSPECTOR', '박감독'),
                                ('라인 반장: 프레스 2호기 소음 점검 요청', 'INTERNAL', '이반장')):
            if not Memo.objects.filter(body=body).exists():
                Memo.objects.create(body=body, speaker_kind=kind, speaker_name=who, author=self.u['lead'])

    # ---------- 연차·급여(첫 시스템 관리자 본인 몫, 실제 기록이 하나라도 있으면 건너뜀) ----------
    def personal(self):
        from personal.models import LeaveProfile, LeaveUse, PayLine, Payslip
        owner = get_user_model().objects.filter(is_superuser=True).order_by('pk').first()
        if owner is None:
            self.stdout.write('건너뜀 - 연차·급여: 시스템 관리자가 없어 본인 몫을 만들 수 없다')
            return
        if LeaveProfile.objects.filter(owner=owner).exists() or Payslip.objects.filter(owner=owner).exists():
            self.stdout.write('건너뜀 - 연차·급여: 본인 실제 기록이 있어 예시를 섞지 않는다')
            return
        self.get(LeaveProfile, {'owner': owner}, hired_on=datetime.date(2019, 3, 4))
        for used_on, days, reason in ((self.today - datetime.timedelta(days=30), '1.00', '[예시] 개인 사유'),
                                      (self.today - datetime.timedelta(days=14), '0.50', '[예시] 반차'),
                                      (self.today - datetime.timedelta(days=3), '0.25', '[예시] 반반차')):
            self.get(LeaveUse, {'owner': owner, 'reason': reason}, used_on=used_on, days=D(days))
        for k in (1, 2, 3):
            month = (self.today.replace(day=1) - datetime.timedelta(days=30 * k)).replace(day=1)
            slip, new = Payslip.objects.get_or_create(owner=owner, month=month, defaults={'base_pay': D(3000000)})
            if new:
                PayLine.objects.create(payslip=slip, kind='PLUS', name='연장근로수당', amount=D(250000))
                PayLine.objects.create(payslip=slip, kind='MINUS', name='국민연금', amount=D(135000))
