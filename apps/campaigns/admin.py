from django.contrib import admin

from .models import Campaign, PlatformRate, SenderID, SMSLog


@admin.register(SenderID)
class SenderIDAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'platform_status', 'termii_dnd_whitelisted', 'created_at']
    list_filter = ['platform_status', 'termii_dnd_whitelisted']
    search_fields = ['name', 'user__email']


class SMSLogInline(admin.TabularInline):
    model = SMSLog
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['sender_id', 'user', 'channel', 'status', 'total_recipients', 'total_cost', 'termii_cost', 'created_at']
    list_filter = ['status', 'channel', 'is_admin_campaign']
    search_fields = ['sender_id', 'user__email', 'message']
    inlines = [SMSLogInline]


@admin.register(PlatformRate)
class PlatformRateAdmin(admin.ModelAdmin):
    list_display = ['generic_rate', 'dnd_rate', 'updated_at']
