"""
Thin wrapper around the KudiSMS API — a third SMS provider alongside
Termii and Sendchamp. Its advantage: like Sendchamp, it ships with a
sender ID usable immediately, no network approval wait — Darra, approved
on this account within seconds of requesting it.

Confirmed live against KudiSMS's own API on 2026-09-05 (their public docs
at documenter.getpostman.com/view/44181644/2sB2cd3HUd are JS-rendered and
not fetchable as plain HTML, so this was checked directly rather than
scraped): POST /api/balance returned a real balance (₦1,025.00), and
POST /api/sms with sender_id="Darra" and a deliberately invalid recipient
returned error 107 "Please provide a valid phone number" — validation
reached the recipient check, meaning Darra itself passed sender-ID
validation cleanly.

The recipient-batch limit is confirmed, not assumed: KudiSMS's own error
108 names it directly — "The total amount of recipients is more than
the required batch size of 100."

gateway=1 (this file's 'generic' route) is KudiSMS's **promotional SMS
route** — confirmed by their support team reaching out directly on
2026-09-05 after live test sends, warning that OTP/verification-style
messages are not allowed on it at all. That's the likely real reason
Darra (the original shared sender ID) got denied shortly after testing:
the test messages read as OTP/verification content on a route that
doesn't permit it. Since Reachly only ever sends bulk/marketing
campaigns — genuinely promotional by nature — this route is the
correct one for real customer traffic; it's ad-hoc test messages that
need to avoid OTP-style wording ("verification code", "status check",
etc.) to avoid tripping the same flag again.
"""

from __future__ import annotations

import requests
from django.conf import settings


class KudiSMSError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response


class KudiSMSClient:
    # Confirmed by KudiSMS's own docs (error 108): "The total amount of
    # recipients is more than the required batch size of 100."
    CHUNK_SIZE = 100

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.KUDISMS_API_KEY
        self.base_url = (base_url or settings.KUDISMS_BASE_URL).rstrip('/')

    def _request(self, path: str, fields: dict) -> dict:
        # KudiSMS's API is picky about this: the same request sent as
        # application/x-www-form-urlencoded comes back "missing
        # parameters" even with every field present. Confirmed live —
        # multipart/form-data (via `files=`, with each value wrapped as
        # (None, value) so requests sends it as a form field, not a file
        # upload) is what actually works.
        multipart = {k: (None, str(v)) for k, v in fields.items()}
        try:
            resp = requests.post(f'{self.base_url}{path}', files=multipart, timeout=30)
        except requests.exceptions.RequestException as exc:
            raise KudiSMSError(f'KudiSMS POST {path} unreachable: {exc}') from exc
        try:
            body = resp.json()
        except ValueError:
            raise KudiSMSError(f'KudiSMS POST {path}: non-JSON response ({resp.status_code}): {resp.text[:200]}', resp)
        if not resp.ok or body.get('status') == 'error':
            raise KudiSMSError(f'KudiSMS POST {path} failed: {resp.status_code} {body}', resp)
        return body

    def send_sms(self, to: list[str], sender_id: str, message: str, route: str) -> dict:
        """route: 'dnd' (gateway 2, documented) or 'generic' (gateway 1,
        assumed — see module docstring). `to` should already be chunked
        by the caller — see send_bulk_chunked."""
        gateway = '2' if route == 'dnd' else '1'
        return self._request('/api/sms', {
            'token': self.api_key,
            'senderID': sender_id,
            'recipients': ','.join(to),
            'message': message,
            'gateway': gateway,
        })

    def send_bulk_chunked(self, to: list[str], sender_id: str, message: str, route: str) -> list[dict]:
        responses = []
        for i in range(0, len(to), self.CHUNK_SIZE):
            responses.append(self.send_sms(to[i:i + self.CHUNK_SIZE], sender_id, message, route))
        return responses

    def get_balance(self) -> dict:
        return self._request('/api/balance', {'token': self.api_key})

    def register_callback(self, url: str) -> dict:
        """Registers a delivery-report webhook — KudiSMS POSTs real
        per-recipient status (DELIVRD/UNDELIVRD/EXPIRED/REJECTD) to it,
        matched back to a send via api_reference. Neither Termii nor
        Sendchamp's integration has this yet."""
        return self._request('/api/callback', {'token': self.api_key, 'url': url})


kudisms = KudiSMSClient()

# Darra was confirmed live on this account on 2026-09-05, but was denied
# by KudiSMS shortly after (same day) — POST /api/sms now returns
# error_code 106 "The sender ID used does not exist." for it.
#
# Replaced same day with "algaddafhub", "AT-HUB" and "Darrang" — all
# confirmed live via the same invalid-recipient probe used for Darra:
# validation reached the recipient check (error 107 "Please provide a
# valid phone number") rather than error 106 (sender ID doesn't exist),
# meaning each sender ID itself passed cleanly.
DEFAULT_SENDER_IDS: tuple[str, ...] = ('algaddafhub', 'AT-HUB', 'Darrang')

# Also confirmed live the same way, but deliberately kept out of
# DEFAULT_SENDER_IDS: these are for the admin console's own platform
# sends only, not the customer-facing shared pool. See
# ADMIN_ONLY_SENDER_ID_PROVIDERS in campaigns/views.py for where that
# restriction is actually enforced.
ADMIN_ONLY_SENDER_IDS: tuple[str, ...] = ('DAK', 'phee-dev')
