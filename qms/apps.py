from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_roles(sender, **kwargs):
    """역할 그룹과 권한을 만든다. 품질팀장 그룹 = 승인자(core.models.APPROVER_GROUP)."""
    from django.contrib.auth.models import Group, Permission

    apps_ = ['core', 'qms']
    engineer = Permission.objects.filter(content_type__app_label__in=apps_).exclude(codename__startswith='delete_')
    inspector = Permission.objects.filter(content_type__app_label__in=apps_, codename__in=[
        'view_item', 'view_process', 'view_workorder', 'view_inspectionspec', 'view_characteristic',
        'view_lot', 'add_lot', 'add_lotlink', 'view_lotlink', 'add_shipment', 'view_shipment',
        'view_inspection', 'add_inspection', 'change_inspection',
        'view_measurement', 'add_measurement', 'change_measurement', 'delete_measurement', 'view_gauge'])
    for name, perms in (('품질엔지니어', engineer), ('품질팀장', engineer), ('검사원', inspector)):
        Group.objects.get_or_create(name=name)[0].permissions.set(perms)


class QmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'qms'
    verbose_name = 'QMS'

    def ready(self):
        post_migrate.connect(ensure_roles, sender=self)
