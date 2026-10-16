"""Server-rendered admin console (/console/…) — the replacement for the
Next.js /admin/* screens. Mutations go through the existing DRF admin
views (call_api) so validation and side effects stay in one place."""

from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from datetime import timedelta
import csv
from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import EmailLoginForm
from apps.accounts.models import Wallet, WalletTransaction
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


def _money(value):
    return value or Decimal('0.00')


def _profit_row(qs):
    agg = qs.aggregate(revenue=Sum('total_cost'), cost=Sum('termii_cost'), sms=Sum('delivered'))
    revenue, cost = _money(agg['revenue']), _money(agg['cost'])
    profit = revenue - cost
    return {
        'revenue': revenue, 'cost': cost, 'profit': profit, 'sms': agg['sms'] or 0,
        'margin': (profit / revenue * 100) if revenue else Decimal('0'),
    }


def _profit_report(rate):
    """Customer revenue vs what the provider charged us, from customer
    campaigns only (admin sends earn nothing). Failed sends have zero on
    both sides, so they drop out naturally."""
    base = Campaign.objects.filter(is_admin_campaign=False)
    now = timezone.localtime()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = [
        ('Today', base.filter(created_at__gte=start_today)),
        ('Last 7 days', base.filter(created_at__gte=start_today - timedelta(days=6))),
        ('Last 30 days', base.filter(created_at__gte=start_today - timedelta(days=29))),
        ('All time', base),
    ]
    daily = (
        base.filter(created_at__gte=start_today - timedelta(days=13))
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(revenue=Sum('total_cost'), cost=Sum('termii_cost'), sms=Sum('delivered'))
        .order_by('-day')
    )
    daily_rows = []
    for d in daily:
        revenue, cost = _money(d['revenue']), _money(d['cost'])
        daily_rows.append({'day': d['day'], 'sms': d['sms'] or 0, 'revenue': revenue, 'cost': cost, 'profit': revenue - cost})
    bonuses = _money(WalletTransaction.objects.filter(description='Welcome bonus').aggregate(t=Sum('amount'))['t'])
    all_time = _profit_row(base)
    return {
        'periods': [(label, _profit_row(qs)) for label, qs in periods],
        'channels': [(label, _profit_row(base.filter(channel=ch))) for ch, label in (('generic', 'Generic'), ('dnd', 'DND'))],
        'daily': daily_rows,
        'bonuses': bonuses,
        'net_after_bonuses': all_time['profit'] - bonuses,
        'unit_margin_generic': rate.generic_rate - rate.cost_generic,
        'unit_margin_dnd': rate.dnd_rate - rate.cost_dnd,
    }


@staff_required
def analytics(request):
    rate = PlatformRate.current()
    if request.method == 'POST':
        try:
            cost_generic = Decimal(request.POST.get('cost_generic', ''))
            cost_dnd = Decimal(request.POST.get('cost_dnd', ''))
            if cost_generic < 0 or cost_dnd < 0:
                raise ValueError
        except (ArithmeticError, ValueError):
            messages.error(request, 'Enter valid provider costs.')
        else:
            rate.cost_generic, rate.cost_dnd = cost_generic, cost_dnd
            rate.save(update_fields=['cost_generic', 'cost_dnd', 'updated_at'])
            messages.success(request, 'Provider costs updated. They apply to new sends.')
        return redirect('console-analytics')

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
        'profit': _profit_report(rate), 'rate': rate,
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
                'rejection_reason': request.POST.get('rejection_reason', '').strip(),
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


# --- Users --------------------------------------------------------------------


def _customers_qs(q='', status=''):
    qs = (
        User.objects.filter(is_staff=False)
        .select_related('wallet')
        .annotate(
            campaigns_count=Count('campaigns', filter=Q(campaigns__is_admin_campaign=False), distinct=True),
            total_spent=Coalesce(Sum('campaigns__total_cost', filter=Q(campaigns__is_admin_campaign=False)), Value(Decimal('0.00'))),
        )
        .order_by('-date_joined')
    )
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q) | Q(phone_number__icontains=q))
    if status == 'blocked':
        qs = qs.filter(is_active=False)
    elif status == 'active':
        qs = qs.filter(is_active=True)
    return qs


