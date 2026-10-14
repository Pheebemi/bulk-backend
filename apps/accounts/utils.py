import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailOTP, Wallet, WalletTransaction


def log_wallet_transaction(user, amount: Decimal, description: str) -> None:
    WalletTransaction.objects.create(user=user, amount=amount, description=description)


def create_wallet(user) -> Wallet:
    """New customers start at zero with the welcome bonus still unclaimed."""
    return Wallet.objects.create(user=user)


def claim_welcome_bonus(user) -> bool:
    """One-time credit of settings.SIGNUP_BONUS_NGN. Row-locked so a
    double-click or two tabs can never credit it twice. Returns True only
    on the call that actually paid it out."""
    bonus = Decimal(str(settings.SIGNUP_BONUS_NGN))
    if bonus <= 0:
        return False
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(user=user)
        if wallet.welcome_bonus_claimed:
            return False
        wallet.balance += bonus
        wallet.welcome_bonus_claimed = True
        wallet.save(update_fields=['balance', 'welcome_bonus_claimed'])
        log_wallet_transaction(user, bonus, 'Welcome bonus')
    return True


def send_verification_code(user) -> None:
    """Emails a fresh 6-digit code (replacing any live one). Raises if the
    mail can't be sent, so callers can tell the user instead of pretending."""
    code = f'{secrets.randbelow(1_000_000):06d}'
    EmailOTP.objects.update_or_create(user=user, defaults={'code_hash': make_password(code), 'attempts': 0})
    body = render_to_string('accounts/otp_email.html', {
        'user': user, 'code': code, 'validity_minutes': EmailOTP.VALIDITY_MINUTES,
    })
    message = EmailMessage(subject='Your Reachly verification code', body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
    message.content_subtype = 'html'
    message.send(fail_silently=False)


def resend_wait_seconds(user) -> int:
    otp = EmailOTP.objects.filter(user=user).first()
    if not otp:
        return 0
    remaining = otp.created_at + timedelta(seconds=EmailOTP.RESEND_COOLDOWN_SECONDS) - timezone.now()
    return max(0, int(remaining.total_seconds()))


def check_verification_code(user, code: str):
    """Returns (ok, error_message). Marks the user verified on success."""
    otp = EmailOTP.objects.filter(user=user).first()
    if not otp:
        return False, 'Request a new code first.'
    if timezone.now() > otp.created_at + timedelta(minutes=EmailOTP.VALIDITY_MINUTES):
        return False, 'That code has expired — request a new one.'
    if otp.attempts >= EmailOTP.MAX_ATTEMPTS:
        return False, 'Too many wrong attempts — request a new code.'
    if not check_password(code.strip(), otp.code_hash):
        EmailOTP.objects.filter(pk=otp.pk).update(attempts=otp.attempts + 1)
        return False, 'That code is not correct.'
    user.email_verified = True
    user.save(update_fields=['email_verified'])
    otp.delete()
    return True, ''
