from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Wallet
from apps.accounts.utils import log_wallet_transaction
from apps.contacts.models import ContactGroup
from config.pagination import StandardResultsPagination
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
    CampaignDetailSerializer,
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

# Above this many recipients, CampaignListCreateView.post() doesn't send
# inline — a single Vercel request has a hard duration ceiling (10s on
# Hobby, up to 300s on Pro if configured), and enough chunks can blow
# past that regardless of plan. Past this point the campaign is created
# as PROCESSING and handed to process_campaign_batch instead, called
# repeatedly by an external scheduler until it's done. Comfortably under
# even Hobby's 10s for a single request finishing 20 chunks or fewer.
ASYNC_SEND_THRESHOLD = 2000

# How many chunks one process_campaign_batch call advances a single
# campaign by. Keeps one tick's total duration bounded regardless of how
# large the campaign is — the rest waits for the next tick.
#
# Kept low deliberately: a live timing check against KudiSMS's own API
# from this environment showed one call taking 12.58s against a ~0.8s
# typical — on Vercel Hobby's 10s default function ceiling, even a
# single unlucky chunk in a batch can risk the whole tick. 5 keeps a
# batch's expected total comfortably under that even with one slow call
# in the mix, at the cost of needing more ticks to finish a huge
# campaign — a real tradeoff, not free; Vercel Pro's configurable
# maxDuration (up to 300s) would allow raising this safely.
MAX_CHUNKS_PER_BATCH = 5


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
    pagination_class = StandardResultsPagination

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
            recipients=recipients_numbers,
            unit_cost=unit_cost,
            total_recipients=recipient_count,
            total_cost=cost,
            status='PROCESSING',
        )

        if recipient_count > ASYNC_SEND_THRESHOLD:
            # Too big to safely finish inside one request — leave it
            # PROCESSING and let process_campaign_batch (called
            # repeatedly by an external scheduler hitting POST
            # /api/cron/process-campaigns/) advance it in bounded
            # batches instead. The customer sees it climb via delivered/
            # total_recipients on subsequent GETs, same fields either way.
            return Response(CampaignSerializer(campaign).data, status=status.HTTP_202_ACCEPTED)

        # Small enough to finish right now, same as this always used to
        # work — max_chunks=None processes every recipient in one go.
        _send_campaign_batch(campaign, max_chunks=None)
        _finalize_campaign(campaign)

        if campaign.status == 'FAILED':
            # Deliberately generic: a provider account running low is our
            # problem, not the customer's — their wallet was never
            # actually spent (refunded in _finalize_campaign), and
            # "Sendchamp"/"Termii" means nothing to them. The real reason
            # is on the campaign for admin (Django admin, or GET this
            # campaign as staff).
            return Response(
                {'detail': "We couldn't send this campaign right now. Your wallet was not charged — please try again shortly."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


def _send_campaign_batch(campaign: Campaign, *, max_chunks: int | None) -> bool:
    """Sends chunks of campaign.recipients starting from
    campaign.next_recipient_index, advancing it by at most max_chunks
    chunks this call (None = keep going until every recipient's been
    attempted or a hard provider error stops it — used for a small,
    synchronous send; a bounded number is what a single
    process_campaign_batch tick uses for a large, queued one).

    Updates campaign.delivered/failed/next_recipient_index/
    provider_error and writes SMSLog rows as it goes. Does NOT refund
    unsent recipients or set a final status — call _finalize_campaign
    once this returns True.

    Returns True once every recipient has been attempted (sent or
    failed) — either because the end of the list was reached, or a hard
    provider error stopped it early, in which case everything from that
    point on is marked failed immediately rather than left for a future
    batch to retry (a hard error — bad credentials, provider account
    suspended, network down — would likely just fail identically again).

    Termii's bulk endpoint can return HTTP 200 with a top-level code "ok"
    while its own body says some or all recipients in that chunk were
    rejected — confirmed live: {"code": "ok", "submitted": 0, "rejected":
    1, ...} for a single invalid number. An HTTP success alone does NOT
    mean the chunk was sent; `submitted` is the number to trust. It
    doesn't say *which* recipients were rejected, only how many, so
    within a partially-rejected chunk the first `submitted` numbers are
    treated as sent and the rest as not — a best-effort split, not a
    verified per-recipient result. That partial case does NOT stop the
    loop, unlike a hard error — the next chunk is still attempted.
    """
    provider = campaign.provider
    recipients_numbers = campaign.recipients
    recipient_count = len(recipients_numbers)
    extract_id = {
        'sendchamp': _extract_sendchamp_message_id,
        'kudisms': _extract_kudisms_message_id,
    }.get(provider, _extract_message_id)

    logs: list[SMSLog] = []
    delivered_delta = 0
    failed_delta = 0
    send_error: Exception | None = None
    i = campaign.next_recipient_index
    chunks_done = 0
    while i < recipient_count and (max_chunks is None or chunks_done < max_chunks):
        chunk = recipients_numbers[i : i + CHUNK_SIZE]
        try:
            if provider == 'sendchamp':
                route = 'dnd' if campaign.channel == 'dnd' else 'non_dnd'
                response = sendchamp.send_sms(chunk, campaign.sender_id, campaign.message, route)
                # No partial-accept signal observed/documented for
                # Sendchamp — SendchampClient already raises on any
                # non-success response, so a call that returns here is
                # treated as the whole chunk having gone out.
                delivered_count = len(chunk)
            elif provider == 'kudisms':
                route = 'dnd' if campaign.channel == 'dnd' else 'generic'
                response = kudisms.send_sms(chunk, campaign.sender_id, campaign.message, route)
                # Same reasoning as Sendchamp — KudiSMSClient raises on
                # any non-success response, and their response shape
                # carries no per-recipient/submitted count.
                delivered_count = len(chunk)
            else:
                response = termii.send_bulk(chunk, campaign.sender_id, campaign.message, campaign.channel)
                delivered_count = response.get('submitted', len(chunk))
        except (TermiiError, SendchampError, KudiSMSError) as exc:
            send_error = exc
            remaining = recipients_numbers[i:]
            logs.extend(SMSLog(campaign=campaign, recipient=n, status='FAILED') for n in remaining)
            failed_delta += len(remaining)
            i = recipient_count
            break

        chunk_sent, chunk_unsent = chunk[:delivered_count], chunk[delivered_count:]
        msg_id = extract_id(response)
        logs.extend(SMSLog(campaign=campaign, recipient=n, provider_msg_id=msg_id, status='DELIVERED') for n in chunk_sent)
        logs.extend(SMSLog(campaign=campaign, recipient=n, status='FAILED') for n in chunk_unsent)
        delivered_delta += len(chunk_sent)
        failed_delta += len(chunk_unsent)
        i += len(chunk)
        chunks_done += 1

    SMSLog.objects.bulk_create(logs)
    campaign.delivered += delivered_delta
    campaign.failed += failed_delta
    campaign.next_recipient_index = i
    if send_error:
        campaign.provider_error = f'{provider}: {send_error}'
    campaign.save(update_fields=['delivered', 'failed', 'next_recipient_index', 'provider_error'])

    return i >= recipient_count


def _finalize_campaign(campaign: Campaign) -> None:
    """Refunds whatever wasn't sent and sets the campaign's final status.
    Call only once _send_campaign_batch has returned True (every
    recipient attempted, whether by reaching the end or a hard error).
    Clears `recipients` afterward — nothing needs the raw list again
    once a campaign is done."""
    sent_count = campaign.delivered
    unsent_count = campaign.failed

    if unsent_count:
        refund = Decimal(unsent_count) * campaign.unit_cost
        with transaction.atomic():
            refund_wallet = Wallet.objects.select_for_update().get(user=campaign.user)
            refund_wallet.balance += refund
            refund_wallet.save(update_fields=['balance'])
            log_wallet_transaction(
                campaign.user, refund, f'Refund: {unsent_count} of {campaign.total_recipients} recipients not sent'
            )

    if not sent_count:
        campaign.status = 'FAILED'
    elif unsent_count:
        campaign.status = 'PARTIAL'
    else:
        campaign.status = 'DELIVERED'
    campaign.total_cost = Decimal(sent_count) * campaign.unit_cost
    campaign.recipients = []
    campaign.save(update_fields=['status', 'total_cost', 'recipients'])


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
    serializer_class = CampaignDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Campaign.objects.filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        campaign = self.get_object()
        _refresh_campaign_from_termii(campaign)
        return Response(CampaignDetailSerializer(campaign).data)


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


class ProcessQueuedCampaignsView(APIView):
    """Advances every campaign still PROCESSING (see ASYNC_SEND_THRESHOLD
    on CampaignListCreateView.post()) by up to MAX_CHUNKS_PER_BATCH
    chunks each. Meant to be called roughly once a minute by an external
    scheduler — NOT Vercel's own Cron, which on the Hobby plan is capped
    at once/day, far too infrequent for this.

    No user session involved — this isn't part of the customer or admin
    API, so it's authenticated by a shared secret instead
    (settings.CRON_SECRET) presented as a Bearer token, not a JWT.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        # A blank CRON_SECRET means this is refused unconditionally,
        # never treated as "no secret required" — an unset env var
        # should not silently open this endpoint to the public internet.
        expected = settings.CRON_SECRET
        provided = request.headers.get('Authorization', '')
        if not expected or provided != f'Bearer {expected}':
            return Response(status=status.HTTP_403_FORBIDDEN)

        # Bounded so one slow campaign can't starve every other queued
        # campaign of a turn this tick — oldest first, so a big campaign
        # doesn't get stuck behind newer ones indefinitely either.
        campaigns = Campaign.objects.filter(status='PROCESSING').order_by('created_at')[:5]
        progress = []
        for campaign in campaigns:
            done = _send_campaign_batch(campaign, max_chunks=MAX_CHUNKS_PER_BATCH)
            if done:
                _finalize_campaign(campaign)
            progress.append({
                'id': campaign.id,
                'done': done,
                'sent_so_far': campaign.next_recipient_index,
                'total_recipients': campaign.total_recipients,
            })
        return Response({'processed': progress})


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


class AdminStatsView(APIView):
    """Real aggregates for the admin dashboard's overview cards — total
    users, total user balances, admin SMS sent. All three used to be
    computed by summing/counting whatever was in an unpaginated list
    fetched in full; now that AdminUserListView and
    AdminCampaignListCreateView are paginated, that would silently only
    cover whatever page happened to be loaded, so these are real DB
    aggregates instead."""

    permission_classes = [IsAdmin]

    def get(self, request):
        total_users = User.objects.filter(is_staff=False).count()
        total_balance = Wallet.objects.filter(user__is_staff=False).aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        admin_sms_sent = Campaign.objects.filter(is_admin_campaign=True).aggregate(total=Sum('total_recipients'))['total'] or 0
        return Response({
            'total_users': total_users,
            'total_balance': str(total_balance),
            'admin_sms_sent': admin_sms_sent,
        })


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
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = Campaign.objects.select_related('user').order_by('-created_at')
        # Done server-side, not by the frontend filtering a fetched page,
        # since a fetched page is only ever a slice of the whole table
        # now — filtering client-side would silently miss every failed
        # campaign not on the currently-loaded page.
        if self.request.query_params.get('status_group') == 'failed':
            qs = qs.filter(status__in=['FAILED', 'PARTIAL'])
        return qs


class AdminCampaignListCreateView(generics.ListAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsAdmin]
    pagination_class = StandardResultsPagination

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
