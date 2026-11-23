"""옛 서버 화면을 대신하는 API(W2-2): 모듈 설정, 승인된 부적합 메일."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.loader import render_to_string
from rest_framework.response import Response
from rest_framework.views import APIView

from core import views as old
from core.models import ModuleSwitch
from core.modules import MODULES, active_set
from core.relations import record_url

from .permissions import require_perm


class ModuleSettingsView(APIView):
    """모듈 켜기/끄기: 시스템 관리자만(core/admin.py ModuleSwitchAdmin과 같은 규칙). 규칙 검사는 ModuleSwitch.clean."""
    schema = None

    def _rows(self):
        on, saved = active_set(), {m.key: m for m in ModuleSwitch.objects.select_related('changed_by')}
        return {'rows': [{'key': k, 'name': m.name, 'enabled': k in on, 'requires': [MODULES[r].name for r in m.requires],
                          'changed_by': str(saved[k].changed_by or '') if k in saved else '',
                          'changed_at': saved[k].changed_at if k in saved else None} for k, m in MODULES.items()]}

    def check(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied('시스템 관리자만 모듈을 켜고 끌 수 있습니다.')

    def get(self, request):
        self.check(request)
        return Response(self._rows())

    def post(self, request):
        self.check(request)
        key = str(request.data.get('key', ''))
        row = ModuleSwitch.objects.filter(key=key).first() or ModuleSwitch(key=key)
        row.enabled, row.changed_by = request.data.get('enabled') is True, request.user
        row.save()  # full_clean: 기본 플랫폼·먼저 켤 모듈·쓰는 모듈·열린 기록
        return Response(self._rows())


class NcMailView(APIView):
    """승인된 부적합 보고 메일(옛 /nc/<번호>/mail/과 같은 규칙): 본문 복사가 기본, SMTP가 있으면 바로 보내기."""
    schema = None

    def _payload(self, nc, request):
        title, header, rows = nc.print_table()
        subject = f'[부적합 보고] {nc.number} {nc.lot}'
        body = render_to_string('core/_nc_mail_body.html', {'subject': subject, 'table_header': header, 'table': rows})
        return {'number': nc.number, 'subject': subject, 'body': body, 'smtp': settings.SMTP_ENABLED,
                'can_send': request.user.has_perm('core.change_nonconformance') and settings.SMTP_ENABLED,
                'can_mark': request.user.has_perm('core.change_nonconformance'),
                'mailed_at': nc.mailed_at, 'photos': [str(p) for p in nc.photos.all()],
                'photos_zip': f'/nc/{nc.pk}/photos.zip', 'nc_url': record_url(nc)}

    def get(self, request, pk):
        require_perm(request.user, 'core.view_nonconformance')
        nc = old._approved_nc(pk)
        return Response(self._payload(nc, request))

    def post(self, request, pk):
        require_perm(request.user, 'core.view_nonconformance')
        require_perm(request.user, 'core.change_nonconformance')
        nc = old._approved_nc(pk)
        action = request.data.get('action')
        if action == 'send':
            if not settings.SMTP_ENABLED:
                raise ValidationError('메일 서버가 설정되지 않았습니다. 본문을 복사해 보내고 「보냈음 표시」를 누르세요.')
            p = self._payload(nc, request)
            old.send_nc_mail(nc, p['subject'], p['body'], str(request.data.get('to', '')))
        elif action == 'mark_sent':
            old._mark_mailed(nc)
        else:
            raise ValidationError('알 수 없는 동작입니다.')
        nc.refresh_from_db()
        return Response(self._payload(nc, request))
