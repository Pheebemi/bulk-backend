from django.urls import path

from . import views_web

urlpatterns = [
    path('campaigns/', views_web.campaign_list, name='web-campaigns'),
    path('campaigns/new/', views_web.campaign_new, name='web-campaign-new'),
    path('campaigns/<int:pk>/', views_web.campaign_detail, name='web-campaign-detail'),
    path('campaigns/<int:pk>/cancel/', views_web.campaign_cancel, name='web-campaign-cancel'),
    path('templates/', views_web.template_list, name='web-templates'),
    path('sender-ids/', views_web.sender_ids, name='web-sender-ids'),
]
