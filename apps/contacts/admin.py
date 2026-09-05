from django.contrib import admin

from .models import Contact, ContactGroup


class ContactInline(admin.TabularInline):
    model = Contact
    extra = 0


@admin.register(ContactGroup)
class ContactGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'termii_phonebook_id', 'created_at']
    search_fields = ['name', 'user__email']
    inlines = [ContactInline]


admin.site.register(Contact)
