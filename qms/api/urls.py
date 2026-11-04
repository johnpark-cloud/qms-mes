from django.urls import path

from . import inspections, specs, views

urlpatterns = [
    path('overview/', views.OverviewView.as_view()),
    path('customer-rules/', views.CustomerRuleTableView.as_view()),
    path('todo/', views.TodoView.as_view()),
    path('dashboard/', views.DashboardSaveView.as_view()),
    path('specs/', specs.SpecListView.as_view()),
    path('specs/<int:pk>/', specs.SpecDetailView.as_view()),
    path('specs/<int:pk>/new-revision/', specs.SpecNewRevisionView.as_view()),
    path('specs/<int:pk>/approve/', specs.SpecApproveView.as_view()),
    path('specs/<int:pk>/revision-log/', specs.SpecRevisionLogView.as_view()),
    path('specs/<int:pk>/document/', specs.SpecDocumentView.as_view()),
    path('inspections/', inspections.InspectionListView.as_view()),
    path('inspections/<int:pk>/', inspections.InspectionDetailView.as_view()),
    path('inspections/<int:pk>/document/', inspections.InspectionDocumentView.as_view()),
    path('inspect/queue/', inspections.QueueView.as_view()),
    path('inspect/lot/', inspections.LotLookupView.as_view()),
    path('inspect/receive/', inspections.ReceiveView.as_view()),
    path('inspect/form/<int:lot_id>/<int:spec_id>/', inspections.FormView.as_view()),
    path('inspect/check/', inspections.CheckView.as_view()),
    path('inspect/submit/', inspections.SubmitView.as_view()),
]
