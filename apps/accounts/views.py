from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.campaigns.permissions import IsAdmin

from .models import User
from .serializers import AdminUserSerializer, SignupSerializer, UserSerializer


class SignupView(generics.CreateAPIView):
    """Public signup — always creates a regular (non-staff) user + wallet."""

    queryset = User.objects.all()
    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data,
            },
            status=201,
        )


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class AdminUserListView(generics.ListAPIView):
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        return User.objects.filter(is_staff=False).select_related('wallet').prefetch_related('wallet_transactions')
