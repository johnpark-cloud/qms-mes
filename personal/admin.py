from django.contrib import admin
from django.http import Http404

from .models import LeaveProfile, LeaveUse, PayLine, Payslip


class OwnerAdmin(admin.ModelAdmin):
    """본인 기록만 보인다 (슈퍼유저 포함). 이력(simple_history)은 쓰지 않아 다른 경로로 새지 않는다.
    삭제는 소유자가 직접 한다: 품질 증적이 아니라 개인 자료라 삭제 요청·승인 흐름을 타지 않는다."""
    exclude = ('owner',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(owner=request.user)

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is None:  # 기본은 목록으로 되돌리는 302라 존재 여부가 드러난다
            raise Http404
        return obj

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        super().save_model(request, obj, form, change)


class PayLineInline(admin.TabularInline):
    model = PayLine
    extra = 1

    def get_queryset(self, request):
        return super().get_queryset(request).filter(payslip__owner=request.user)


@admin.register(LeaveProfile)
class LeaveProfileAdmin(OwnerAdmin):
    list_display = ['hired_on']

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not self.get_queryset(request).exists()


@admin.register(LeaveUse)
class LeaveUseAdmin(OwnerAdmin):
    list_display = ['used_on', 'days', 'reason']


@admin.register(Payslip)
class PayslipAdmin(OwnerAdmin):
    list_display = ['month', 'base_pay']
    inlines = [PayLineInline]
