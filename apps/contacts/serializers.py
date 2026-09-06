from rest_framework import serializers

from .models import Contact, ContactGroup


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ['id', 'first_name', 'last_name', 'phone_number']


class ContactGroupSerializer(serializers.ModelSerializer):
    # No nested `contacts` here on purpose — a group's contact list is
    # unbounded by design (that's the whole point of a bulk-SMS group)
    # and this serializer backs the group list, which used to embed
    # every contact in every group on every page load regardless of
    # whether that group was even expanded. GET
    # /api/contact-groups/<id>/contacts/ (paginated) is how a specific
    # group's contacts are actually fetched now, on demand.
    contact_count = serializers.SerializerMethodField()

    class Meta:
        model = ContactGroup
        fields = ['id', 'name', 'termii_phonebook_id', 'created_at', 'contact_count']
        read_only_fields = ['termii_phonebook_id', 'created_at']

    def get_contact_count(self, obj):
        return obj.contacts.count()
