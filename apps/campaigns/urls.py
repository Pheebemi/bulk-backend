from django.urls import path

from apps.accounts.views import AdminUserListView

from .views import (
    AdminCampaignListCreateView,
    AdminPlatformRateView,
    AdminSenderIDDetailView,
    AdminSenderIDListView,
    AdminWalletAdjustView,
    CampaignDetailView,
    CampaignListCreateView,
    CampaignRetryView,
    RateView,
    SenderIDListCreateView,
)

urlpatterns = [
    # User-facing
    path('rate/', RateView.as_view(), name='rate'),
    path('sender-ids/', SenderIDListCreateView.as_view(), name='sender-id-list'),
    path('campaigns/', CampaignListCreateView.as_view(), name='campaign-list'),
    path('campaigns/<int:pk>/', CampaignDetailView.as_view(), name='campaign-detail'),
    path('campaigns/<int:campaign_id>/retry/', CampaignRetryView.as_view(), name='campaign-retry'),
    # Admin
    path('admin/sender-ids/', AdminSenderIDListView.as_view(), name='admin-sender-id-list'),
    path('admin/sender-ids/<int:pk>/', AdminSenderIDDetailView.as_view(), name='admin-sender-id-detail'),
    path('admin/rate/', AdminPlatformRateView.as_view(), name='admin-rate'),
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/<int:user_id>/wallet/', AdminWalletAdjustView.as_view(), name='admin-wallet-adjust'),
    path('admin/campaigns/', AdminCampaignListCreateView.as_view(), name='admin-campaign-list'),
]
