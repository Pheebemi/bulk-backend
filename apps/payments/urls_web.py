from django.urls import path

from . import views_web

urlpatterns = [
    path('wallet/', views_web.wallet_view, name='web-wallet'),
    path('wallet/verify/', views_web.wallet_verify, name='web-wallet-verify'),
]
