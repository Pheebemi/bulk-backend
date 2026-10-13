from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import include, path


def health(request):
    """Proves the deployed function can actually reach the database and
    that migrations have run — not just that the app booted."""
    User = get_user_model()
    try:
        user_count = User.objects.count()
        return JsonResponse({'status': 'ok', 'database': 'connected', 'user_count': user_count})
    except Exception as exc:
        return JsonResponse({'status': 'error', 'database': 'unreachable', 'detail': str(exc)}, status=500)


def home(request):
    from django.shortcuts import render

    from apps.accounts import landing_content as c
    from apps.campaigns.models import PlatformRate

    # Live selling rates on the pricing cards; fall back to the model
    # defaults if the database is unreachable so the landing never 500s.
    try:
        rate = PlatformRate.current()
        generic_rate, dnd_rate = rate.generic_rate, rate.dnd_rate
    except Exception:
        generic_rate, dnd_rate = '8.00', '10.00'

    return render(request, 'landing.html', {
        'use_cases': c.USE_CASES, 'industries': c.INDUSTRIES, 'features': c.FEATURES,
        'faqs': c.FAQS, 'checklist': c.CHECKLIST,
        'generic_rate': generic_rate, 'dnd_rate': dnd_rate,
        'stats': [('4', 'Networks covered'), ('DND', 'Route included'), ('160', 'Characters / segment'), ('₦0', 'Monthly fee')],
        'steps': [
            ('1', 'Create & fund', 'Sign up in a minute and top up your wallet by card or transfer — no subscription.', 'illustrations/wallet.svg'),
            ('2', 'Add your contacts', 'Upload a CSV or add numbers by hand, grouped the way you actually message.', 'illustrations/contacts.svg'),
            ('3', 'Send & track', 'See the exact cost first, send, then watch delivery per recipient.', 'illustrations/reports.svg'),
        ],
    })


urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('api/health/', health, name='health'),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/', include('apps.contacts.urls')),
    path('api/', include('apps.campaigns.urls')),
    path('api/', include('apps.payments.urls')),
    # Server-rendered pages — the session-based replacement for the old
    # Next.js SPA (bulk-frontend). Deliberately not under /api/.
    path('', include('apps.accounts.urls_web')),
    path('', include('apps.campaigns.urls_web')),
    path('', include('apps.contacts.urls_web')),
    path('', include('apps.payments.urls_web')),
    path('', include('apps.campaigns.urls_console')),
]
