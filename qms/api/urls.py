from django.urls import path

from . import views

urlpatterns = [
    path('overview/', views.OverviewView.as_view()),
    path('todo/', views.TodoView.as_view()),
    path('dashboard/', views.DashboardSaveView.as_view()),
]
