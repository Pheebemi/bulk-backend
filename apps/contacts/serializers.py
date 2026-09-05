from rest_framework import serializers

from .models import Contact, ContactGroup


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ['id', 'first_name', 'last_name', 'phone_number']


class ContactGroupSerializer(serializers.ModelSerializer):
    contacts = ContactSerializer(many=True, read_only=True)
    contact_count = serializers.SerializerMethodField()

    class Meta:
        model = ContactGroup
        fields = ['id', 'name', 'termii_phonebook_id', 'created_at', 'contacts', 'contact_count']
        read_only_fields = ['termii_phonebook_id', 'created_at']

    def get_contact_count(self, obj):
        return obj.contacts.count()
