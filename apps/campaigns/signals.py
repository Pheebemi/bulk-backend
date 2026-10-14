"""Emails around Sender ID requests: Admin hears about each new request,
and the customer hears when it flips to approved. Hooked on the model (not
the views) so it fires however the row changes — API, admin console or
Django admin."""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template.loader import render_to_string

from .models import SenderID

logger = logging.getLogger(__name__)


def _send(subject, template, context, to):
    """Best-effort: a mail failure must never break the request or the
    admin's save, so it's logged and swallowed."""
    try:
        message = EmailMessage(
            subject=subject, body=render_to_string(template, context),
            from_email=settings.DEFAULT_FROM_EMAIL, to=to,
        )
        message.content_subtype = 'html'
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Sender ID email failed (%s -> %s)', subject, to)


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
        _send(
            f'New sender ID request: {instance.name}', 'campaigns/email_sender_request.html',
            {'sender': instance, 'user': user, 'console_url': f'{settings.SITE_URL}/console/approvals/'},
            settings.SENDER_ID_ALERT_EMAILS,
        )
    elif not created and instance.platform_status == 'active' and getattr(instance, '_previous_status', None) != 'active':
        _send(
            f'Your sender ID {instance.name} is approved', 'campaigns/email_sender_approved.html',
            {'sender': instance, 'user': user, 'site_url': settings.SITE_URL},
            [user.email],
        )
