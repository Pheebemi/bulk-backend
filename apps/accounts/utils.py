from decimal import Decimal

from django.conf import settings

from .models import Wallet, WalletTransaction


def log_wallet_transaction(user, amount: Decimal, description: str) -> None:
    WalletTransaction.objects.create(user=user, amount=amount, description=description)


def create_wallet_with_bonus(user) -> Wallet:
    """Every new customer's wallet starts with the welcome bonus
    (settings.SIGNUP_BONUS_NGN), recorded in the ledger like any credit."""
    bonus = Decimal(str(settings.SIGNUP_BONUS_NGN))
    wallet = Wallet.objects.create(user=user, balance=bonus)
    if bonus > 0:
        log_wallet_transaction(user, bonus, 'Welcome bonus')
    return wallet
