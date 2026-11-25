"""조직도·사용자(W5): 옛 관리 화면(사용자)을 대신한다.

시스템 관리자만 열고 바꾼다(서버에서 검사). 역할·관리자 권한·비밀번호를 바꾸면 관리자 비밀번호를 다시 받는다.
사용자는 지우지 않고 비활성으로 둔다(기록의 작성자·승인자 이력 보존). 계정 변경은 LogEntry, 인사 정보는 simple-history에 남는다.
"""
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Department, Member

ROLE_GROUPS = ('품질팀장', '품질엔지니어', '검사원')  # qms/apps.py ensure_roles
MEMBER_FIELDS = ('employee_no', 'position', 'title', 'phone')


def _name(u):
    return f'{u.last_name}{u.first_name}' or u.username


def _user_row(u):
    m = getattr(u, 'member', None)
    return {'id': u.pk, 'username': u.username, 'name': _name(u), 'last_name': u.last_name, 'first_name': u.first_name,
            'email': u.email, 'active': u.is_active, 'admin': u.is_superuser,
            'groups': sorted(g.name for g in u.groups.all()), 'last_login': u.last_login,
            'dept': m.department_id if m else None, **{f: getattr(m, f) if m else '' for f in MEMBER_FIELDS}}


def _log(by, user, flag, text):
    LogEntry.objects.log_actions(by.pk, [user], flag, text, single_object=True)


def _dept(pk):
    return None if pk in (None, '') else get_object_or_404(Department, pk=pk)


class OrgView(APIView):
    schema = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_superuser:
            raise PermissionDenied('시스템 관리자만 사용자·조직도를 관리할 수 있습니다.')

    def get(self, request):
        data = {
            'depts': [{'id': d.pk, 'code': d.code, 'name': d.name, 'parent': d.parent_id, 'active': d.active, 'sort': d.sort,
                       'manager': _name(d.manager) if d.manager else '', 'manager_id': d.manager_id}
                      for d in Department.objects.select_related('manager')],
            'users': [_user_row(u) for u in User.objects.select_related('member').prefetch_related('groups').order_by('username')],
            'groups': [g for g in ROLE_GROUPS if Group.objects.filter(name=g).exists()],
            'me': request.user.pk,
        }
        if uid := request.query_params.get('user'):  # 계정 변경 기록(생성·역할·권한·비밀번호·비활성)
            data['log'] = [{'at': e.action_time, 'by': _name(e.user), 'text': e.get_change_message()}
                           for e in LogEntry.objects.filter(content_type__app_label='auth', content_type__model='user',
                                                            object_id=str(uid)).select_related('user')[:50]]
        return Response(data)

    def post(self, request):
        d, action = request.data, request.data.get('action')
        with transaction.atomic():
            if action == 'move_user':
                user = get_object_or_404(User, pk=d.get('id'))
                m = Member.objects.filter(user=user).first() or Member(user=user)
                m.department = _dept(d.get('dept'))
                m.save()
            elif action == 'move_dept':
                dept = get_object_or_404(Department, pk=d.get('id'))
                dept.parent = _dept(d.get('parent'))
                dept.full_clean()  # 순환 검사(Department.clean)
                dept.save()
            elif action == 'save_dept':  # 조직도 오른쪽 창(P4)
                dept = Department() if not d.get('id') else get_object_or_404(Department, pk=d['id'])
                dept.code, dept.name = str(d.get('code') or '').strip(), str(d.get('name') or '').strip()
                dept.parent = _dept(d.get('parent'))
                dept.manager = None if d.get('manager') in (None, '') else get_object_or_404(User, pk=d['manager'])
                dept.sort, dept.active = int(d.get('sort') or 0), d.get('active') is not False
                dept.full_clean()  # 코드 중복·순환 검사(Department.clean)
                dept.save()
                return Response({'ok': True, 'id': dept.pk})
            elif action == 'save_user':
                self._save_user(request, d)
            elif action == 'reset_password':
                user = get_object_or_404(User, pk=d.get('id'))
                self._reauth(request, d)
                self._check_password(d.get('password'), user)
                user.set_password(d['password'])
                user.save()
                _log(request.user, user, CHANGE, '비밀번호 초기화')
            else:
                raise ValidationError('알 수 없는 요청입니다.')
        return Response({'ok': True})

    @staticmethod
    def _reauth(request, d):
        if not request.user.check_password(str(d.get('admin_password') or '')):
            raise ValidationError({'admin_password': '관리자 비밀번호가 맞지 않습니다.'})

    @staticmethod
    def _check_password(pw, user):
        if not pw:
            raise ValidationError({'password': '비밀번호를 입력하세요.'})
        try:
            validate_password(pw, user)
        except ValidationError as e:
            raise ValidationError({'password': e.messages})

    def _save_user(self, request, d):
        new = not d.get('id')
        user = User(is_staff=True) if new else get_object_or_404(User, pk=d['id'])
        groups = [g for g in d.get('groups') or [] if g in ROLE_GROUPS]
        old_groups = set() if new else set(user.groups.values_list('name', flat=True))
        admin, active = d.get('admin') is True, d.get('active') is not False
        if user == request.user and not (admin and active):
            raise ValidationError('자기 계정은 비활성으로 바꾸거나 관리자 권한을 뗄 수 없습니다.')
        # 권한(역할·관리자)이나 비밀번호가 바뀌면 관리자 비밀번호를 다시 받는다
        if new or set(groups) != old_groups or admin != user.is_superuser:
            self._reauth(request, d)
        changes = []
        if not new:
            changes += [t for t, on in (('관리자 권한 부여', admin and not user.is_superuser),
                                        ('관리자 권한 해제', user.is_superuser and not admin),
                                        ('비활성', user.is_active and not active), ('다시 활성', active and not user.is_active)) if on]
            if set(groups) != old_groups:
                changes.append('역할: ' + (', '.join(sorted(groups)) or '없음'))
        user.username = str(d.get('username') or '').strip()
        user.last_name, user.first_name = str(d.get('last_name') or ''), str(d.get('first_name') or '')
        user.email = str(d.get('email') or '').strip()
        user.is_superuser, user.is_active = admin, active
        user.is_staff = user.is_staff or new
        if new:
            self._check_password(d.get('password'), user)
            user.set_password(d['password'])
        user.full_clean(exclude=['password'])  # 아이디 형식·중복, 메일 형식
        user.save()
        user.groups.set(Group.objects.filter(name__in=groups))
        m = Member.objects.filter(user=user).first() or Member(user=user)
        m.department = _dept(d.get('dept'))
        for f in MEMBER_FIELDS:
            setattr(m, f, str(d.get(f) or ''))
        m.full_clean()
        m.save()
        if new:
            _log(request.user, user, ADDITION, '계정 생성 (역할: ' + (', '.join(groups) or '없음') + (', 관리자' if admin else '') + ')')
        elif changes:
            _log(request.user, user, CHANGE, ', '.join(changes))
