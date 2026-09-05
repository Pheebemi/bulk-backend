from rest_framework import serializers

from .models import Campaign, PlatformRate, SenderID, SMSLog


class SenderIDSerializer(serializers.ModelSerializer):
    class Meta:
        model = SenderID
        fields = ['id', 'name', 'platform_status', 'termii_dnd_whitelisted', 'created_at']
        read_only_fields = ['platform_status', 'termii_dnd_whitelisted', 'created_at']


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
            'id', 'is_admin_campaign', 'sender_id', 'message', 'channel',
            'termii_campaign_id', 'total_recipients', 'delivered', 'failed',
            'total_cost', 'termii_cost', 'status', 'created_at', 'logs',
        ]
        read_only_fields = [f for f in fields if f not in ()]


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
