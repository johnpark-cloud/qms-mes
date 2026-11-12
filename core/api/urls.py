from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from . import attachments, master, views
from .permissions import IsStaff

urlpatterns = [
    path('auth/csrf/', views.CsrfView.as_view()),
    path('auth/login/', views.LoginView.as_view()),
    path('auth/logout/', views.LogoutView.as_view()),
    path('auth/me/', views.MeView.as_view()),
    path('search/', views.SearchView.as_view()),
    path('items/', views.ItemLookupView.as_view()),
    path('core/lots/', views.LotSearchView.as_view()),
    path('core/trace/', views.TraceView.as_view()),
    path('core/items/', master.ItemListView.as_view()),
    path('core/items/<int:pk>/', master.ItemDetailView.as_view()),
    path('core/numbering/item-options/', master.ItemOptionsView.as_view(), name='numbering-item-options'),
    path('core/numbering/item-preview/', master.ItemPreviewView.as_view(), name='numbering-item-preview'),
    path('core/processes/', master.ProcessTableView.as_view()),
    path('core/import/profiles/', master.ImportProfileListView.as_view()),
    path('core/import/', master.ImportView.as_view()),
    path('attachments/', attachments.AttachmentListView.as_view()),
    path('relations/<str:label>/<int:pk>/', views.RelationsView.as_view(), name='relations'),
    path('revision-log/<int:pk>/approve/',views.RevisionLogApproveView.as_view()),
    path('audit-log/', views.AuditLogView.as_view()),
    path('qms/', include('qms.api.urls')),
    path('schema/', SpectacularAPIView.as_view(permission_classes=[IsStaff]), name='api_schema'),
]
