from rest_framework import filters, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.campaigns.permissions import IsAdmin
from config.pagination import StandardResultsPagination

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
    pagination_class = StandardResultsPagination
    # Server-side, not the frontend filtering an already-fetched page —
    # a fetched page is only ever a slice of the whole user table now,
    # so filtering client-side would silently miss every match not on
    # the currently-loaded page. ?search= matches name or email.
    filter_backends = [filters.SearchFilter]
    search_fields = ['full_name', 'email']

    def get_queryset(self):
        return User.objects.filter(is_staff=False).select_related('wallet').prefetch_related('wallet_transactions')
