from django.apps import AppConfig
from django.db.models.signals import post_migrate

TEAM_LEAD_ONLY = ['department', 'partner', 'fielddef']  # core 모델 이름


def ensure_roles(sender, **kwargs):
    """역할 그룹과 권한을 만든다. 품질팀장 그룹 = 승인자(core.models.APPROVER_GROUP)."""
    from django.contrib.auth.models import Group, Permission

    apps_ = ['core', 'qms']
    engineer = Permission.objects.filter(content_type__app_label__in=apps_).exclude(codename__startswith='delete_')
    inspector = Permission.objects.filter(content_type__app_label__in=apps_, codename__in=[
        'view_item', 'view_process', 'view_workorder', 'view_inspectionspec', 'view_characteristic',
        'view_lot', 'add_lot', 'add_lotlink', 'view_lotlink', 'add_shipment', 'view_shipment',
        'view_inspection', 'add_inspection', 'change_inspection',
        'view_measurement', 'add_measurement', 'change_measurement', 'delete_measurement', 'view_gauge',
        'add_nonconformance', 'view_nonconformance', 'add_nonconformancephoto', 'view_routingstep', 'view_workresult', 'add_workresult',
        'add_memo', 'view_memo', 'add_memophoto', 'view_memophoto', 'view_attachment', 'add_attachment'])
    mine = Permission.objects.filter(content_type__app_label='personal')  # 본인 것만 보이게 admin이 거른다
    # 부서·거래처·사용자 정의 칸 추가·수정은 품질팀장(과 시스템 관리자)만
    masters = [f'{a}_{m}' for m in TEAM_LEAD_ONLY for a in ('add', 'change')]
    eng_only = engineer.exclude(content_type__app_label='core', codename__in=masters)
    for name, perms in (('품질엔지니어', eng_only), ('품질팀장', engineer), ('검사원', inspector)):
        Group.objects.get_or_create(name=name)[0].permissions.set(list(perms) + list(mine))


class QmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'qms'
    verbose_name = 'QMS'

    def ready(self):
        # 모든 앱 뒤에도 돌아야 personal 권한(qms보다 늦게 생성)이 첫 migrate에서 들어간다
        post_migrate.connect(ensure_roles, dispatch_uid='qms.ensure_roles')
