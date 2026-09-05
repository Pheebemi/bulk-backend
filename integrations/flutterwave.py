"""
Flutterwave v3 client. The frontend triggers payment client-side via the
inline checkout (flutterwave-react-v3, public key only) — this backend's
job is to VERIFY the transaction server-side before crediting any wallet.
Never trust a client-reported "successful" status on its own.
"""

from __future__ import annotations

import requests
from django.conf import settings


class FlutterwaveError(Exception):
    pass


class FlutterwaveClient:
    def __init__(self, secret_key: str | None = None, base_url: str | None = None):
        self.secret_key = secret_key or settings.FLUTTERWAVE_SECRET_KEY
        self.base_url = (base_url or settings.FLUTTERWAVE_BASE_URL).rstrip('/')

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self.secret_key}'}

    def verify_transaction(self, transaction_id: str) -> dict:
        try:
            resp = requests.get(
                f'{self.base_url}/transactions/{transaction_id}/verify',
                headers=self._headers(),
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise FlutterwaveError(f'Verify request unreachable: {exc}') from exc
        if not resp.ok:
            raise FlutterwaveError(f'Verify failed: {resp.status_code} {resp.text}')
        return resp.json()


flutterwave = FlutterwaveClient()
