from decimal import Decimal

from django.conf import settings
from django.db import transaction

from .models import Wallet, WalletTransaction


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
