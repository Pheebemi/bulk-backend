from django.urls import path

from .views import (
    AdminContactCsvUploadView,
    AdminContactGroupDetailView,
    AdminContactGroupListCreateView,
    AdminContactListCreateView,
    ContactCsvUploadView,
    ContactGroupDetailView,
    ContactGroupListCreateView,
    ContactListCreateView,
)

urlpatterns = [
    path('contact-groups/', ContactGroupListCreateView.as_view(), name='contact-group-list'),
    path('contact-groups/<int:pk>/', ContactGroupDetailView.as_view(), name='contact-group-detail'),
    path('contact-groups/<int:group_id>/contacts/', ContactListCreateView.as_view(), name='contact-list-create'),
    path('contact-groups/upload-csv/', ContactCsvUploadView.as_view(), name='contact-csv-upload'),
    # Admin — its own, separate contact groups (see views.py for why).
    path('admin/contact-groups/', AdminContactGroupListCreateView.as_view(), name='admin-contact-group-list'),
    path('admin/contact-groups/<int:pk>/', AdminContactGroupDetailView.as_view(), name='admin-contact-group-detail'),
    path(
        'admin/contact-groups/<int:group_id>/contacts/',
        AdminContactListCreateView.as_view(),
        name='admin-contact-list-create',
    ),
    path('admin/contact-groups/upload-csv/', AdminContactCsvUploadView.as_view(), name='admin-contact-csv-upload'),
]
