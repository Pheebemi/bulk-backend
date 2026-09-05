from django.contrib import admin

from .models import Campaign, PlatformRate, SenderID, SMSLog


@admin.register(SenderID)
class SenderIDAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'provider', 'platform_status', 'termii_dnd_whitelisted', 'created_at']
    list_filter = ['provider', 'platform_status', 'termii_dnd_whitelisted']
    search_fields = ['name', 'user__email']


class SMSLogInline(admin.TabularInline):
    model = SMSLog
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['sender_id', 'user', 'provider', 'channel', 'status', 'total_recipients', 'total_cost', 'termii_cost', 'created_at']
    list_filter = ['status', 'channel', 'provider', 'is_admin_campaign']
    # provider_error lets a FAILED/PARTIAL campaign's real cause (e.g. a
    # provider account being out of balance) turn up by searching "balance"
    # here, instead of digging through Vercel logs.
    search_fields = ['sender_id', 'user__email', 'message', 'provider_error']
    readonly_fields = ['provider_error']
    inlines = [SMSLogInline]


@admin.register(PlatformRate)
class PlatformRateAdmin(admin.ModelAdmin):
    list_display = ['generic_rate', 'dnd_rate', 'updated_at']
