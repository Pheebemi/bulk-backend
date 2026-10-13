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
    return redirect('web-dashboard' if request.user.is_authenticated else 'web-login')


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
