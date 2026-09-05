from django.contrib import admin

from .models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['tx_ref', 'user', 'amount', 'status', 'created_at']
    search_fields = ['tx_ref', 'user__email', 'flutterwave_transaction_id']
