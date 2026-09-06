import csv
import io

from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.pagination import StandardResultsPagination

from .models import Contact, ContactGroup
from .serializers import ContactGroupSerializer, ContactSerializer


class ContactGroupListCreateView(generics.ListCreateAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # No longer prefetches contacts — ContactGroupSerializer doesn't
        # nest them any more (see its own comment), so there's nothing
        # here for a prefetch to save a query on.
        return ContactGroup.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactGroupDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ContactGroup.objects.filter(user=self.request.user)


class ContactListCreateView(generics.ListCreateAPIView):
    """A specific group's contacts, paginated — fetched on demand when
    that group is expanded on the Contacts page, instead of every
    group's entire contact list being embedded on every page load
    regardless of whether it was ever expanded at all."""

    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsPagination

    def get_group(self):
        return generics.get_object_or_404(ContactGroup, id=self.kwargs['group_id'], user=self.request.user)

    def get_queryset(self):
        return Contact.objects.filter(group=self.get_group()).order_by('id')

    def perform_create(self, serializer):
        serializer.save(group=self.get_group())
        # No Termii sync: this database is the sole source of truth for
        # contacts. Numbers are handed to Termii only at send time, as the
        # recipient list of a bulk message — never stored in a phonebook.


class ContactCsvUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        group_name = request.data.get('group_name')
        if not file:
            return Response({'detail': 'file is required'}, status=status.HTTP_400_BAD_REQUEST)

        group = ContactGroup.objects.create(user=request.user, name=group_name or file.name)
        raw_bytes = file.read()
        decoded = io.StringIO(raw_bytes.decode('utf-8', errors='ignore'))
        reader = csv.DictReader(decoded)
        # Accept either explicit columns (phone_number, first_name, last_name)
        # or a single unlabelled phone-number column.
        created = 0
        for row in reader:
            phone = row.get('phone_number') or row.get('phone') or next(iter(row.values()), None)
            if not phone:
                continue
            Contact.objects.create(
                group=group,
                phone_number=phone.strip(),
                first_name=(row.get('first_name') or '').strip(),
                last_name=(row.get('last_name') or '').strip(),
            )
            created += 1

        return Response(ContactGroupSerializer(group).data, status=status.HTTP_201_CREATED)
