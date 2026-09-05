"""
Thin wrapper around the Sendchamp SMS API — a secondary provider used
alongside Termii (see integrations.termii). Its main advantage: it ships
with default sender IDs (Sendchamp, SAlert, SC-OTP) usable immediately,
where a custom Termii sender ID needs 1-2 days of network approval.

Confirmed live against Sendchamp's own API on 2026-09-05 (not just their
docs, which don't expose a browsable endpoint reference): the request/
response shapes below match a real 407 "Low balance" response from
POST /sms/send using all three default sender IDs on both the dnd and
non_dnd routes — everything short of an actual funded send.

The per-call recipient limit for /sms/send's `to` array isn't documented
anywhere Sendchamp publishes. CHUNK_SIZE below is a conservative assumed
limit (matching Termii's confirmed real one), not a verified one —
revisit if Sendchamp's support/docs ever state their actual cap.
"""

from __future__ import annotations

import requests
from django.conf import settings


class SendchampError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response


class SendchampClient:
    # Unverified — see module docstring.
    CHUNK_SIZE = 100

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.SENDCHAMP_API_KEY
        self.base_url = (base_url or settings.SENDCHAMP_BASE_URL).rstrip('/')

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = requests.request(method, f'{self.base_url}{path}', headers=self._headers(), timeout=30, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise SendchampError(f'Sendchamp {method} {path} unreachable: {exc}') from exc
        try:
            body = resp.json()
        except ValueError:
            raise SendchampError(f'Sendchamp {method} {path}: non-JSON response ({resp.status_code}): {resp.text[:200]}', resp)
        # Sendchamp signals failure via body["status"] rather than always
        # using a 4xx/5xx HTTP status (e.g. 407 "Low balance" is the one
        # confirmed exception that IS a real HTTP error code; treat both
        # patterns as failure to be safe).
        if not resp.ok or body.get('status') not in ('success', None):
            raise SendchampError(f'Sendchamp {method} {path} failed: {resp.status_code} {body}', resp)
        return body

    def send_sms(self, to: list[str], sender_name: str, message: str, route: str) -> dict:
        """route: 'dnd', 'non_dnd', or 'international'. `to` should already
        be chunked by the caller — see send_bulk_chunked."""
        return self._request('POST', '/sms/send', json={
            'to': to,
            'message': message,
            'sender_name': sender_name,
            'route': route,
        })

    def send_bulk_chunked(self, to: list[str], sender_name: str, message: str, route: str) -> list[dict]:
        responses = []
        for i in range(0, len(to), self.CHUNK_SIZE):
            responses.append(self.send_sms(to[i:i + self.CHUNK_SIZE], sender_name, message, route))
        return responses

    def sms_status(self, sms_uid: str) -> dict:
        return self._request('GET', f'/sms/status/{sms_uid}')

    def bulk_sms_status(self, bulk_sms_uid: str) -> dict:
        return self._request('GET', f'/sms/bulk-sms-status/{bulk_sms_uid}')


sendchamp = SendchampClient()

# Default sender IDs available without approval — confirmed live against
# this account on 2026-09-05.
DEFAULT_SENDER_IDS = ('Sendchamp', 'SAlert', 'SC-OTP')
