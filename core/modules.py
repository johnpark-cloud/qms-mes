"""모듈 대응표: 어느 모델·주소가 어느 모듈에 속하는지 정하는 유일한 곳. 시스템 관리자가 모듈을 끄면 그 화면·API가 닫힌다.

BASE(홈·LOT·부적합·보류·기준정보·시스템·개인)는 끌 수 없다. 업무 규칙(인터록)은 모듈 설정과 무관하게 모델에서 동작한다.
qms 모델을 import하지 않는다('app.model' 라벨만). 새 모델·새 주소는 여기에 등록해야 core/tests_modules.py 전수 테스트가 통과한다.
"""
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.http import Http404

BASE = 'base'
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


class Module(NamedTuple):
    name: str
    models: tuple
    paths: tuple = ()  # 주소 접두('/' 없이 시작). 관리 화면 주소는 모델로 판정한다
    requires: tuple = ()  # 켜려면 먼저 켜져 있어야 하는 모듈


MODULES = {
    'mes': Module('생산관리 (작업지시·실적·출하)', ('core.workorder', 'core.workresult', 'core.shipment')),
    'qms_inspection': Module(
        '검사 (검사기준·관리계획서·검사·계측기·검사원 자격)',
        ('qms.inspectionspec', 'qms.characteristic', 'qms.inspection', 'qms.measurement', 'qms.gauge',
         'qms.qualification', 'qms.controlplan', 'qms.controlplanline'),
        ('inspect/', 'spc/', 'api/qms/specs/', 'api/qms/plans/', 'api/qms/inspections/', 'api/qms/inspect/')),
    # 4M 초품 해제는 검사 판정으로만 된다
    'qms_change': Module('4M 변경', ('qms.changerequest',), requires=('qms_inspection',)),
    'qms_capa': Module('CAPA (시정조치)', ('qms.capa',)),
    'qms_claim': Module('고객 클레임 (8D)', ('qms.customerclaim', 'qms.customerrule'), ('api/qms/customer-rules/',)),
    'qms_supplier': Module('협력사 시정요구(SCAR)·평가', ('qms.scar',), ('suppliers/',)),
    'qms_ppap': Module('PPAP', ('qms.ppapsubmission', 'qms.ppapelement')),
    # 심사 지적이 CAPA를 외래키로 가리킨다
    'qms_audit': Module('내부심사', ('qms.internalaudit', 'qms.auditfinding', 'qms.auditchecklist', 'qms.audititem', 'qms.evidence'),
                        ('audit-pack/',), requires=('qms_capa',)),
    'qms_document': Module('문서 관리', ('qms.document', 'qms.documentrevision')),
    'qms_kpi': Module('품질 KPI', (), ('kpi/',)),
}

BASE_MODELS = (
    'core.item', 'core.codevalue', 'core.numberrule', 'core.process', 'core.bomline', 'core.routingstep',
    'core.importprofile', 'core.lot', 'core.lotlink', 'core.nonconformance', 'core.nonconformancephoto', 'core.hold',
    'core.editrequest', 'core.revisionlog', 'core.department', 'core.partner', 'core.partnercertificate',
    'core.fielddef', 'core.attachment', 'core.moduleswitch',
    'qms.exceltemplate', 'qms.memo', 'qms.memophoto', 'qms.dashboardlayout',
)
BASE_APPS = ('auth', 'personal')  # 사용자·권한, 개인 연차·급여
# 관리 화면 밖의 기본 플랫폼 주소. 라벨을 인자로 받는 approve/·request/·print/·relations/는 미들웨어가 인자로 다시 판정한다.
BASE_PATHS = (
    'app/', 'me/', 'todo/', 'overview/', 'dashboard/', 'brand/', 'search/', 'trace/', 'nc/', 'attachments/', 'import/',
    'approve/', 'request/', 'print/', 'memo/', 'media/',
    # shortcut: 엑셀 보고서·첨부 원본은 대상 기록의 모듈을 아직 보지 않는다. A4(MOD-12)에서 막는다.
    'report/',
    'api/auth/', 'api/search/', 'api/items/', 'api/core/lots/', 'api/core/trace/', 'api/core/items/',
    'api/core/numbering/', 'api/core/processes/', 'api/core/import/', 'api/attachments/', 'api/relations/',
    'api/revision-log/', 'api/audit-log/', 'api/schema/',
    'api/qms/overview/', 'api/qms/todo/', 'api/qms/dashboard/', 'api/qms/memos/',
)

# 꺼진 모듈에서도 시스템 관리자가 열린 기록을 닫을 수 있는 쓰기 주소(MOD-07). 관리 화면은 변경 폼만, 추가·삭제는 열지 않는다.
# 4M 초품은 검사 판정으로만 풀리므로 검사 입력을 연다(미결 #3: 수동 해제 규칙은 만들지 않는다).
CLOSING = {
    'qms_capa': ('admin/qms/capa/',),
    'qms_claim': ('admin/qms/customerclaim/',),
    'qms_supplier': ('admin/qms/scar/',),
    'qms_audit': ('admin/qms/internalaudit/', 'admin/qms/auditfinding/'),
    'qms_inspection': ('inspect/', 'api/qms/inspect/'),
}