@staff_required
def users(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = _customers_qs(q, status)
    return render(request, 'console/users.html', {
        'page': Paginator(qs, 25).get_page(request.GET.get('page')), 'q': q, 'status': status,
        'total': User.objects.filter(is_staff=False).count(),
        'blocked': User.objects.filter(is_staff=False, is_active=False).count(),
    })


@staff_required
def user_detail(request, pk):
    customer = get_object_or_404(User, pk=pk, is_staff=False)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'block':
            customer.is_active = False
            messages.success(request, f'{customer.email} is blocked and signed out. They can no longer log in or send.')
        elif action == 'unblock':
            customer.is_active = True
            messages.success(request, f'{customer.email} is active again.')
        customer.save(update_fields=['is_active'])
        return redirect('console-user-detail', pk=pk)

    wallet, _ = Wallet.objects.get_or_create(user=customer)
    camps = Campaign.objects.filter(user=customer, is_admin_campaign=False)
    agg = camps.aggregate(spent=Sum('total_cost'), recipients=Sum('delivered'))
    return render(request, 'console/user_detail.html', {
        'c': customer, 'wallet': wallet,
        'campaigns_count': camps.count(), 'spent': _money(agg['spent']), 'delivered': agg['recipients'] or 0,
        'recent': camps.order_by('-created_at')[:10],
        'history': WalletTransaction.objects.filter(user=customer).order_by('-created_at')[:10],
        'sender_ids': SenderID.objects.filter(user=customer).order_by('-created_at'),
    })


def _csv_response(filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@staff_required
def export_users(request):
    response = _csv_response(f'users-{date.today().isoformat()}.csv')
    writer = csv.writer(response)
    writer.writerow(['Email', 'Name', 'Phone', 'Joined', 'Verified', 'Status', 'Balance (NGN)', 'Campaigns', 'Total spent (NGN)'])
    for u in _customers_qs(request.GET.get('q', '').strip(), request.GET.get('status', '')):
        writer.writerow([
            u.email, u.full_name, u.phone_number, timezone.localtime(u.date_joined).strftime('%Y-%m-%d'),
            'yes' if u.email_verified else 'no', 'active' if u.is_active else 'blocked',
            getattr(getattr(u, 'wallet', None), 'balance', 0), u.campaigns_count, u.total_spent,
        ])
    return response


def _parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@staff_required
def export_revenue(request):
    """One row per customer campaign that delivered something, with revenue,
    provider cost and profit; a totals row closes the file."""
    start, end = _parse_day(request.GET.get('from')), _parse_day(request.GET.get('to'))
    qs = Campaign.objects.filter(is_admin_campaign=False, delivered__gt=0).select_related('user').order_by('created_at')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    label = f'{start or "start"}_to_{end or "today"}'
    response = _csv_response(f'revenue-{label}.csv')
    writer = csv.writer(response)
    writer.writerow(['Date', 'Campaign', 'Customer', 'Sender ID', 'Route', 'Delivered', 'Revenue (NGN)', 'Provider cost (NGN)', 'Profit (NGN)'])
    revenue = cost = Decimal('0.00')
    delivered = 0
    for c in qs:
        profit = c.total_cost - c.termii_cost
        revenue, cost, delivered = revenue + c.total_cost, cost + c.termii_cost, delivered + c.delivered
        writer.writerow([
            timezone.localtime(c.created_at).strftime('%Y-%m-%d %H:%M'), c.pk, c.user.email, c.sender_id,
            c.channel.upper(), c.delivered, c.total_cost, c.termii_cost, profit,
        ])
    writer.writerow([])
    writer.writerow(['TOTAL', '', '', '', '', delivered, revenue, cost, revenue - cost])
    return response
