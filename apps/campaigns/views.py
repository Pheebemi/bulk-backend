from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Wallet
from apps.accounts.utils import log_wallet_transaction
from apps.contacts.models import ContactGroup
from integrations.termii import TermiiError, ensure_phonebook, termii

from .models import Campaign, PlatformRate, SenderID, SMSLog
from .permissions import IsAdmin
from .serializers import (
    AdminCampaignCreateSerializer,
    AdminSenderIDSerializer,
    CampaignCreateSerializer,
    CampaignSerializer,
    PlatformRateSerializer,
    SenderIDRequestSerializer,
    SenderIDSerializer,
    WalletAdjustSerializer,
)
from .utils import count_segments

User = get_user_model()


# --- Sender IDs (user) -------------------------------------------------------


class SenderIDListCreateView(generics.ListCreateAPIView):
    serializer_class = SenderIDSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = SenderID.objects.filter(user=self.request.user)
        _sync_sender_id_statuses(qs)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = SenderIDRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data['name'].upper()
        use_case = serializer.validated_data['use_case']

        if SenderID.objects.filter(user=request.user, name=name).exists():
            return Response({'detail': f'{name} has already been requested.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            termii.request_sender_id(name, use_case, company=request.user.full_name or request.user.email)
        except TermiiError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        # get_or_create (not create()) so a genuine concurrent double-submit
        # — both requests passing the .exists() check above before either
        # commits — lands on the unique_together constraint safely instead
        # of raising IntegrityError; the Termii request itself can still
        # double-fire in that narrow race, which is an acceptable tradeoff
        # (a duplicate review request) versus a 500 to the user.
        sender_id, _ = SenderID.objects.get_or_create(user=request.user, name=name, defaults={'platform_status': 'pending'})
        return Response(SenderIDSerializer(sender_id).data, status=status.HTTP_201_CREATED)


def _sync_sender_id_statuses(queryset):
    """Best-effort: pull real status from Termii's GET /api/sender-id and
    update matching local rows by name. Termii's own team is the real
    approver — see PROJECT_SPEC.md §4.

    Skipped entirely once every local row is already active/blocked —
    there's nothing left that could still change, so there's no reason to
    make a page load depend on Termii's API being up and fast."""
    rows = list(queryset)
    if not any(s.platform_status == 'pending' for s in rows):
        return
    try:
        data = termii.fetch_sender_ids()
    except TermiiError:
        return
    by_name = {item.get('sender_id'): item.get('status') for item in data.get('content', [])}
    for sender_id in rows:
        remote_status = by_name.get(sender_id.name)
        if remote_status and remote_status in dict(SenderID.PLATFORM_STATUS) and remote_status != sender_id.platform_status:
            sender_id.platform_status = remote_status
            sender_id.save(update_fields=['platform_status'])


# --- Campaigns (user) --------------------------------------------------------


class CampaignListCreateView(generics.ListAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Campaign.objects.filter(user=self.request.user, is_admin_campaign=False).order_by('-created_at')

    def post(self, request, *args, **kwargs):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        recipients_numbers = None
        group = None
        if data.get('group_id'):
            group = get_object_or_404(ContactGroup, id=data['group_id'], user=request.user)
            recipient_count = group.contacts.count()
        else:
            recipients_numbers = data['manual_numbers']
            recipient_count = len(recipients_numbers)

        if recipient_count == 0:
            return Response({'detail': 'No recipients selected.'}, status=status.HTTP_400_BAD_REQUEST)

        segments = count_segments(data['message'])
        rate = PlatformRate.current().rate_for(data['channel'])
        cost = Decimal(recipient_count) * segments * rate

        # Reserve the funds up front, inside a row lock, so two concurrent
        # sends from the same user can't both pass a stale balance check —
        # whichever request gets here second sees the already-decremented
        # balance. If the Termii call below fails, we refund (see except
        # block) rather than holding the lock for the whole external call.
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(user=request.user)
            if cost > wallet.balance:
                return Response({'detail': 'Insufficient wallet balance.'}, status=status.HTTP_400_BAD_REQUEST)
            wallet.balance -= cost
            wallet.save(update_fields=['balance'])
            log_wallet_transaction(request.user, -cost, f'Campaign: {data["message"][:40]}')

        campaign = Campaign.objects.create(
            user=request.user,
            sender_id=data['sender_id'],
            message=data['message'],
            channel=data['channel'],
            total_recipients=recipient_count,
            total_cost=cost,
            status='PENDING',
        )

        try:
            if group is not None:
                phonebook_id = ensure_phonebook(group)
                result = termii.send_campaign(phonebook_id, data['sender_id'], data['message'], data['channel'])
                campaign.termii_campaign_id = result.get('campaignId')
                campaign.status = 'PROCESSING'
                campaign.save(update_fields=['termii_campaign_id', 'status'])
            else:
                responses = termii.send_bulk_chunked(recipients_numbers, data['sender_id'], data['message'], data['channel'])
                all_ok = all(r.get('code') == 'ok' for r in responses)
                campaign.status = 'DELIVERED' if all_ok else 'FAILED'
                campaign.delivered = recipient_count if all_ok else 0
                campaign.failed = 0 if all_ok else recipient_count
                # Termii's bulk-send response doesn't give per-recipient status,
                # so every log shares the batch's overall outcome — the best
                # granularity this endpoint's response actually offers.
                SMSLog.objects.bulk_create(
                    [SMSLog(campaign=campaign, recipient=n, status=campaign.status) for n in recipients_numbers]
                )
                campaign.save(update_fields=['status', 'delivered', 'failed'])
        except TermiiError as exc:
            campaign.status = 'FAILED'
            campaign.save(update_fields=['status'])
            with transaction.atomic():
                refund_wallet = Wallet.objects.select_for_update().get(user=request.user)
                refund_wallet.balance += cost
                refund_wallet.save(update_fields=['balance'])
                log_wallet_transaction(request.user, cost, 'Refund: campaign send failed')
            return Response({'detail': f'Termii send failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


class CampaignDetailView(generics.RetrieveAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Campaign.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        campaign = self.get_object()
        _refresh_campaign_from_termii(campaign)
        return Response(CampaignSerializer(campaign).data)


class CampaignRetryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, campaign_id, *args, **kwargs):
        campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
        if campaign.status != 'FAILED' or not campaign.termii_campaign_id:
            return Response({'detail': 'Only failed phonebook-based campaigns can be retried.'}, status=400)
        try:
            termii.retry_campaign(campaign.termii_campaign_id)
        except TermiiError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        campaign.status = 'PROCESSING'
        campaign.save(update_fields=['status'])
        return Response(CampaignSerializer(campaign).data)


def _refresh_campaign_from_termii(campaign: Campaign):
    """Campaign-API path only — the Messaging bulk path already resolves
    synchronously at send time (see CampaignListCreateView.post)."""
    if not campaign.termii_campaign_id or campaign.status in ('DELIVERED', 'FAILED'):
        return
    try:
        data = termii.fetch_campaign_history(campaign.termii_campaign_id)
    except TermiiError:
        return
    status_map = {'DELIVERED': 'DELIVERED', 'FAILED': 'FAILED'}
    remote_status = status_map.get(data.get('status'))
    if remote_status:
        campaign.status = remote_status
    campaign.total_recipients = data.get('totalRecipient', campaign.total_recipients)
    campaign.delivered = data.get('totalDelivered', campaign.delivered)
    campaign.failed = data.get('totalFailed', campaign.failed)
    campaign.termii_cost = data.get('cost', campaign.termii_cost)
    campaign.save(update_fields=['status', 'total_recipients', 'delivered', 'failed', 'termii_cost'])


class RateView(APIView):
    """Read-only, any authenticated user — needed so the create-campaign
    screen can show a real cost estimate before sending."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(PlatformRateSerializer(PlatformRate.current()).data)


# --- Admin --------------------------------------------------------------------


class AdminSenderIDListView(generics.ListAPIView):
    serializer_class = AdminSenderIDSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = SenderID.objects.all().select_related('user')
        _sync_sender_id_statuses(qs)
        return qs


class AdminSenderIDDetailView(APIView):
    """The only real admin *action* on a Sender ID: recording that Termii's
    support has confirmed DND whitelisting for it (see PROJECT_SPEC.md §4 —
    Termii's own team decides platform_status via GET /api/sender-id, not
    us; this flag is the one thing we do decide, manually, once they've
    told us)."""

    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        sender_id = get_object_or_404(SenderID, pk=pk)
        whitelisted = request.data.get('termii_dnd_whitelisted')
        if whitelisted is not None:
            sender_id.termii_dnd_whitelisted = bool(whitelisted)
            sender_id.save(update_fields=['termii_dnd_whitelisted'])
        return Response(AdminSenderIDSerializer(sender_id).data)


class AdminPlatformRateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(PlatformRateSerializer(PlatformRate.current()).data)

    def put(self, request):
        rate = PlatformRate.current()
        serializer = PlatformRateSerializer(rate, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AdminWalletAdjustView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        wallet, _ = Wallet.objects.get_or_create(user=target_user)
        serializer = WalletAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']
        signed = amount if serializer.validated_data['direction'] == 'credit' else -amount
        reason = serializer.validated_data.get('reason') or ('Manual credit' if signed > 0 else 'Manual debit')
        with transaction.atomic():
            wallet.balance += signed
            wallet.save(update_fields=['balance'])
            log_wallet_transaction(target_user, signed, reason)
        return Response({'balance': str(wallet.balance)})


class AdminCampaignListCreateView(generics.ListAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        return Campaign.objects.filter(is_admin_campaign=True).order_by('-created_at')

    def post(self, request, *args, **kwargs):
        serializer = AdminCampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recipients_numbers = data.get('manual_numbers') or []
        recipient_count = len(recipients_numbers) or data.get('recipient_count', 0)

        if recipient_count == 0:
            return Response({'detail': 'No recipients selected.'}, status=status.HTTP_400_BAD_REQUEST)

        segments = count_segments(data['message'])
        # Reference cost only — admin sends aren't charged to any wallet.
        reference_rate = Decimal('6.00') if data['channel'] == 'generic' else Decimal('8.00')

        campaign = Campaign.objects.create(
            user=request.user,
            is_admin_campaign=True,
            sender_id=data['sender_id'],
            message=data['message'],
            channel=data['channel'],
            total_recipients=recipient_count,
            total_cost=Decimal('0.00'),
            termii_cost=Decimal(recipient_count) * segments * reference_rate,
            status='DELIVERED',
            delivered=recipient_count,
        )
        if recipients_numbers:
            try:
                termii.send_bulk_chunked(recipients_numbers, data['sender_id'], data['message'], data['channel'])
            except TermiiError as exc:
                campaign.status = 'FAILED'
                campaign.save(update_fields=['status'])
                return Response({'detail': f'Termii send failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)
