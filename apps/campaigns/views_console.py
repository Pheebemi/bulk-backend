"""Server-rendered admin console (/console/…) — the replacement for the
Next.js /admin/* screens. Mutations go through the existing DRF admin
views (call_api) so validation and side effects stay in one place."""

from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import EmailLoginForm
from apps.accounts.models import Wallet
from apps.accounts.web_utils import call_api, error_text, staff_required
from apps.contacts.models import ContactGroup

from .models import Campaign, PlatformRate, SenderID
from .views import (
    AdminCampaignListCreateView,
    AdminPlatformRateView,
    AdminSenderIDDetailView,
    AdminSenderIDListCreateView,
    AdminWalletAdjustView,
    _sync_sender_id_statuses,
)

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('console-dashboard')
    form = EmailLoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        user = form.cleaned_data['user']
        if not user.is_staff:
            form.add_error(None, 'This account is not an admin account.')
        else:
            auth_login(request, user)
            return redirect('console-dashboard')
    return render(request, 'console/login.html', {'form': form})


def logout_view(request):
    if request.method == 'POST':
        auth_logout(request)
    return redirect('console-login')


@staff_required
def dashboard(request):
    customers = User.objects.filter(is_staff=False)
    return render(request, 'console/dashboard.html', {
        'total_users': customers.count(),
        'total_balance': Wallet.objects.filter(user__is_staff=False).aggregate(t=Sum('balance'))['t'] or Decimal('0.00'),
        'admin_sms_sent': Campaign.objects.filter(is_admin_campaign=True).aggregate(t=Sum('total_recipients'))['t'] or 0,
        'pending': SenderID.objects.filter(platform_status='pending', visibility='private').select_related('user')[:10],
    })


@staff_required
def analytics(request):
    admin_agg = Campaign.objects.filter(is_admin_campaign=True).aggregate(spend=Sum('termii_cost'), recipients=Sum('total_recipients'))
    user_agg = Campaign.objects.filter(is_admin_campaign=False).aggregate(spend=Sum('total_cost'), recipients=Sum('total_recipients'))
    admin_spend = admin_agg['spend'] or Decimal('0.00')
    user_spend = user_agg['spend'] or Decimal('0.00')
    non_admin = Q(campaigns__is_admin_campaign=False)
    users = (
        User.objects.filter(is_staff=False)
        .annotate(
            total_spent=Coalesce(Sum('campaigns__total_cost', filter=non_admin), Value(Decimal('0.00'))),
            campaigns_count=Count('campaigns', filter=non_admin),
            recipients_total=Coalesce(Sum('campaigns__total_recipients', filter=non_admin), Value(0)),
        )
        .order_by('-total_spent', '-recipients_total', 'id')
    )
    return render(request, 'console/analytics.html', {
        'admin_spend': admin_spend, 'admin_recipients': admin_agg['recipients'] or 0,
        'user_spend': user_spend, 'user_recipients': user_agg['recipients'] or 0,
        'total_spend': admin_spend + user_spend,
        'total_recipients': (admin_agg['recipients'] or 0) + (user_agg['recipients'] or 0),
        'page': Paginator(users, 25).get_page(request.GET.get('page')),
    })


@staff_required
def campaigns(request):
    qs = Campaign.objects.select_related('user').order_by('-created_at')
    failed_only = request.GET.get('filter') == 'failed'
    if failed_only:
        qs = qs.filter(status__in=['FAILED', 'PARTIAL'])
    return render(request, 'console/campaigns.html', {
        'page': Paginator(qs, 25).get_page(request.GET.get('page')), 'failed_only': failed_only,
    })


