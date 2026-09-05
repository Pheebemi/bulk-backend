from django.urls import path

from .views import FlutterwaveWebhookView, PaymentVerifyView

urlpatterns = [
    path('wallet/verify/', PaymentVerifyView.as_view(), name='wallet-verify'),
    path('webhooks/flutterwave/', FlutterwaveWebhookView.as_view(), name='flutterwave-webhook'),
]
