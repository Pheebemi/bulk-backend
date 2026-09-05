from django.urls import path

from .views import ContactCreateView, ContactCsvUploadView, ContactGroupDetailView, ContactGroupListCreateView

urlpatterns = [
    path('contact-groups/', ContactGroupListCreateView.as_view(), name='contact-group-list'),
    path('contact-groups/<int:pk>/', ContactGroupDetailView.as_view(), name='contact-group-detail'),
    path('contact-groups/<int:group_id>/contacts/', ContactCreateView.as_view(), name='contact-create'),
    path('contact-groups/upload-csv/', ContactCsvUploadView.as_view(), name='contact-csv-upload'),
]
