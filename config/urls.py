from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from core import views as core_views
from qms import views as qms_views

urlpatterns = [
    path('', RedirectView.as_view(url='/todo/')),
    path('admin/', admin.site.urls),
    path('todo/', qms_views.todo, name='todo'),
    path('trace/', core_views.trace, name='trace'),
    path('import/', core_views.import_view, name='import'),
    path('approve/<str:app_label>/<str:model_name>/<int:pk>/', core_views.approve, name='approve'),
    path('print/<str:app_label>/<str:model_name>/<int:pk>/', core_views.print_view, name='print'),
    path('report/<int:template_id>/<int:pk>/', qms_views.excel_report, name='excel_report'),
    path('spc/<int:char_id>/', qms_views.spc_view, name='spc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)  # DEBUG일 때만 동작
