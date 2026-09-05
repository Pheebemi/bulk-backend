from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import JsonResponse
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


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health, name='health'),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/', include('apps.contacts.urls')),
    path('api/', include('apps.campaigns.urls')),
    path('api/', include('apps.payments.urls')),
]
