from decimal import Decimal

from django.conf import settings
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.flutterwave import FlutterwaveError, flutterwave

from .models import PaymentTransaction


def _credit_wallet_if_new(user, tx_ref: str, transaction_id: str, amount: Decimal) -> PaymentTransaction:
    """Idempotent: if this tx_ref was already recorded, don't credit twice —
    both the client-verify call and the webhook can land on the same tx_ref."""
    existing = PaymentTransaction.objects.filter(tx_ref=tx_ref).first()
    if existing:
        return existing

    record = PaymentTransaction.objects.create(
        user=user, tx_ref=tx_ref, flutterwave_transaction_id=transaction_id, amount=amount, status='successful'
    )
    with transaction.atomic():
        wallet = user.wallet
        wallet.balance += amount
        wallet.save(update_fields=['balance'])
    return record


class PaymentVerifyView(APIView):
    """Called by the frontend right after Flutterwave's inline checkout
    reports success — we independently verify with Flutterwave before
    trusting it, rather than crediting on the client's say-so."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        transaction_id = request.data.get('transaction_id')
        expected_tx_ref = request.data.get('tx_ref')
        if not transaction_id or not expected_tx_ref:
            return Response({'detail': 'transaction_id and tx_ref are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = flutterwave.verify_transaction(transaction_id)
        except FlutterwaveError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        data = result.get('data', {})
        if (
            result.get('status') != 'success'
            or data.get('status') != 'successful'
            or data.get('tx_ref') != expected_tx_ref
            or data.get('currency') != 'NGN'
        ):
            return Response({'detail': 'Transaction could not be verified as successful.'}, status=status.HTTP_400_BAD_REQUEST)

        record = _credit_wallet_if_new(request.user, data['tx_ref'], str(data['id']), Decimal(str(data['amount'])))
        return Response({'balance': str(request.user.wallet.balance), 'tx_ref': record.tx_ref})


class FlutterwaveWebhookView(APIView):
    """Server-to-server backup path — authoritative even if the client
    never calls PaymentVerifyView (closed tab, network drop, etc.)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get('verif-hash')
        if not signature or signature != settings.FLUTTERWAVE_WEBHOOK_HASH:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data
        data = payload.get('data', {})
        if payload.get('event') != 'charge.completed' or data.get('status') != 'successful':
            return Response(status=status.HTTP_200_OK)  # ack, nothing to do

        transaction_id = str(data.get('id'))
        try:
            verified = flutterwave.verify_transaction(transaction_id)
        except FlutterwaveError:
            return Response(status=status.HTTP_502_BAD_GATEWAY)

        vdata = verified.get('data', {})
        if verified.get('status') != 'success' or vdata.get('status') != 'successful' or vdata.get('currency') != 'NGN':
            return Response(status=status.HTTP_200_OK)

        customer_email = vdata.get('customer', {}).get('email')
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(email=customer_email).first()
        if not user:
            return Response(status=status.HTTP_200_OK)

        _credit_wallet_if_new(user, vdata['tx_ref'], transaction_id, Decimal(str(vdata['amount'])))
        return Response(status=status.HTTP_200_OK)
