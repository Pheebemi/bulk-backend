"""Server-rendered campaign + sender-ID pages. Sending itself goes
through the existing DRF views (call_api) so the wallet/provider logic
stays in exactly one place."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.web_utils import call_api, customer_required, error_text
from apps.contacts.models import ContactGroup

from .models import Campaign, PlatformRate, SenderID
from .views import (
    CampaignListCreateView,
    SenderIDListCreateView,
    _refresh_campaign_from_termii,
)


@customer_required
def campaign_list(request):
    qs = Campaign.objects.filter(user=request.user, is_admin_campaign=False).order_by('-created_at')
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'campaigns/list.html', {'page': page})


@customer_required
def campaign_new(request):
    if request.method == 'POST':
        manual = [n.strip() for n in request.POST.get('manual_numbers', '').replace('\n', ',').split(',') if n.strip()]
        payload = {
            'sender_id': request.POST.get('sender_id', ''),
            'message': request.POST.get('message', ''),
            'channel': request.POST.get('channel', 'dnd'),
        }
        if request.POST.get('source') == 'manual':
            payload['manual_numbers'] = manual
        else:
            payload['group_id'] = request.POST.get('group_id') or None
        status, data = call_api(CampaignListCreateView, request.user, 'post', payload)
        if status < 300:
            messages.success(request, 'Campaign submitted.')
            return redirect('web-campaign-detail', pk=data['id'])
        messages.error(request, error_text(data))

    sender_ids = [*SenderID.objects.filter(user=request.user, platform_status='active'),
                  *SenderID.objects.filter(visibility='shared', platform_status='active')]
    groups = [{'id': g.id, 'name': g.name, 'count': g.contacts.count()} for g in ContactGroup.objects.filter(user=request.user)]
    rate = PlatformRate.current()
    return render(request, 'campaigns/new.html', {
        'sender_ids': sender_ids,
        'groups': groups,
        'config_json': ({
            'groups': {str(g['id']): g['count'] for g in groups},
            'generic': float(rate.generic_rate),
            'dnd': float(rate.dnd_rate),
            'balance': float(request.user.wallet.balance),
        }),
        'posted': request.POST,
    })


@customer_required
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk, user=request.user)
    _refresh_campaign_from_termii(campaign)
    return render(request, 'campaigns/detail.html', {'campaign': campaign, 'logs': campaign.logs.all()[:200]})


@customer_required
def sender_ids(request):
    if request.method == 'POST':
        status, data = call_api(SenderIDListCreateView, request.user, 'post', {
            'name': request.POST.get('name', ''), 'use_case': request.POST.get('use_case', ''),
        })
        if status < 300:
            messages.success(request, 'Sender ID requested — it will show as pending until approved.')
            return redirect('web-sender-ids')
        messages.error(request, error_text(data))
    owned = SenderID.objects.filter(user=request.user).order_by('-created_at')
    shared = SenderID.objects.filter(visibility='shared', platform_status='active')
    return render(request, 'campaigns/sender_ids.html', {'owned': owned, 'shared': shared})
