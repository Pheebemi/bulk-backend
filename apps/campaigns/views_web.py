"""Server-rendered campaign + sender-ID pages. Sending itself goes
through the existing DRF views (call_api) so the wallet/provider logic
stays in exactly one place."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.web_utils import call_api, customer_required, error_text
from apps.contacts.models import ContactGroup

from .models import Campaign, MessageTemplate, PlatformRate, SenderID
from .views import (
    CampaignCancelView,
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
        if request.POST.get('send_when') == 'later':
            # <input type="datetime-local"> sends a naive local time; DRF reads
            # it in the project timezone (Africa/Lagos).
            payload['scheduled_at'] = request.POST.get('scheduled_for') or None
        if request.POST.get('source') == 'manual':
            payload['manual_numbers'] = manual
        else:
            payload['group_id'] = request.POST.get('group_id') or None
        status, data = call_api(CampaignListCreateView, request.user, 'post', payload)
        if status < 300:
            tpl_name = request.POST.get('save_template_name', '').strip()[:60]
            if tpl_name:
                MessageTemplate.objects.update_or_create(
                    user=request.user, name=tpl_name, defaults={'body': request.POST.get('message', '')})
            messages.success(request, 'Campaign scheduled.' if data.get('status') == 'SCHEDULED' else 'Campaign submitted.')
            return redirect('web-campaign-detail', pk=data['id'])
        messages.error(request, error_text(data))

    sender_ids = [*SenderID.objects.filter(user=request.user, platform_status='active'),
                  *SenderID.objects.filter(visibility='shared', platform_status='active')]
    groups = [{'id': g.id, 'name': g.name, 'count': g.contacts.count()} for g in ContactGroup.objects.filter(user=request.user)]
    rate = PlatformRate.current()
    templates = list(MessageTemplate.objects.filter(user=request.user).values('id', 'name', 'body'))
    prefill = request.POST.get('message') or next((t['body'] for t in templates if str(t['id']) == request.GET.get('template')), '')
    return render(request, 'campaigns/new.html', {
        'sender_ids': sender_ids,
        'groups': groups,
        'templates': templates,
        'prefill': prefill,
        'config_json': ({
            'templates': {str(t['id']): t['body'] for t in templates},
            'groups': {str(g['id']): g['count'] for g in groups},
            'generic': float(rate.generic_rate),
            'dnd': float(rate.dnd_rate),
            'balance': float(request.user.wallet.balance),
        }),
        'posted': request.POST,
    })


@customer_required
@require_POST
def campaign_cancel(request, pk):
    status, data = call_api(CampaignCancelView, request.user, 'post', {}, pk=pk)
    if status < 300:
        messages.success(request, 'Campaign cancelled — your wallet has been refunded.')
    else:
        messages.error(request, error_text(data))
    return redirect('web-campaign-detail', pk=pk)


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


@customer_required
def template_list(request):
    """Saved messages: list, create, edit and delete on one page."""
    editing = None
    if request.GET.get('edit'):
        editing = MessageTemplate.objects.filter(user=request.user, pk=request.GET['edit']).first()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            MessageTemplate.objects.filter(user=request.user, pk=request.POST.get('id')).delete()
            messages.success(request, 'Template deleted.')
            return redirect('web-templates')
        name, body = request.POST.get('name', '').strip()[:60], request.POST.get('body', '').strip()
        if not name or not body:
            messages.error(request, 'Give the template a name and a message.')
        else:
            pk = request.POST.get('id')
            if pk:
                found = MessageTemplate.objects.filter(user=request.user, pk=pk).first()
                clash = MessageTemplate.objects.filter(user=request.user, name=name).exclude(pk=pk).exists()
                if found and not clash:
                    found.name, found.body = name, body
                    found.save()
                    messages.success(request, 'Template updated.')
                    return redirect('web-templates')
                messages.error(request, 'You already have a template with that name.')
            elif MessageTemplate.objects.filter(user=request.user, name=name).exists():
                messages.error(request, 'You already have a template with that name.')
            else:
                MessageTemplate.objects.create(user=request.user, name=name, body=body)
                messages.success(request, 'Template saved.')
                return redirect('web-templates')
    return render(request, 'campaigns/templates.html', {
        'templates': MessageTemplate.objects.filter(user=request.user), 'editing': editing,
        'posted': request.POST if request.method == 'POST' else None,
    })
