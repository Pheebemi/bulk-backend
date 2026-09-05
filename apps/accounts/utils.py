from decimal import Decimal

from .models import WalletTransaction


def log_wallet_transaction(user, amount: Decimal, description: str) -> None:
    WalletTransaction.objects.create(user=user, amount=amount, description=description)
