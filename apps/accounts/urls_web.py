from django.urls import path

from . import views_web

urlpatterns = [
    path('login/', views_web.login_view, name='web-login'),
    path('signup/', views_web.signup_view, name='web-signup'),
    path('dashboard/', views_web.dashboard_view, name='web-dashboard'),
    path('claim-bonus/', views_web.claim_bonus_view, name='web-claim-bonus'),
    path('logout/', views_web.logout_view, name='web-logout'),
]
