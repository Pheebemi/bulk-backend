"""
Thin wrapper around the Termii APIs this platform actually uses, grounded
in their real documented request/response shapes (see PROJECT_SPEC.md):

- Messaging (single + bulk, <=100 numbers/call)
- Campaign (phonebook-based, asynchronous on Termii's side)
- Phonebooks + Contacts (syncing our ContactGroup/Contact rows)
- Sender ID (request + fetch status)

TERMII_BASE_URL has moved before (api.termii.com vs api.ng.termii.com) —
confirm it against the current dashboard/docs if calls start 404ing.
"""

from __future__ import annotations

import io
from typing import Iterable

import requests
from django.conf import settings


class TermiiError(Exception):
    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response


class TermiiClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.TERMII_API_KEY
        self.base_url = (base_url or settings.TERMII_BASE_URL).rstrip('/')

    def _url(self, path: str) -> str:
        return f'{self.base_url}{path}'

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = requests.request(method, self._url(path), timeout=30, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise TermiiError(f'Termii {method} {path} unreachable: {exc}') from exc
        if not resp.ok:
            raise TermiiError(f'Termii {method} {path} failed: {resp.status_code} {resp.text}', resp)
        return resp.json()

    # --- Messaging ------------------------------------------------------

    def send_message(self, to: str, sender_id: str, sms: str, channel: str) -> dict:
        return self._request(
            'POST',
            '/api/sms/send',
            json={
                'api_key': self.api_key,
                'to': to,
                'from': sender_id,
                'sms': sms,
                'type': 'plain',
                'channel': channel,
            },
        )

    def send_bulk(self, to: list[str], sender_id: str, sms: str, channel: str) -> dict:
        """`to` must be <=100 numbers — chunk before calling this."""
        if len(to) > 100:
            raise ValueError('Termii bulk send accepts at most 100 numbers per call')
        return self._request(
            'POST',
            '/api/sms/send/bulk',
            json={
                'api_key': self.api_key,
                'to': to,
                'from': sender_id,
                'sms': sms,
                'type': 'plain',
                'channel': channel,
            },
        )

    def send_bulk_chunked(self, to: list[str], sender_id: str, sms: str, channel: str) -> list[dict]:
        """Splits an arbitrary-length manual recipient list into <=100-number
        batches, per the Messaging bulk endpoint's real limit."""
        responses = []
        for i in range(0, len(to), 100):
            batch = to[i : i + 100]
            responses.append(self.send_bulk(batch, sender_id, sms, channel))
        return responses

    # --- Campaign (phonebook-based, async) -------------------------------

    def send_campaign(
        self,
        phonebook_id: str,
        sender_id: str,
        message: str,
        channel: str,
        country_code: str = '234',
    ) -> dict:
        return self._request(
            'POST',
            '/api/sms/campaigns/send',
            json={
                'api_key': self.api_key,
                'country_code': country_code,
                'sender_id': sender_id,
                'message': message,
                'channel': channel,
                'message_type': 'plain',
                'phonebook_id': phonebook_id,
                'campaign_type': 'regular',
                'schedule_sms_status': 'regular',
            },
        )

    def fetch_campaign_history(self, campaign_id: str) -> dict:
        return self._request('GET', f'/api/sms/campaigns/{campaign_id}', params={'api_key': self.api_key})

    def retry_campaign(self, campaign_id: str) -> dict:
        return self._request('PATCH', f'/api/sms/campaigns/{campaign_id}', json={'api_key': self.api_key})

    # --- Phonebooks -------------------------------------------------------

    def fetch_phonebooks(self) -> dict:
        return self._request('GET', '/api/phonebooks', params={'api_key': self.api_key})

    def create_phonebook(self, name: str, description: str = '') -> dict:
        # Response has no id — caller must follow up with fetch_phonebooks().
        return self._request(
            'POST',
            '/api/phonebooks',
            json={'api_key': self.api_key, 'phonebook_name': name, 'description': description},
        )

    def find_phonebook_id_by_name(self, name: str) -> str | None:
        data = self.fetch_phonebooks()
        for pb in data.get('content', []):
            if pb.get('name') == name:
                return pb.get('id')
        return None

    # --- Contacts ----------------------------------------------------------

    def add_contact(self, phonebook_id: str, phone_number: str, country_code: str = '234', **extra) -> dict:
        return self._request(
            'POST',
            f'/api/phonebooks/{phonebook_id}/contacts',
            json={'api_key': self.api_key, 'phone_number': phone_number, 'country_code': country_code, **extra},
        )

    def upload_contacts_csv(self, phonebook_id: str, csv_bytes: bytes, filename: str, country_code: str = '234') -> dict:
        """Asynchronous on Termii's side — response just confirms it queued."""
        return self._request(
            'POST',
            '/api/phonebooks/contacts/upload',
            files={'file': (filename, io.BytesIO(csv_bytes), 'text/csv')},
            data={'contact': f'{{"pid": "{phonebook_id}", "country_code": "{country_code}", "api_key": "{self.api_key}"}}'},
        )

    # --- Sender ID -----------------------------------------------------------

    def fetch_sender_ids(self) -> dict:
        return self._request('GET', '/api/sender-id', params={'api_key': self.api_key})

    def request_sender_id(self, sender_id: str, use_case: str, company: str) -> dict:
        return self._request(
            'POST',
            '/api/sender-id/request',
            json={'api_key': self.api_key, 'sender_id': sender_id, 'use_case': use_case, 'company': company},
        )


termii = TermiiClient()


# --- Higher-level helpers used by other apps --------------------------------


def ensure_phonebook(group) -> str:
    """Creates (and saves) group.termii_phonebook_id if it doesn't exist yet.

    Locks the group row for the duration of the check+create+save so two
    concurrent callers (e.g. a CSV upload and a single contact add landing
    at the same moment) can't both see an empty termii_phonebook_id and
    each create a duplicate remote phonebook — the second caller blocks
    until the first commits, then sees the id already set and skips
    creating anything."""
    from django.db import transaction

    from apps.contacts.models import ContactGroup

    with transaction.atomic():
        locked_group = ContactGroup.objects.select_for_update().get(pk=group.pk)
        if locked_group.termii_phonebook_id:
            group.termii_phonebook_id = locked_group.termii_phonebook_id
            return locked_group.termii_phonebook_id

        termii.create_phonebook(name=locked_group.name)
        phonebook_id = termii.find_phonebook_id_by_name(locked_group.name)
        if not phonebook_id:
            raise TermiiError(f'Created phonebook "{locked_group.name}" but could not find its id afterwards')
        locked_group.termii_phonebook_id = phonebook_id
        locked_group.save(update_fields=['termii_phonebook_id'])
        group.termii_phonebook_id = phonebook_id
        return phonebook_id


def sync_group_to_phonebook(group) -> str:
    """First-time sync: create the phonebook (if needed) and push every
    contact currently in the group. Safe to call again — it only creates
    the phonebook once (ensure_phonebook is idempotent); re-adding the same
    contacts is a Termii-side no-op/duplicate concern we accept for now."""
    phonebook_id = ensure_phonebook(group)
    for contact in group.contacts.all():
        termii.add_contact(
            phonebook_id,
            contact.phone_number,
            first_name=contact.first_name,
            last_name=contact.last_name,
        )
    return phonebook_id


def push_single_contact(group, contact) -> str:
    """Ensures the phonebook exists, then pushes just this one contact —
    used when a single contact is added to an already-synced group."""
    phonebook_id = ensure_phonebook(group)
    termii.add_contact(
        phonebook_id,
        contact.phone_number,
        first_name=contact.first_name,
        last_name=contact.last_name,
    )
    return phonebook_id


def sync_group_via_csv(group, csv_bytes: bytes, filename: str) -> str:
    """Used right after a CSV upload — forwards the same file to Termii's
    bulk contact-upload endpoint instead of looping single-adds."""
    phonebook_id = ensure_phonebook(group)
    termii.upload_contacts_csv(phonebook_id, csv_bytes, filename)
    return phonebook_id
