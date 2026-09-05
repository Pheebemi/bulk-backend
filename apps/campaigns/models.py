from decimal import Decimal

from django.conf import settings
from django.db import models


class SenderID(models.Model):
    PLATFORM_STATUS = (
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('blocked', 'Blocked'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sender_ids')
    name = models.CharField(max_length=11)
    # Synced from Termii's GET /api/sender-id (active/pending/blocked) —
    # Termii's own team approves this, not our Admin. See PROJECT_SPEC.md §4.
    platform_status = models.CharField(max_length=10, choices=PLATFORM_STATUS, default='pending')
    # DND whitelisting is a separate, manual step (Termii support) — not
    # covered by the Sender ID API at all. Admin flips this once confirmed.
    termii_dnd_whitelisted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'name']

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
        ('FAILED', 'Failed'),
    )
    CHANNEL_CHOICES = (('generic', 'Generic'), ('dnd', 'DND'))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='campaigns')
    is_admin_campaign = models.BooleanField(default=False)
    sender_id = models.CharField(max_length=11)
    message = models.TextField()
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default='dnd')
    # Set when sent via the Campaign API (phonebook path); null when sent via
    # the Messaging bulk endpoint instead (manual/ad-hoc recipient list).
    termii_campaign_id = models.CharField(max_length=100, blank=True, null=True)
    total_recipients = models.PositiveIntegerField(default=0)
    delivered = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # charged to user
    termii_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # Termii's actual cost
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.sender_id}: {self.message[:30]}'


class SMSLog(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='logs')
    recipient = models.CharField(max_length=15)
    provider_msg_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, default='PENDING')
    sent_at = models.DateTimeField(auto_now_add=True)
