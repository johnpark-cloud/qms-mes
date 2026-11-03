from django.urls import path

from . import specs, views

urlpatterns = [
    path('overview/', views.OverviewView.as_view()),
    path('todo/', views.TodoView.as_view()),
    path('dashboard/', views.DashboardSaveView.as_view()),
    path('specs/', specs.SpecListView.as_view()),
    path('specs/<int:pk>/', specs.SpecDetailView.as_view()),
    path('specs/<int:pk>/new-revision/', specs.SpecNewRevisionView.as_view()),
    path('specs/<int:pk>/approve/', specs.SpecApproveView.as_view()),
    path('specs/<int:pk>/revision-log/', specs.SpecRevisionLogView.as_view()),
    path('specs/<int:pk>/document/', specs.SpecDocumentView.as_view()),
]
