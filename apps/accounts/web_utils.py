"""Lets the server-rendered views reuse the DRF views' business logic
(wallet reserve/refund, provider routing, batching) instead of
duplicating it: build a synthetic API request authenticated as the
session user and call the view directly."""

from rest_framework.test import APIRequestFactory, force_authenticate

_factory = APIRequestFactory()


def call_api(view_class, user, method='post', data=None, **view_kwargs):
    """Returns (status_code, data) from invoking `view_class` as `user`."""
    request = getattr(_factory, method)('/', data or {}, format='json')
    force_authenticate(request, user=user)
    response = view_class.as_view()(request, **view_kwargs)
    return response.status_code, response.data


def error_text(data):
    """Flattens a DRF error payload into one human-readable string."""
    if isinstance(data, dict):
        if 'detail' in data:
            return str(data['detail'])
        return ' '.join(f"{', '.join(map(str, v)) if isinstance(v, list) else v}" for v in data.values())
    return str(data)


def staff_required(view):
    """Console pages: must be logged in AND is_staff, else the console login."""
    from functools import wraps

    from django.shortcuts import redirect

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_staff):
            return redirect('console-login')
        return view(request, *args, **kwargs)

    return wrapper
