"""
Vercel Python entry point. @vercel/python auto-detects a WSGI `app` and
wraps it as a serverless function.

Vercel has no release-phase hook like Heroku, and this sandbox's own
network can't reach Neon directly to run migrations ahead of time — but
the deployed function's runtime *does* have normal outbound network
access. So migrations run here, once per cold start (Vercel reuses warm
containers across requests, and `migrate` is idempotent/safe to re-run),
instead of as a separate deploy step.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

try:
    call_command('migrate', interactive=False, verbosity=0)
except Exception as exc:  # pragma: no cover
    # Don't crash the whole function if migration fails (e.g. transient
    # connection issue on cold start) — surface it in Vercel's logs and
    # let requests fail naturally instead of the import itself blowing up.
    print(f'[startup migrate failed] {exc}', file=sys.stderr)

from config.wsgi import application as app  # noqa: E402,F401
