from django.db.models import Sum
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User, Wallet, WalletTransaction


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'password', 'full_name', 'phone_number']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        Wallet.objects.create(user=user)
        return user


class UserSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    # Real aggregates, computed server-side — the dashboard's "Campaigns
    # sent" / "Recipients reached" stat cards used to just count/sum
    # whatever page of GET /api/campaigns/ happened to be loaded, which
    # was only ever correct by accident (it fetched all of them). Now
    # that campaigns list is paginated, those need a real total instead.
    campaigns_sent = serializers.SerializerMethodField()
    recipients_reached = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'phone_number', 'is_staff', 'balance', 'campaigns_sent', 'recipients_reached']

    def get_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        return str(wallet.balance) if wallet else None

    def get_campaigns_sent(self, obj):
        return obj.campaigns.filter(is_admin_campaign=False).count()

    def get_recipients_reached(self, obj):
        return obj.campaigns.filter(is_admin_campaign=False).aggregate(total=Sum('total_recipients'))['total'] or 0


class LoginSerializer(TokenObtainPairSerializer):
    """Reshapes SimpleJWT's {access, refresh} into {token, refresh, user}
    to match the frontend's lib/api.ts contract."""

    def validate(self, attrs):
        data = super().validate(attrs)
        return {
            'token': data['access'],
            'refresh': data['refresh'],
            'user': UserSerializer(self.user).data,
        }


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ['id', 'amount', 'description', 'created_at']


class AdminUserSerializer(serializers.ModelSerializer):
    """Used by the admin wallet-management screen — includes balance and
    recent transaction history, unlike the plain UserSerializer."""

    balance = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'phone_number', 'balance', 'history']

    def get_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        return str(wallet.balance) if wallet else '0.00'

    def get_history(self, obj):
        qs = obj.wallet_transactions.all()[:20]
        return WalletTransactionSerializer(qs, many=True).data
