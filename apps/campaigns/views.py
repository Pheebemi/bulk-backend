from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Wallet
from apps.accounts.utils import log_wallet_transaction
from apps.contacts.models import ContactGroup
from integrations.termii import TermiiError, termii
from integrations.sendchamp import SendchampError, sendchamp
from integrations.kudisms import KudiSMSError, kudisms

from .models import Campaign, PlatformRate, SenderID, SMSLog
from .permissions import IsAdmin
from .serializers import (
    AdminCampaignCreateSerializer,
    AdminCampaignSerializer,
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

# Termii's bulk endpoint accepts at most 100 numbers per call.
CHUNK_SIZE = 100


# --- Sender IDs (user) -------------------------------------------------------


class SenderIDListCreateView(generics.ListCreateAPIView):
    serializer_class = SenderIDSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = SenderID.objects.filter(user=self.request.user)
        _sync_sender_id_statuses(qs)
        return qs

    def list(self, request, *args, **kwargs):
        # The user's own requested sender IDs, plus every active shared
        # row every account can send from immediately — both are real
        # SenderID rows now (see SenderID.visibility), Admin-managed from
        # the admin console instead of a hardcoded list in code.
        owned = self.get_queryset()
        shared = SenderID.objects.filter(visibility='shared', platform_status='active')
        return Response(SenderIDSerializer([*owned, *shared], many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = SenderIDRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data['name'].upper()
        use_case = serializer.validated_data['use_case']

        if SenderID.objects.filter(user=request.user, name=name).exists():
            return Response({'detail': f'{name} has already been requested.'}, status=status.HTTP_400_BAD_REQUEST)

        # Nothing is submitted to any provider here — Admin does that by
        # hand, on whichever provider's dashboard they choose, once they've
        # seen this request (see AdminSenderIDDetailView.patch). This just
        # records that the customer asked, and why.
        #
        # get_or_create (not create()) so a genuine concurrent double-submit
        # — both requests passing the .exists() check above before either
        # commits — lands on the unique_together constraint safely instead
        # of raising IntegrityError.
        sender_id, _ = SenderID.objects.get_or_create(
            user=request.user, name=name, defaults={'platform_status': 'pending', 'use_case': use_case}
        )
        return Response(SenderIDSerializer(sender_id).data, status=status.HTTP_201_CREATED)


def _sync_sender_id_statuses(queryset):
    """Best-effort: pull real status from Termii's GET /api/sender-id and
    update matching local rows by name. Termii's own team is the real
    approver — see PROJECT_SPEC.md §4.

    Only ever touches provider='termii' rows — a sendchamp/kudisms row
    has no equivalent status API, so it stays exactly as Admin last set
    it (see AdminSenderIDDetailView.patch) until they change it by hand.

    Skipped entirely once every relevant local row is already
    active/blocked — there's nothing left that could still change, so
    there's no reason to make a page load depend on Termii's API being
    up and fast."""
    rows = [s for s in queryset if s.provider == 'termii']
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

        # Recipients always come out of our own database — a saved group's
        # numbers and a manually typed list are the same thing by the time
        # they reach Termii. Nothing is stored in a Termii phonebook.
        if data.get('group_id'):
            group = get_object_or_404(ContactGroup, id=data['group_id'], user=request.user)
            recipients_numbers = list(group.contacts.values_list('phone_number', flat=True))
        else:
            recipients_numbers = list(data['manual_numbers'])
        recipient_count = len(recipients_numbers)

        if recipient_count == 0:
            return Response({'detail': 'No recipients selected.'}, status=status.HTTP_400_BAD_REQUEST)

        # A shared row (visibility='shared') needs no per-account approval
        # and routes straight to whichever provider Admin registered it
        # on; any other name must be this user's own approved sender ID
        # (visibility='private', owned by them) — admin_only rows never
        # match here, so a customer typing one of those hits the same
        # rejection as any other name they don't own.
        sender_id = data['sender_id']
        matched_sender_id = SenderID.objects.filter(name=sender_id, platform_status='active').filter(
            Q(visibility='shared') | Q(visibility='private', user=request.user)
        ).first()
        if not matched_sender_id:
            return Response(
                {'detail': f'"{sender_id}" is not an approved sender ID on your account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        provider = matched_sender_id.provider

        segments = count_segments(data['message'])
        rate = PlatformRate.current().rate_for(data['channel'])
        # Per-recipient price is kept separate so a partial send can be
        # refunded by the recipient, not all-or-nothing.
        unit_cost = Decimal(segments) * rate
        cost = Decimal(recipient_count) * unit_cost

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
            provider=provider,
            sender_id=sender_id,
            message=data['message'],
            channel=data['channel'],
            total_recipients=recipient_count,
            total_cost=cost,
            status='PENDING',
        )

        # Send chunk by chunk, tracking what actually left. Refunding the
        # whole campaign when a late chunk fails would hand back money for
        # messages the provider has already delivered and billed us for,
        # so only the recipients that never went out are refunded.
        #
        # Termii's bulk endpoint can return HTTP 200 with a top-level
        # code "ok" while its own body says some or all recipients in
        # that chunk were rejected — confirmed live:
        # {"code": "ok", "submitted": 0, "rejected": 1, ...} for a single
        # invalid number. An HTTP success alone does NOT mean the chunk
        # was sent; `submitted` is the number to trust. It doesn't say
        # *which* recipients were rejected, only how many, so within a
        # partially-rejected chunk the first `submitted` numbers are
        # treated as sent and the rest as not — a best-effort split, not
        # a verified per-recipient result.
        extract_id = {
            'sendchamp': _extract_sendchamp_message_id,
            'kudisms': _extract_kudisms_message_id,
        }.get(provider, _extract_message_id)
        sent: list[str] = []
        unsent: list[str] = []
        logs: list[SMSLog] = []
        send_error: Exception | None = None
        for i in range(0, recipient_count, CHUNK_SIZE):
            chunk = recipients_numbers[i : i + CHUNK_SIZE]
            try:
                if provider == 'sendchamp':
                    route = 'dnd' if data['channel'] == 'dnd' else 'non_dnd'
                    response = sendchamp.send_sms(chunk, sender_id, data['message'], route)
                    # No partial-accept signal observed/documented for
                    # Sendchamp — SendchampClient already raises on any
                    # non-success response, so a call that returns here
                    # is treated as the whole chunk having gone out.
                    delivered_count = len(chunk)
                elif provider == 'kudisms':
                    route = 'dnd' if data['channel'] == 'dnd' else 'generic'
                    response = kudisms.send_sms(chunk, sender_id, data['message'], route)
                    # Same reasoning as Sendchamp — KudiSMSClient raises
                    # on any non-success response, and their response
                    # shape carries no per-recipient/submitted count.
                    delivered_count = len(chunk)
                else:
                    response = termii.send_bulk(chunk, sender_id, data['message'], data['channel'])
                    delivered_count = response.get('submitted', len(chunk))
            except (TermiiError, SendchampError, KudiSMSError) as exc:
                send_error = exc
                unsent.extend(chunk)
                logs.extend(SMSLog(campaign=campaign, recipient=n, status='FAILED') for n in chunk)
                break

            chunk_sent, chunk_unsent = chunk[:delivered_count], chunk[delivered_count:]
            sent.extend(chunk_sent)
            unsent.extend(chunk_unsent)
            msg_id = extract_id(response)
            logs.extend(SMSLog(campaign=campaign, recipient=n, provider_msg_id=msg_id, status='DELIVERED') for n in chunk_sent)
            logs.extend(SMSLog(campaign=campaign, recipient=n, status='FAILED') for n in chunk_unsent)

        # Any chunk never attempted at all (loop broke early) still needs
        # its recipients recorded as failed.
        attempted = len(sent) + len(unsent)
        logs.extend(SMSLog(campaign=campaign, recipient=n, status='FAILED') for n in recipients_numbers[attempted:])
        unsent.extend(recipients_numbers[attempted:])
        SMSLog.objects.bulk_create(logs)

        if unsent:
            refund = Decimal(len(unsent)) * unit_cost
            with transaction.atomic():
                refund_wallet = Wallet.objects.select_for_update().get(user=request.user)
                refund_wallet.balance += refund
                refund_wallet.save(update_fields=['balance'])
                log_wallet_transaction(
                    request.user, refund, f'Refund: {len(unsent)} of {recipient_count} recipients not sent'
                )

        if not sent:
            campaign.status = 'FAILED'
        elif unsent:
            campaign.status = 'PARTIAL'
        else:
            campaign.status = 'DELIVERED'
        campaign.delivered = len(sent)
        campaign.failed = len(unsent)
        campaign.total_cost = Decimal(len(sent)) * unit_cost
        if send_error:
            campaign.provider_error = f'{provider}: {send_error}'
        campaign.save(update_fields=['status', 'delivered', 'failed', 'total_cost', 'provider_error'])

        if not sent:
            # Deliberately generic: a provider account running low is our
            # problem, not the customer's — their wallet was never
            # actually spent (refunded above), and "Sendchamp"/"Termii"
            # means nothing to them. The real reason is on the campaign
            # for admin (Django admin, or GET this campaign as staff).
            return Response(
                {'detail': "We couldn't send this campaign right now. Your wallet was not charged — please try again shortly."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


def _extract_message_id(response: dict) -> str | None:
    """Termii has used several names for the id it returns on send
    (message_id, messageId, id). Take whichever is present rather than
    silently storing nothing if the shape shifts again."""
    if not isinstance(response, dict):
        return None
    for key in ('message_id', 'messageId', 'id'):
        value = response.get(key)
        if value:
            return str(value)[:100]
    return None


def _extract_sendchamp_message_id(response: dict) -> str | None:
    """Per Sendchamp's own Send SMS OpenAPI spec, a successful response
    nests the id under data.id (data.reference carries the same value)."""
    if not isinstance(response, dict):
        return None
    data = response.get('data') or {}
    value = data.get('id') or data.get('reference')
    return str(value)[:100] if value else None


def _extract_kudisms_message_id(response: dict) -> str | None:
    """KudiSMS's confirmed live response shape is unusual: data is a
    one-element list holding a single string of comma-separated
    "number|uuid" pairs, e.g.
    ["234703xxxxx|fd2913aa-...,234703xxxxx|52d21697-..."] — one uuid per
    recipient in the chunk, not one id for the whole call. Since delivery
    tracking here is chunk-level either way (see the module note on
    KudiSMS having no submitted/rejected-style count), this takes the
    first pair's uuid as the chunk's representative id rather than
    trying to map each uuid back to its own recipient."""
    if not isinstance(response, dict):
        return None
    data = response.get('data')
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        return None
    first_pair = data[0].split(',')[0]
    _, _, uuid = first_pair.partition('|')
    return uuid[:100] if uuid else None


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
        # Retry existed for the Campaign API (phonebook) path, which ran
        # asynchronously on Termii's side and could be re-kicked by id.
        # Direct bulk sends resolve synchronously and a failed one is
        # refunded in full at send time, so there is nothing to re-kick —
        # the user simply sends again, and is charged again.
        return Response(
            {'detail': 'Retry is not available for direct sends. Create the campaign again to resend.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


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


class AdminSenderIDListCreateView(generics.ListCreateAPIView):
    """Every Sender ID row on the platform — private (with whoever owns
    it), shared, and admin-only alike — with full create here and
    edit/delete on AdminSenderIDDetailView. Replaces what used to be a
    read-only list plus two hardcoded Python tuples
    (integrations.sendchamp/kudisms.DEFAULT_SENDER_IDS,
    integrations.kudisms.ADMIN_ONLY_SENDER_IDS) that needed a code change
    and deploy to touch — now it's all real rows, managed from here."""

    serializer_class = AdminSenderIDSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = SenderID.objects.all().select_related('user').order_by('-created_at')
        _sync_sender_id_statuses(qs)
        return qs


class AdminSenderIDDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Full edit and delete for one Sender ID row, whatever its
    visibility. Covers everything Admin decides by hand — provider,
    platform_status, DND whitelisting, even reassigning visibility or
    owner — since none of Termii, Sendchamp or KudiSMS's request/approval
    steps are called by this codebase (see SenderID.provider's
    docstring); Admin submits on the provider's own dashboard directly
    and records the outcome here.

    Delete removes the row outright. Campaign.sender_id is a plain
    CharField, not a foreign key, so a campaign's history is unaffected
    by deleting the SenderID row that sent it."""

    queryset = SenderID.objects.all()
    serializer_class = AdminSenderIDSerializer
    permission_classes = [IsAdmin]


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


class AdminAllCampaignsListView(generics.ListAPIView):
    """Every campaign on the platform — customer sends and admin's own —
    for the admin console's monitor, distinct from
    AdminCampaignListCreateView which only lists admin's own (that one
    backs the Send screen's history, scoped on purpose)."""

    serializer_class = AdminCampaignSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        return Campaign.objects.select_related('user').order_by('-created_at')


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

        sender_id = data['sender_id']
        # Admin can send from any active row regardless of visibility —
        # admin_only, shared, or even a customer's private one — unlike
        # CampaignListCreateView.post() there's no ownership check here,
        # only IsAdmin can reach this view at all. Falls back to termii
        # for a name with no matching row (shouldn't normally happen once
        # every provider approval goes through AdminSenderIDDetailView,
        # but matches this view's prior behavior rather than hard-failing).
        matched_sender_id = SenderID.objects.filter(name=sender_id, platform_status='active').first()
        provider = matched_sender_id.provider if matched_sender_id else 'termii'

        segments = count_segments(data['message'])
        # Reference cost only — admin sends aren't charged to any wallet.
        reference_rate = Decimal('6.00') if data['channel'] == 'generic' else Decimal('8.00')

        campaign = Campaign.objects.create(
            user=request.user,
            is_admin_campaign=True,
            provider=provider,
            sender_id=sender_id,
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
                if provider == 'sendchamp':
                    route = 'dnd' if data['channel'] == 'dnd' else 'non_dnd'
                    sendchamp.send_bulk_chunked(recipients_numbers, sender_id, data['message'], route)
                elif provider == 'kudisms':
                    route = 'dnd' if data['channel'] == 'dnd' else 'generic'
                    kudisms.send_bulk_chunked(recipients_numbers, sender_id, data['message'], route)
                else:
                    termii.send_bulk_chunked(recipients_numbers, sender_id, data['message'], data['channel'])
            except (TermiiError, SendchampError, KudiSMSError) as exc:
                campaign.status = 'FAILED'
                campaign.provider_error = f'{provider}: {exc}'
                campaign.save(update_fields=['status', 'provider_error'])
                return Response({'detail': f'{provider} send failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)