@staff_required
def wallets(request):
    if request.method == 'POST':
        user_pk = request.POST.get('user_id')
        direction = request.POST.get('direction')
        status, data = call_api(AdminWalletAdjustView, request.user, 'post', {
            'amount': request.POST.get('amount') or '0', 'direction': direction, 'reason': request.POST.get('reason', ''),
        }, user_id=user_pk)
        if status < 300:
            messages.success(request, f'Wallet {"credited" if direction == "credit" else "debited"}. New balance: ₦{data["balance"]}')
        else:
            messages.error(request, error_text(data))
        return redirect(f"{request.path}?user={user_pk}")

    q = request.GET.get('q', '').strip()
    users = User.objects.filter(is_staff=False).select_related('wallet').order_by('full_name', 'email')
    if q:
        users = users.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    page = Paginator(users, 25).get_page(request.GET.get('page'))
    selected = None
    if request.GET.get('user'):
        selected = User.objects.filter(pk=request.GET['user'], is_staff=False).select_related('wallet').first()
    elif page.object_list:
        selected = page.object_list[0]
    history = selected.wallet_transactions.all()[:20] if selected else []
    return render(request, 'console/wallets.html', {'page': page, 'q': q, 'selected': selected, 'history': history})


@staff_required
def send(request):
    rate = PlatformRate.current()
    if request.method == 'POST':
        if request.POST.get('form') == 'rate':
            status, data = call_api(AdminPlatformRateView, request.user, 'put', {
                'generic_rate': request.POST.get('generic_rate'), 'dnd_rate': request.POST.get('dnd_rate'),
            })
            messages.success(request, 'Platform rate updated.') if status < 300 else messages.error(request, error_text(data))
            return redirect('console-send')
        payload = {
            'sender_id': request.POST.get('sender_id', ''),
            'message': request.POST.get('message', ''),
            'channel': request.POST.get('channel', 'generic'),
        }
        target = request.POST.get('target')
        if target == 'custom':
            payload['manual_numbers'] = [n.strip() for n in request.POST.get('manual_numbers', '').replace('\n', ',').split(',') if n.strip()]
        elif target == 'group':
            payload['group_id'] = request.POST.get('group_id') or None
        else:
            payload['recipient_count'] = User.objects.filter(is_staff=False).count()
        status, data = call_api(AdminCampaignListCreateView, request.user, 'post', payload)
        if status < 300:
            messages.success(request, 'Campaign sent and logged.')
            return redirect('console-send')
        messages.error(request, error_text(data))

    history = Paginator(Campaign.objects.filter(is_admin_campaign=True).order_by('-created_at'), 25).get_page(request.GET.get('page'))
    return render(request, 'console/send.html', {
        'rate': rate,
        'sender_ids': SenderID.objects.filter(platform_status='active'),
        'groups': ContactGroup.objects.filter(user=request.user).annotate(n=Count('contacts')),
        'user_count': User.objects.filter(is_staff=False).count(),
        'page': history,
        'posted': request.POST,
    })


@staff_required
def approvals(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            payload = {
                'name': request.POST.get('name', '').upper(),
                'visibility': request.POST.get('visibility', 'shared'),
                'provider': settings.SMS_PROVIDER,
                'platform_status': request.POST.get('platform_status', 'active'),
            }
            if request.POST.get('user_email'):
                payload['user_email'] = request.POST['user_email']
            status, data = call_api(AdminSenderIDListCreateView, request.user, 'post', payload)
            messages.success(request, 'Sender ID created.') if status < 300 else messages.error(request, error_text(data))
        elif action == 'update':
            status, data = call_api(AdminSenderIDDetailView, request.user, 'patch', {
                'platform_status': request.POST.get('platform_status'),
                'visibility': request.POST.get('visibility'),
            }, pk=request.POST.get('id'))
            messages.success(request, 'Sender ID updated.') if status < 300 else messages.error(request, error_text(data))
        elif action == 'delete':
            status, data = call_api(AdminSenderIDDetailView, request.user, 'delete', {}, pk=request.POST.get('id'))
            messages.success(request, 'Sender ID deleted.') if status < 300 else messages.error(request, error_text(data))
        return redirect('console-approvals')

    rows = SenderID.objects.select_related('user').order_by('-created_at')
    _sync_sender_id_statuses(rows)
    vis = request.GET.get('visibility')
    if vis in ('private', 'shared', 'admin_only'):
        rows = rows.filter(visibility=vis)
    return render(request, 'console/approvals.html', {
        'page': Paginator(rows, 25).get_page(request.GET.get('page')), 'vis': vis,
        'providers': SenderID.PROVIDER_CHOICES, 'statuses': SenderID.PLATFORM_STATUS, 'visibilities': SenderID.VISIBILITY_CHOICES,
    })
