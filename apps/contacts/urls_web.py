from django.urls import path

from . import views_web as v

urlpatterns = [
    path('contacts/', v.contacts_home, {'scope': 'user'}, name='web-contacts'),
    path('contacts/<int:pk>/', v.group_detail, {'scope': 'user'}, name='web-contact-group'),
    path('contacts/<int:pk>/delete/', v.group_delete, {'scope': 'user'}, name='web-contact-group-delete'),
    path('contacts/<int:group_pk>/<int:pk>/edit/', v.contact_edit, {'scope': 'user'}, name='web-contact-edit'),
    path('contacts/<int:group_pk>/<int:pk>/delete/', v.contact_delete, {'scope': 'user'}, name='web-contact-delete'),
    path('console/contacts/', v.contacts_home, {'scope': 'console'}, name='console-contacts'),
    path('console/contacts/<int:pk>/', v.group_detail, {'scope': 'console'}, name='console-contact-group'),
    path('console/contacts/<int:pk>/delete/', v.group_delete, {'scope': 'console'}, name='console-contact-group-delete'),
    path('console/contacts/<int:group_pk>/<int:pk>/edit/', v.contact_edit, {'scope': 'console'}, name='console-contact-edit'),
    path('console/contacts/<int:group_pk>/<int:pk>/delete/', v.contact_delete, {'scope': 'console'}, name='console-contact-delete'),
]
