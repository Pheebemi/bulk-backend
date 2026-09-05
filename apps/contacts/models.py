from django.conf import settings
from django.db import models


class ContactGroup(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contact_groups')
    name = models.CharField(max_length=100)
    # Synced lazily on first send — see integrations.termii and campaigns.views.
    termii_phonebook_id = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Contact(models.Model):
    group = models.ForeignKey(ContactGroup, on_delete=models.CASCADE, related_name='contacts')
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    phone_number = models.CharField(max_length=15)

    def __str__(self):
        return f'{self.first_name} {self.last_name} ({self.phone_number})'
