"""Server-rendered (Django template) views — the session-based
replacement for the old Next.js SPA's login/signup pages. Kept separate
from views.py (the DRF API, still used by nothing right now but left in
place rather than deleted speculatively)."""

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from apps.campaigns.models import Campaign

from .forms import EmailLoginForm, SignupForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect('web-dashboard')
    form = EmailLoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        auth_login(request, form.cleaned_data['user'])
        return redirect('web-dashboard')
    return render(request, 'accounts/login.html', {'form': form})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('web-dashboard')
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        auth_login(request, user)
        return redirect('web-dashboard')
    return render(request, 'accounts/signup.html', {'form': form})


@login_required(login_url='web-login')
def logout_view(request):
    auth_logout(request)
    return redirect('web-login')


@login_required(login_url='web-login')
def dashboard_view(request):
    user_campaigns = Campaign.objects.filter(user=request.user, is_admin_campaign=False)
    recent = user_campaigns.order_by('-created_at')[:5]
    recipients_reached = user_campaigns.aggregate(total=Sum('total_recipients'))['total'] or 0
    context = {
        'balance': request.user.wallet.balance,
        'campaigns_sent': user_campaigns.count(),
        'recipients_reached': recipients_reached,
        'recent_campaigns': recent,
    }
    return render(request, 'accounts/dashboard.html', context)
