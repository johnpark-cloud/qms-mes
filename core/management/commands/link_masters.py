import os
from collections import Counter, defaultdict

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from simple_history.utils import bulk_update_with_history

from core.models import Department, Partner

REASON = '기준정보 연결(link_masters)'
# (앱, 모델, 글자 칸, 외래키 칸, 맞춰 볼 기준정보) — 글자 칸은 바꾸지 않고 외래키만 채운다
LINKS = [
    ('core', 'Lot', 'supplier', 'partner', 'supplier'),
    ('core', 'Shipment', 'customer', 'partner', 'customer'),
    ('qms', 'Scar', 'supplier', 'partner', 'supplier'),
    ('qms', 'CustomerRule', 'customer', 'partner', 'customer'),
    ('qms', 'CustomerClaim', 'customer', 'partner', 'customer'),
    ('qms', 'PpapSubmission', 'customer', 'partner', 'customer'),
    ('qms', 'InternalAudit', 'auditee', 'auditee_dept', 'department'),
    ('qms', 'InternalAudit', 'auditor', 'auditor_user', 'user'),
]
ROLE = {'supplier': ('is_supplier', '협력사'), 'customer': ('is_customer', '고객사')}


def _key(value):
    return ''.join(str(value).split()).casefold()  # 공백·대소문자 무시


def _index(pairs):
    found = defaultdict(set)
    for obj, names in pairs:
        for n in names:
            if n and n.strip():
                found[_key(n)].add(obj)
    return found


def build_indexes():
    User = get_user_model()
    return {
        'partner': _index((p, [p.code, p.name]) for p in Partner.objects.all()),
        'department': _index((d, [d.code, d.name]) for d in Department.objects.all()),
        'user': _index((u, [u.username, u.first_name + u.last_name, u.last_name + u.first_name])
                       for u in User.objects.all()),
    }


def match(indexes, matcher, value):
    """(연결할 대상, 문제 종류, 후보 목록). 후보가 정확히 1개일 때만 대상이 있다."""
    if matcher in ROLE:
        cands = indexes['partner'].get(_key(value), set())
        flag = ROLE[matcher][0]
        fit = [p for p in cands if getattr(p, flag)]
        if len(fit) == 1:
            return fit[0], None, fit
        if len(fit) > 1:
            return None, 'many', fit
        return None, ('role' if cands else 'none'), list(cands)
    cands = list(indexes[matcher].get(_key(value), set()))
    if len(cands) == 1:
        return cands[0], None, cands
    return None, ('many' if cands else 'none'), cands


def _code(obj):
    return getattr(obj, 'code', None) or getattr(obj, 'username', None) or str(obj)


class Command(BaseCommand):
    help = ('공급처·고객사·심사 대상 글자 값을 거래처·부서·사용자 기준정보에 연결한다. '
            '기본은 미리보기(아무것도 쓰지 않음), --apply를 주면 백업 뒤 연결한다.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='실제로 연결 (먼저 backup을 실행한다)')
        parser.add_argument('--backup-dir', default=None, help='백업 폴더 (없으면 환경변수 QMS_BACKUP_DIR)')

    def handle(self, apply, backup_dir, **opts):
        if apply:
            dest = backup_dir or os.environ.get('QMS_BACKUP_DIR')
            if not dest:
                raise CommandError('백업 폴더를 --backup-dir이나 QMS_BACKUP_DIR로 지정하세요.')
            call_command('backup', dest, stdout=self.stdout)
        indexes = build_indexes()
        plan = []
        for app_label, model_name, text, fk, matcher in LINKS:
            model = apps.get_model(app_label, model_name)
            rows = model.objects.exclude(**{text: ''})
            done = rows.filter(**{f'{fk}__isnull': False}).count()
            todo, missing, many, role = [], Counter(), {}, {}
            for obj in rows.filter(**{f'{fk}__isnull': True}):
                value = getattr(obj, text).strip()
                if not value:
                    continue
                target, problem, cands = match(indexes, matcher, value)
                if target is not None:
                    setattr(obj, fk, target)
                    todo.append(obj)
                elif problem == 'none':
                    missing[value] += 1
                elif problem == 'many':
                    many[value] = sorted(_code(c) for c in cands)
                else:
                    role[value] = sorted(_code(c) for c in cands)
            self.stdout.write(f'[{model._meta.verbose_name} {model._meta.get_field(text).verbose_name} → '
                              f'{model._meta.get_field(fk).verbose_name}] 연결 가능 {len(todo)}, 이미 연결 {done}')
            if missing:
                self.stdout.write('  못 찾음: ' + ', '.join(f'{v}({n})' for v, n in sorted(missing.items())))
            for v, codes in sorted(many.items()):
                self.stdout.write(f'  여러 후보: {v} → {", ".join(codes)}')
            for v, codes in sorted(role.items()):
                self.stdout.write(f'  구분 불일치: {v} → {", ".join(codes)}({ROLE[matcher][1]} 아님)')
            plan.append((model, fk, todo))
        if not apply:
            self.stdout.write('미리보기입니다. 아무것도 바꾸지 않았습니다. 연결하려면 --apply --backup-dir 폴더 를 붙이세요.')
            return
        total = 0
        # save()/clean()을 거치지 않으므로 승인 잠금·출하 인터록에 막히지 않는다. 바뀌는 칸은 빈 외래키뿐이고 이력은 남는다.
        with transaction.atomic():
            for model, fk, todo in plan:
                if todo:
                    bulk_update_with_history(todo, model, [fk], default_change_reason=REASON)
                    total += len(todo)
        self.stdout.write(self.style.SUCCESS(f'연결함 {total}건'))
