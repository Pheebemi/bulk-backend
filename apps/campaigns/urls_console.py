from django.urls import path

from . import views_console as v

urlpatterns = [
    path('console/login/', v.login_view, name='console-login'),
    path('console/logout/', v.logout_view, name='console-logout'),
    path('console/dashboard/', v.dashboard, name='console-dashboard'),
    path('console/analytics/', v.analytics, name='console-analytics'),
    path('console/campaigns/', v.campaigns, name='console-campaigns'),
    path('console/wallets/', v.wallets, name='console-wallets'),
    path('console/send/', v.send, name='console-send'),
    path('console/approvals/', v.approvals, name='console-approvals'),
]
