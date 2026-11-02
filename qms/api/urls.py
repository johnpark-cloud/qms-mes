from django.urls import path

from . import views

urlpatterns = [
    path('overview/', views.OverviewView.as_view()),
]