_MODEL = {label: BASE for label in BASE_MODELS} | {label: key for key, m in MODULES.items() for label in m.models}


def choices():
    return [(key, m.name) for key, m in MODULES.items()]


def module_of_model(label):
    """'app.model' → 모듈 키 또는 BASE. 대응표에 없으면 None(전수 테스트가 잡는다)."""
    label = label.lower()
    if label.split('.')[0] in BASE_APPS:
        return BASE
    return _MODEL.get(label)


def module_of_path(path):
    """주소('/' 없이 시작, 쿼리 없이) → 모듈 키 또는 BASE. 대응표에 없으면 None."""
    if path == '':
        return BASE
    if path.startswith('admin/'):
        parts = path.split('/')
        # admin/<app>/<model>/… 만 모델 화면이다. admin/, admin/<app>/(묶음 목록), 로그인·자동완성 등은 기본 플랫폼
        if len(parts) > 3 and parts[1] in ('core', 'qms', *BASE_APPS) and parts[2] and not parts[2].startswith(('<', '(')):
            return module_of_model(f'{parts[1]}.{parts[2]}')
        return BASE
    for key, m in MODULES.items():
        if path.startswith(m.paths or '\0'):
            return key
    return BASE if path.startswith(BASE_PATHS) else None


def module_of_request(request, view_kwargs):
    """요청이 속한 모듈. 라벨을 인자로 받는 경로는 그 라벨로, 관리 자동완성은 GET 인자로 판정한다."""
    if 'app_label' in view_kwargs and 'model_name' in view_kwargs:
        return module_of_model(f"{view_kwargs['app_label']}.{view_kwargs['model_name']}") or BASE
    if 'label' in view_kwargs:
        return module_of_model(str(view_kwargs['label'])) or BASE
    path = request.path_info.lstrip('/')
    if path.startswith('admin/autocomplete/'):
        return module_of_model(f"{request.GET.get('app_label', '')}.{request.GET.get('model_name', '')}") or BASE
    return module_of_path(path) or BASE  # 등록되지 않은 주소는 전수 테스트가 잡는다


def closing_allowed(key, path):
    return any(path.startswith(p) and (not p.startswith('admin/') or path.endswith('/change/')) for p in CLOSING.get(key, ()))


def open_records(key):
    """끄면 닫을 길이 사라지는 열린 기록(MOD-06). 이 목록이 비어야 끌 수 있다."""
    from django.apps import apps
    model = lambda label: apps.get_model(*label.split('.'))
    if key == 'mes':
        wo = model('core.workorder')
        return list(wo.objects.exclude(status=wo.DONE))
    if key == 'qms_inspection':
        return [f'{i.lot.number} 미판정 검사' for i in model('qms.inspection').objects.filter(result='').select_related('lot')]
    if key == 'qms_change':  # 승인됐는데 초품 합격이 아직 없는 4M (적용 일시 전 것도 곧 출하를 막는다)
        return [c for c in model('qms.changerequest').objects.filter(approved_at__isnull=False) if not c.first_article]
    found = {'qms_capa': ('qms.capa', 'closed_at'), 'qms_claim': ('qms.customerclaim', 'closed_at'),
             'qms_supplier': ('qms.scar', 'closed_at'), 'qms_audit': ('qms.internalaudit', 'closed_at'),
             'qms_ppap': ('qms.ppapsubmission', 'approved_at')}.get(key)
    if not found:
        return []
    return list(model(found[0]).objects.filter(**{f'{found[1]}__isnull': True}))


def active_set():
    """켜진 모듈 키 + BASE. 행이 없으면 켜짐. 캐시하지 않는다(요청마다 한 쿼리)."""
    from core.models import ModuleSwitch
    off = set(ModuleSwitch.objects.filter(enabled=False).values_list('key', flat=True))
    return {BASE} | (set(MODULES) - off)


def active(key):
    return key == BASE or key in active_set()


def blocked(request, key, active_keys=None):
    """꺼진 모듈이면 404(일반 사용자) 또는 403(시스템 관리자의 종결 외 쓰기). 열려 있으면 None."""
    if key == BASE or key in (active_keys if active_keys is not None else active_set()):
        return None
    if not request.user.is_superuser:
        return 404
    if request.method in SAFE_METHODS or closing_allowed(key, request.path_info.lstrip('/')):
        return None
    return 403


def check_label(request, label):
    """쿼리 인자로 기록 종류를 받는 뷰(첨부·메모)가 부른다. 미들웨어는 쿼리 인자를 보지 않는다."""
    code = blocked(request, module_of_model(label) or BASE)
    if code == 404:
        raise Http404('비활성 모듈입니다.')
    if code == 403:
        raise PermissionDenied('비활성 모듈은 조회만 할 수 있습니다.')
