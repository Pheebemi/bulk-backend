from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('DJANGO_SECRET_KEY', default='dev-only-insecure-key-change-me')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,.vercel.app,reachly.pheedev.online', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'apps.accounts',
    'apps.contacts',
    'apps.campaigns',
    'apps.payments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.nav',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Neon (Postgres) via a single connection string; falls back to local sqlite
# for quick local checks when DATABASE_URL isn't set.
DATABASE_URL = config('DATABASE_URL', default='')
if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=True)}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# Compiled Tailwind CSS + hand-drawn illustrations live here, committed
# (same as the admin's own static output) since Vercel's Python builder
# has no build step to run collectstatic for us.
_static_dir = BASE_DIR / 'static'
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []
# collectstatic writes here; the directory is committed so the Vercel
# function has the admin's CSS/JS available at runtime (Vercel's Python
# builder has no build step to run collectstatic for us).
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    # Compressed, but deliberately NOT the manifest variant: a manifest
    # miss raises at request time, and an unstyled admin beats a 500.
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='http://localhost:3000', cast=Csv())

# --- Third-party integrations -------------------------------------------------
TERMII_API_KEY = config('TERMII_API_KEY', default='')
TERMII_BASE_URL = config('TERMII_BASE_URL', default='https://api.ng.termii.com')

FLUTTERWAVE_SECRET_KEY = config('FLUTTERWAVE_SECRET_KEY', default='')
FLUTTERWAVE_PUBLIC_KEY = config('FLUTTERWAVE_PUBLIC_KEY', default='')
FLUTTERWAVE_BASE_URL = config('FLUTTERWAVE_BASE_URL', default='https://api.flutterwave.com/v3')
# Set the same value as your Flutterwave dashboard's webhook "secret hash"
FLUTTERWAVE_WEBHOOK_HASH = config('FLUTTERWAVE_WEBHOOK_HASH', default='')

# Sendchamp — secondary SMS provider. Ships with default sender IDs
# (Sendchamp, SAlert, SC-OTP) usable immediately, unlike Termii's, which
# need 1-2 days of network approval. Useful as a fallback while a
# customer's own sender ID is still pending.
SENDCHAMP_API_KEY = config('SENDCHAMP_API_KEY', default='')
SENDCHAMP_BASE_URL = config('SENDCHAMP_BASE_URL', default='https://api.sendchamp.com/api/v1')

# KudiSMS — third SMS provider, shared/instant sender ID (Darra), confirmed
# live against this account: real balance, and the send endpoint validates
# the sender ID before the recipient — Darra passes it cleanly.
KUDISMS_API_KEY = config('KUDISMS_API_KEY', default='')
KUDISMS_BASE_URL = config('KUDISMS_BASE_URL', default='https://my.kudisms.net')

# Shared secret an external scheduler (not Vercel's own Cron — Hobby caps
# that at once/day, too infrequent for this) presents on every call to
# POST /api/cron/process-campaigns/, checked as a Bearer token. Set to a
# long random value in production; a blank default means the endpoint
# rejects every call rather than silently allowing an unauthenticated one.
CRON_SECRET = config('CRON_SECRET', default='')

# The server-rendered pages post forms same-origin behind Vercel's proxy.
# Without this Django sees plain http, and its CSRF Origin check (the
# browser sends an https Origin) would reject every login/form POST.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='https://*.vercel.app,https://reachly.pheedev.online', cast=Csv())
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
LOGIN_URL = 'web-login'

# The single SMS provider every new send goes through, regardless of the
# provider recorded on a Sender ID row. Termii and Sendchamp are no longer
# used; their client code stays so this can be flipped back by env var.
SMS_PROVIDER = config('SMS_PROVIDER', default='kudisms')

# Free credit every new customer starts with (₦). Set to 0 to turn it off.
SIGNUP_BONUS_NGN = config('SIGNUP_BONUS_NGN', default=10, cast=int)

# Email (cPanel SMTP) — sends the signup verification code. Unset, mail goes
# to the console and verification is NOT enforced (so nothing locks users out
# before the mailbox is configured).
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_HOST = config('EMAIL_HOST', default='localhost')
EMAIL_PORT = config('EMAIL_PORT', default=465, cast=int)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=True, cast=bool)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)
EMAIL_TIMEOUT = 10
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST_USER else 'django.core.mail.backends.console.EmailBackend',
)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=f'ReachlySMS <{EMAIL_HOST_USER or "reachly@pheedev.online"}>')
EMAIL_VERIFICATION_REQUIRED = config('EMAIL_VERIFICATION_REQUIRED', default=bool(EMAIL_HOST_USER), cast=bool)

# Public base URL used for links in emails.
SITE_URL = config('SITE_URL', default='https://reachly.pheedev.online').rstrip('/')

# Who is emailed when a customer requests a sender ID.
SENDER_ID_ALERT_EMAILS = config(
    'SENDER_ID_ALERT_EMAILS',
    default=f'{EMAIL_HOST_USER or "reachly@pheedev.online"},lemuelemmanuel29@gmail.com',
    cast=Csv(),
)
