from rest_framework import serializers

from .models import Campaign, PlatformRate, SenderID, SMSLog


class SenderIDSerializer(serializers.ModelSerializer):
    # Always False here — real DB rows are a user's own requested sender
    # IDs. The shared, no-approval-needed ones are synthetic entries
    # SenderIDListCreateView.list() adds alongside these, not stored rows.
    is_shared = serializers.SerializerMethodField()

    class Meta:
        model = SenderID
        fields = ['id', 'name', 'provider', 'platform_status', 'termii_dnd_whitelisted', 'created_at', 'is_shared']
        read_only_fields = ['provider', 'platform_status', 'termii_dnd_whitelisted', 'created_at', 'is_shared']

    def get_is_shared(self, obj):
        return False


class AdminSenderIDSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    # Always False here — same reasoning as SenderIDSerializer.is_shared.
    is_shared = serializers.SerializerMethodField()

    class Meta:
        model = SenderID
        fields = ['id', 'name', 'provider', 'platform_status', 'termii_dnd_whitelisted', 'created_at', 'user_email', 'is_shared']
        # provider and platform_status are writable here on purpose —
        # AdminSenderIDDetailView.patch is where Admin manually approves a
        # sendchamp/kudisms request, since those providers have no status
        # API to sync from automatically.
        read_only_fields = ['created_at', 'user_email', 'is_shared']

    def get_is_shared(self, obj):
        return False


class SenderIDRequestSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=11)
    use_case = serializers.CharField()


class SMSLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSLog
        fields = ['id', 'recipient', 'provider_msg_id', 'status', 'sent_at']


class CampaignSerializer(serializers.ModelSerializer):
    logs = SMSLogSerializer(many=True, read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'is_admin_campaign', 'provider', 'sender_id', 'message', 'channel',
            'termii_campaign_id', 'total_recipients', 'delivered', 'failed',
            'total_cost', 'termii_cost', 'status', 'created_at', 'logs',
        ]
        read_only_fields = [f for f in fields if f not in ()]
        # provider_error is deliberately excluded — this serializer is what
        # a customer's own GET /api/campaigns/ and /campaigns/<id>/ return,
        # and that field holds raw provider text ("Sendchamp ... Low
        # balance") that names an internal vendor and isn't theirs to see.
        # AdminCampaignSerializer below is the one that includes it.


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
