from decimal import Decimal

from django.conf import settings
from django.db import models


class SenderID(models.Model):
    PLATFORM_STATUS = (
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('blocked', 'Blocked'),
    )
    PROVIDER_CHOICES = (('termii', 'Termii'), ('sendchamp', 'Sendchamp'), ('kudisms', 'KudiSMS'))
    VISIBILITY_CHOICES = (
        # Belongs to exactly one customer — the normal request flow.
        ('private', 'Private'),
        # Every customer can send from it immediately, no request needed —
        # previously a hardcoded tuple (integrations.*.DEFAULT_SENDER_IDS),
        # now a real row Admin creates/edits/deletes directly.
        ('shared', 'Shared'),
        # Only the admin console's own "send platform campaign" screen can
        # use it — previously integrations.kudisms.ADMIN_ONLY_SENDER_IDS.
        ('admin_only', 'Admin only'),
    )

    # Null for shared/admin_only rows — nobody in particular owns those.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sender_ids', null=True, blank=True
    )
    name = models.CharField(max_length=11)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    # What the customer told us they'll use this name for. Nothing calls
    # an API with this — every request is submitted by Admin by hand, on
    # whichever provider's own dashboard, so this is purely so Admin has
    # the context to do that without asking the customer again. Blank for
    # shared/admin_only rows, which Admin creates directly.
    use_case = models.TextField(blank=True)
    # Which provider this name is actually registered with. Defaults to
    # termii, but nothing sets that automatically — Admin sets this (and
    # platform_status) by hand once they've submitted the name on that
    # provider's own dashboard and confirmed it's approved. None of
    # Termii, Sendchamp or KudiSMS's request step is called by this
    # codebase; only Termii's status *sync* is (see
    # _sync_sender_id_statuses), for a provider='termii' row Admin
    # submitted manually.
    provider = models.CharField(max_length=10, choices=PROVIDER_CHOICES, default='termii')
    # For a termii-provider row: synced from Termii's GET /api/sender-id
    # (active/pending/blocked) — Termii's own team approves this, not our
    # Admin. See PROJECT_SPEC.md §4. For sendchamp/kudisms, there's no
    # status API to sync from, so this is set by hand once Admin confirms
    # approval directly on that provider's dashboard.
    platform_status = models.CharField(max_length=10, choices=PLATFORM_STATUS, default='pending')
    # DND whitelisting is a separate, manual step (Termii support) — not
    # covered by the Sender ID API at all. Admin flips this once confirmed.
    termii_dnd_whitelisted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A customer can't request the same name twice.
            models.UniqueConstraint(fields=['user', 'name'], condition=models.Q(user__isnull=False), name='unique_private_name_per_user'),
            # Only one shared row can carry a given name at a time.
            models.UniqueConstraint(fields=['name'], condition=models.Q(visibility='shared'), name='unique_shared_name'),
            # Same, for the admin-only pool.
            models.UniqueConstraint(fields=['name'], condition=models.Q(visibility='admin_only'), name='unique_admin_only_name'),
        ]

    def __str__(self):
        return f'{self.name} ({self.platform_status})'


class PlatformRate(models.Model):
    """Single row, Admin-editable. What WE charge users per SMS segment —
    kept separate from Termii's own cost so margin stays visible."""

    generic_rate = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('8.00'))
    dnd_rate = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('10.00'))
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls) -> 'PlatformRate':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def rate_for(self, channel: str) -> Decimal:
        return self.dnd_rate if channel == 'dnd' else self.generic_rate

    def __str__(self):
        return f'generic=₦{self.generic_rate} dnd=₦{self.dnd_rate}'


class Campaign(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('DELIVERED', 'Delivered'),
        # Some chunks reached the provider and some did not; the unsent
        # recipients have been refunded.
        ('PARTIAL', 'Partially delivered'),
        ('FAILED', 'Failed'),
    )
    CHANNEL_CHOICES = (('generic', 'Generic'), ('dnd', 'DND'))
    PROVIDER_CHOICES = (('termii', 'Termii'), ('sendchamp', 'Sendchamp'), ('kudisms', 'KudiSMS'))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='campaigns')
    is_admin_campaign = models.BooleanField(default=False)
    # Which SMS provider actually carried this send — decided by whether
    # sender_id was one of the shared, no-approval-needed names (see
    # integrations.sendchamp.DEFAULT_SENDER_IDS) or a user's own approved
    # Termii sender ID.
    provider = models.CharField(max_length=10, choices=PROVIDER_CHOICES, default='termii')
    sender_id = models.CharField(max_length=11)
    message = models.TextField()
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default='dnd')
    # Set when sent via the Campaign API (phonebook path); null when sent via
    # the Messaging bulk endpoint instead (manual/ad-hoc recipient list).
    termii_campaign_id = models.CharField(max_length=100, blank=True, null=True)
    # A snapshot of the resolved recipient list at send time (whether it
    # came from a saved group or a manual list) — needed so a large
    # campaign can be processed across several cron ticks (see
    # views.process_campaign_batch) without re-deriving it from a group
    # that might have changed since. Only ever grows a row for a large,
    # queued campaign; a small synchronous one clears it once finalized
    # (see _finalize_campaign) since nothing needs it again after that.
    recipients = models.JSONField(default=list, blank=True)
    # How many of `recipients` have been attempted (sent or failed) so
    # far — a large campaign's resume point across multiple batches.
    # Always equal to total_recipients by the time status leaves
    # PROCESSING.
    next_recipient_index = models.PositiveIntegerField(default=0)
    # Per-recipient cost, snapshotted at send time — refund math (for
    # whatever wasn't sent) uses this instead of re-reading
    # PlatformRate.current(), so a rate change while a large campaign is
    # still being processed across several batches can't skew the refund.
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_recipients = models.PositiveIntegerField(default=0)
    delivered = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # charged to user
    termii_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # Termii's actual cost
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    # Raw provider error text on a FAILED/PARTIAL send (e.g. Termii or
    # Sendchamp reporting their own account balance is exhausted) — admin
    # diagnostic only. Never returned to the customer: the API response
    # gives them a generic message instead, since a provider running low
    # is our problem to fix, not something naming "Sendchamp" or "Termii"
    # to a customer would help them understand or act on.
    provider_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.sender_id}: {self.message[:30]}'


class SMSLog(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='logs')
    recipient = models.CharField(max_length=15)
    provider_msg_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, default='PENDING')
    sent_at = models.DateTimeField(auto_now_add=True)
