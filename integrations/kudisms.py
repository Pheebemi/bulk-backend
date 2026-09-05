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

Two things their docs don't state and this file doesn't invent:
- The exact recipient-batch limit — CHUNK_SIZE below is the same
  assumed-not-verified 100 used for Termii and Sendchamp, not a KudiSMS
  number. Their docs do mention a "batch size of 100" error (code 108),
  which at least confirms 100 is the right ballpark.
- Which gateway value is the plain/non-DND route. Only gateway=2 (DND,
  refunds on non-delivery) is named in their docs. gateway=1 also passes
  sender-ID validation in a live probe (as do 0 and 3, so KudiSMS accepts
  more values than are documented) — used here as generic on the
  ordinary convention of 1 being the default route, not because KudiSMS
  says so.
"""

from __future__ import annotations

import requests
from django.conf import settings


class KudiSMSError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response


class KudiSMSClient:
    # Assumed, not confirmed — see module docstring.
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

# Shared sender ID available without approval — confirmed live against
# this account on 2026-09-05.
DEFAULT_SENDER_IDS = ('Darra',)
