from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Campaign, PlatformRate, SenderID, SMSLog

User = get_user_model()


class SenderIDSerializer(serializers.ModelSerializer):
    is_shared = serializers.SerializerMethodField()

    class Meta:
        model = SenderID
        fields = ['id', 'name', 'provider', 'platform_status', 'termii_dnd_whitelisted', 'created_at', 'is_shared']
        read_only_fields = fields
        # use_case and visibility are deliberately excluded — use_case is
        # what Admin reads to decide what to submit on a provider's
        # dashboard, and visibility is collapsed down to the one bit
        # (is_shared) the customer-facing UI actually needs.

    def get_is_shared(self, obj):
        return obj.visibility == 'shared'


class AdminSenderIDSerializer(serializers.ModelSerializer):
    """Full CRUD shape for the admin console: every SenderID row, whoever
    it belongs to (private/shared/admin_only alike), fully editable.

    user_email is read AND write — Admin creates a private row on a
    customer's behalf (or reassigns one) by typing their email directly,
    rather than juggling a separate id field.
    """

    user_email = serializers.SlugRelatedField(
        slug_field='email', source='user', queryset=User.objects.all(), required=False, allow_null=True
    )
    # Declared explicitly (not left to ModelSerializer's auto-generation)
    # so DRF doesn't also attach its own per-field UniqueValidators from
    # the model's single-field conditional constraints — those run before
    # validate() below and would pre-empt it with generic Django wording.
    name = serializers.CharField(max_length=11)
    is_shared = serializers.SerializerMethodField()
    is_admin_only = serializers.SerializerMethodField()

    class Meta:
        model = SenderID
        fields = [
            'id', 'name', 'visibility', 'use_case', 'provider', 'platform_status',
            'termii_dnd_whitelisted', 'created_at', 'user_email', 'is_shared', 'is_admin_only',
        ]
        read_only_fields = ['created_at', 'is_shared', 'is_admin_only']
        # DRF auto-derives validators from the model's UniqueConstraints,
        # but it doesn't understand their `condition=` — it force-requires
        # every field in the composite constraint (making user_email
        # required even for a shared/admin_only row) and checks the
        # single-field ones unconditionally. validate() below already
        # does this correctly, visibility-aware — so drop the automatic
        # ones entirely rather than fight them.
        validators = []

    def get_is_shared(self, obj):
        return obj.visibility == 'shared'

    def get_is_admin_only(self, obj):
        return obj.visibility == 'admin_only'

    def validate_name(self, value):
        return value.strip()

    def validate(self, attrs):
        instance = self.instance
        visibility = attrs.get('visibility', instance.visibility if instance else 'private')
        # 'user' is only in attrs at all if user_email was part of this
        # request — for a partial update that didn't touch it, fall back
        # to whatever the row already has.
        user = attrs['user'] if 'user' in attrs else (instance.user if instance else None)

        if visibility == 'private' and user is None:
            raise serializers.ValidationError({'user_email': 'A private sender ID must belong to a user.'})
        if visibility != 'private' and user is not None:
            raise serializers.ValidationError({'user_email': 'Shared and admin-only sender IDs cannot belong to a user.'})

        name = attrs.get('name', instance.name if instance else None)
        qs = SenderID.objects.all() if instance is None else SenderID.objects.exclude(pk=instance.pk)

        if visibility == 'private':
            if qs.filter(user=user, name=name, visibility='private').exists():
                raise serializers.ValidationError({'name': f'{user.email} already has a sender ID named "{name}".'})
            # A private row sharing a name with a shared/admin_only one
            # would make send-time routing ambiguous (CampaignListCreateView
            # matches by name across visibilities) — block it here instead.
            if qs.filter(name=name, visibility__in=['shared', 'admin_only']).exists():
                raise serializers.ValidationError({'name': f'"{name}" is already used by a shared or admin-only sender ID.'})
        else:
            label = 'shared sender ID' if visibility == 'shared' else 'admin-only sender ID'
            if qs.filter(visibility=visibility, name=name).exists():
                raise serializers.ValidationError({'name': f'"{name}" is already a {label}.'})
            if qs.filter(name=name, visibility='private').exists():
                raise serializers.ValidationError({'name': f'"{name}" is already used as a private sender ID by a customer.'})
        return attrs


class SenderIDRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=11)
    use_case = serializers.CharField()


class SMSLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSLog
        fields = ['id', 'recipient', 'provider_msg_id', 'status', 'sent_at']


class CampaignSerializer(serializers.ModelSerializer):
    """The list shape — every campaign-list endpoint (customer's own,
    admin's own, admin's platform-wide monitor) uses this. Deliberately
    has no per-recipient `logs`: a large campaign can have thousands of
    SMSLog rows, and nothing on any list page reads them — see
    CampaignDetailSerializer below for where that data actually belongs."""

    class Meta:
        model = Campaign
        fields = [
            'id', 'is_admin_campaign', 'provider', 'sender_id', 'message', 'channel',
            'termii_campaign_id', 'total_recipients', 'delivered', 'failed',
            'total_cost', 'termii_cost', 'status', 'created_at',
        ]
        read_only_fields = fields
        # provider_error is deliberately excluded — this serializer is what
        # a customer's own GET /api/campaigns/ and /campaigns/<id>/ return,
        # and that field holds raw provider text ("Sendchamp ... Low
        # balance") that names an internal vendor and isn't theirs to see.
        # AdminCampaignSerializer below is the one that includes it.


class CampaignDetailSerializer(CampaignSerializer):
    """Adds the per-recipient log — only worth the payload size on a
    single campaign's own page (CampaignDetailView), never on a list."""

    logs = SMSLogSerializer(many=True, read_only=True)

    class Meta(CampaignSerializer.Meta):
        fields = CampaignSerializer.Meta.fields + ['logs']
        read_only_fields = fields


class AdminCampaignSerializer(CampaignSerializer):
    """Same shape the customer gets, plus who it belongs to and, when a
    send failed, the real reason — for the admin console's campaign
    monitor, not returned to any customer-facing endpoint."""

    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta(CampaignSerializer.Meta):
        fields = CampaignSerializer.Meta.fields + ['user_email', 'provider_error']
        read_only_fields = fields


class CampaignCreateSerializer(serializers.Serializer):
    sender_id = serializers.CharField(max_length=11)
    message = serializers.CharField()
    channel = serializers.ChoiceField(choices=['generic', 'dnd'])
    group_id = serializers.IntegerField(required=False)
    manual_numbers = serializers.ListField(child=serializers.CharField(), required=False)

    def validate(self, attrs):
        if not attrs.get('group_id') and not attrs.get('manual_numbers'):
            raise serializers.ValidationError('Provide either group_id or manual_numbers.')
        return attrs


class AdminCampaignCreateSerializer(serializers.Serializer):
    sender_id = serializers.CharField(max_length=11)
    message = serializers.CharField()
    channel = serializers.ChoiceField(choices=['generic', 'dnd'])
    manual_numbers = serializers.ListField(child=serializers.CharField(), required=False)
    recipient_count = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if not attrs.get('manual_numbers') and not attrs.get('recipient_count'):
            raise serializers.ValidationError('Provide either manual_numbers or recipient_count.')
        return attrs


class PlatformRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformRate
        fields = ['generic_rate', 'dnd_rate', 'updated_at']
        read_only_fields = ['updated_at']


class WalletAdjustSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(required=False, allow_blank=True)
    direction = serializers.ChoiceField(choices=['credit', 'debit'])
