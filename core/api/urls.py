from django.urls import path
from drf_spectacular.views import SpectacularAPIView

from . import views
from .permissions import IsStaff

urlpatterns = [
    path('auth/csrf/', views.CsrfView.as_view()),
    path('auth/login/', views.LoginView.as_view()),
    path('auth/logout/', views.LogoutView.as_view()),
    path('auth/me/', views.MeView.as_view()),
    path('schema/', SpectacularAPIView.as_view(permission_classes=[IsStaff]), name='api_schema'),
]
