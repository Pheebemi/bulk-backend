"""Server-rendered (Django template) views — the session-based
replacement for the old Next.js SPA's login/signup pages. Kept separate
from views.py (the DRF API, still used by nothing right now but left in
place rather than deleted speculatively)."""

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from apps.campaigns.models import Campaign

from .forms import EmailLoginForm, SignupForm
from .utils import check_verification_code, claim_welcome_bonus, resend_wait_seconds, send_verification_code
from .web_utils import customer_required
import logging

from django.conf import settings
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('web-dashboard')
    form = EmailLoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        user = form.cleaned_data['user']
        auth_login(request, user)
        if settings.EMAIL_VERIFICATION_REQUIRED and not user.email_verified and not user.is_staff:
            # Unverified: send a fresh code (unless one went out in the last
            # minute) and take them straight to the code entry page.
            if resend_wait_seconds(user) == 0:
                try:
                    send_verification_code(user)
                    messages.info(request, f'Verify your email to continue — we sent a new code to {user.email}.')
                except Exception:
                    logger.exception('Verification email failed at login (%s)', user.email)
                    messages.error(request, "We couldn't send your code just now — tap Resend below.")
            else:
                messages.info(request, 'Verify your email to continue — enter the code we just sent.')
            return redirect('web-verify-email')
        messages.success(request, 'Welcome back.')
        return redirect('web-dashboard')
    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('web-dashboard')
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        auth_login(request, user)
        messages.success(request, f'Welcome to ReachlySMS, {user.full_name or "there"}.')
        if settings.EMAIL_VERIFICATION_REQUIRED:
            try:
                send_verification_code(user)
            except Exception:
                logger.exception('Verification email failed at signup (%s)', user.email)
                messages.error(request, "We couldn't send your code just now — tap Resend on the next page.")
            return redirect('web-verify-email')
        return redirect('web-dashboard')
    return render(request, 'accounts/signup.html', {'form': form})


@login_required(login_url='web-login')
def logout_view(request):
    auth_logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('web-login')


@customer_required
def dashboard_view(request):
    user_campaigns = Campaign.objects.filter(user=request.user, is_admin_campaign=False)
    recent = user_campaigns.order_by('-created_at')[:5]
    recipients_reached = user_campaigns.aggregate(total=Sum('total_recipients'))['total'] or 0
    context = {
        'balance': request.user.wallet.balance,
        'campaigns_sent': user_campaigns.count(),
        'recipients_reached': recipients_reached,
        'recent_campaigns': recent,
        'bonus_amount': settings.SIGNUP_BONUS_NGN,
        'can_claim_bonus': settings.SIGNUP_BONUS_NGN > 0 and not request.user.wallet.welcome_bonus_claimed,
    }
    return render(request, 'accounts/dashboard.html', context)


@customer_required
@require_POST
def claim_bonus_view(request):
    if claim_welcome_bonus(request.user):
        messages.success(request, f'₦{settings.SIGNUP_BONUS_NGN} welcome bonus added to your wallet.')
    else:
        messages.info(request, 'Your welcome bonus has already been claimed.')
    return redirect('web-dashboard')


@login_required(login_url='web-login')
def verify_email_view(request):
    if request.user.email_verified or not settings.EMAIL_VERIFICATION_REQUIRED:
        return redirect('web-dashboard')
    if request.method == 'POST':
        ok, error = check_verification_code(request.user, request.POST.get('code', ''))
        if ok:
            messages.success(request, 'Email verified. Welcome aboard!')
            return redirect('web-dashboard')
        messages.error(request, error)
        return redirect('web-verify-email')
    return render(request, 'accounts/verify_email.html', {'wait': resend_wait_seconds(request.user)})


@login_required(login_url='web-login')
@require_POST
def resend_code_view(request):
    wait = resend_wait_seconds(request.user)
    if wait:
        messages.info(request, f'Please wait {wait}s before requesting another code.')
    else:
        try:
            send_verification_code(request.user)
            messages.success(request, f'A new code was sent to {request.user.email}.')
        except Exception:
            logger.exception('Verification email failed on resend (%s)', request.user.email)
            messages.error(request, "We couldn't send the code right now. Please try again shortly.")
    return redirect('web-verify-email')
