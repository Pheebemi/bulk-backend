"""Server-rendered wallet page: Flutterwave inline checkout in the
browser, then an authenticated POST back here which re-verifies the
transaction server-side (via the existing PaymentVerifyView) before
anything is credited."""

import json
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.models import WalletTransaction
from apps.accounts.web_utils import call_api, customer_required, error_text

from .views import PaymentVerifyView


@customer_required
def wallet_view(request):
    page = Paginator(WalletTransaction.objects.filter(user=request.user), 20).get_page(request.GET.get('page'))
    return render(request, 'payments/wallet.html', {
        'page': page,
        'fw_config': ({
            'public_key': settings.FLUTTERWAVE_PUBLIC_KEY,
            'tx_ref': f'reachly_{request.user.pk}_{int(time.time() * 1000)}',
            'email': request.user.email,
            'phone': request.user.phone_number or '',
            'name': request.user.full_name or request.user.email,
        }),
    })


@customer_required
@require_POST
def wallet_verify(request):
    body = json.loads(request.body or '{}')
    status, data = call_api(PaymentVerifyView, request.user, 'post', {
        'transaction_id': body.get('transaction_id'), 'tx_ref': body.get('tx_ref'),
    })
    if status < 300:
        return JsonResponse({'ok': True, 'balance': data['balance']})
    return JsonResponse({'ok': False, 'error': error_text(data)}, status=status)
