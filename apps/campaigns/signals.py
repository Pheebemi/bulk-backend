"""Emails around Sender ID requests: Admin hears about each new request,
and the customer hears when it flips to approved. Hooked on the model (not
the views) so it fires however the row changes — API, admin console or
Django admin."""

from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.accounts.utils import send_html_email

from .models import SenderID


@receiver(pre_save, sender=SenderID)
def remember_previous_status(sender, instance, **kwargs):
    previous = SenderID.objects.filter(pk=instance.pk).values_list('platform_status', flat=True).first() if instance.pk else None
    instance._previous_status = previous


@receiver(post_save, sender=SenderID)
def notify_sender_id_change(sender, instance, created, **kwargs):
    if instance.visibility != 'private' or not instance.user_id:
        return
    user = instance.user
    if created and instance.platform_status == 'pending':
        send_html_email(
            f'New sender ID request: {instance.name}', 'campaigns/email_sender_request.html',
            {'sender': instance, 'user': user, 'console_url': f'{settings.SITE_URL}/console/approvals/'},
            settings.SENDER_ID_ALERT_EMAILS,
        )
    elif not created and instance.platform_status == 'active' and getattr(instance, '_previous_status', None) != 'active':
        send_html_email(
            f'Your sender ID {instance.name} is approved', 'campaigns/email_sender_approved.html',
            {'sender': instance, 'user': user, 'site_url': settings.SITE_URL},
            [user.email],
        )
    elif not created and instance.platform_status == 'blocked' and getattr(instance, '_previous_status', None) != 'blocked':
        send_html_email(
            f'Your sender ID {instance.name} was not approved', 'campaigns/email_sender_rejected.html',
            {'sender': instance, 'user': user, 'site_url': settings.SITE_URL},
            [user.email],
        )
