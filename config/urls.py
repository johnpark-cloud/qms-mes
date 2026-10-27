from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from core import views as core_views
from personal import views as personal_views
from qms import views as qms_views

urlpatterns = [
    path('', RedirectView.as_view(url='/todo/')),
    path('admin/', admin.site.urls),
    path('me/', personal_views.me, name='me'),
    path('me/payslip/<int:pk>/file/', personal_views.payslip_file, name='payslip_file'),
    path('todo/', qms_views.todo, name='todo'),
    path('brand/logo', core_views.brand_logo, name='brand_logo'),
    path('search/', core_views.search, name='search'),
    path('trace/', core_views.trace, name='trace'),
    path('nc/new/', core_views.nc_quick, name='nc_quick'),
    path('nc/<int:pk>/mail/', core_views.nc_mail, name='nc_mail'),
    path('nc/<int:pk>/photos.zip', core_views.nc_photos_zip, name='nc_photos_zip'),
    path('import/', core_views.import_view, name='import'),
    path('approve/<str:app_label>/<str:model_name>/<int:pk>/', core_views.approve, name='approve'),
    path('request/<str:kind>/<str:app_label>/<str:model_name>/<int:pk>/', core_views.edit_request, name='edit_request'),
    path('request/<int:pk>/decide/', core_views.edit_request_decide, name='edit_request_decide'),
    path('print/<str:app_label>/<str:model_name>/<int:pk>/', core_views.print_view, name='print'),
    path('report/<int:template_id>/<int:pk>/', qms_views.excel_report, name='excel_report'),
    path('spc/<int:char_id>/', qms_views.spc_view, name='spc'),
    path('kpi/', qms_views.kpi_view, name='kpi'),
    path('suppliers/', qms_views.suppliers_view, name='suppliers'),
    path('audit-pack/', qms_views.audit_pack, name='audit_pack'),
    path('audit-pack/zip/', qms_views.audit_pack_zip, name='audit_pack_zip'),
    path('memo/new/', qms_views.memo_new, name='memo_new'),
    path('memo/<int:pk>/edit/', qms_views.memo_edit, name='memo_edit'),
    path('memo/inbox/', qms_views.memo_inbox, name='memo_inbox'),
    path('inspect/', qms_views.inspect_home, name='inspect'),
    path('inspect/lot/', qms_views.inspect_lot, name='inspect_lot'),
    path('inspect/<int:lot_id>/<int:spec_id>/', qms_views.inspect_form, name='inspect_form'),
    path('inspect/<int:lot_id>/<int:spec_id>/submit/', qms_views.inspect_submit, name='inspect_submit'),
    path('inspect/check/<int:char_id>/', qms_views.inspect_check, name='inspect_check'),
    # 문서 원본은 로그인한 사용자에게만 (DEBUG=0 사내망 서비스에서도 동작)
    # 급여 파일은 소유자 전용 화면(payslip_file)으로만 받는다
    re_path(r'^media/(?P<path>(?!personal/).*)$', staff_member_required(serve), {'document_root': settings.MEDIA_ROOT}),
]
