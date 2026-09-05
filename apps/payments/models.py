from django.conf import settings
from django.db import models


class PaymentTransaction(models.Model):
    """One row per Flutterwave transaction we've credited — tx_ref is
    unique so both the client-verify call and the webhook can hit this
    idempotently without double-crediting a wallet."""

    STATUS_CHOICES = (('successful', 'Successful'), ('failed', 'Failed'))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_transactions')
    tx_ref = models.CharField(max_length=100, unique=True)
    flutterwave_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.tx_ref} — {self.status}'
