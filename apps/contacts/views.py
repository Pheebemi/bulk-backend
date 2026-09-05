import csv
import io

from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Contact, ContactGroup
from .serializers import ContactGroupSerializer, ContactSerializer


class ContactGroupListCreateView(generics.ListCreateAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ContactGroup.objects.filter(user=self.request.user).prefetch_related('contacts')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactGroupDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ContactGroup.objects.filter(user=self.request.user)


class ContactCreateView(generics.CreateAPIView):
    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        group = generics.get_object_or_404(
            ContactGroup, id=self.kwargs['group_id'], user=self.request.user
        )
        contact = serializer.save(group=group)
        # Best-effort sync so the group's Termii phonebook stays current.
        # Failures here don't block the contact being saved locally — the
        # phonebook sync is retried the next time a campaign is sent to
        # this group (see campaigns.views.CampaignCreateView).
        try:
            from integrations.termii import push_single_contact

            push_single_contact(group, contact)
        except Exception:
            pass


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

        try:
            from integrations.termii import sync_group_via_csv

            sync_group_via_csv(group, raw_bytes, file.name)
        except Exception:
            pass

        return Response(ContactGroupSerializer(group).data, status=status.HTTP_201_CREATED)
