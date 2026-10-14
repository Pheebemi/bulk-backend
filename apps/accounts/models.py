from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Admin is just a User with is_staff/is_superuser=True — no separate
    login system. Wallets are only ever created for regular (non-staff)
    users; see accounts.views.SignupView.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    # New wallets start unclaimed; the customer taps "Claim" to receive the
    # welcome bonus once (see utils.claim_welcome_bonus).
    welcome_bonus_claimed = models.BooleanField(default=False)
    # True once the low-balance email went out for the current dip below the
    # threshold; cleared when the balance recovers, so each dip emails once.
    low_balance_notified = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.email} — ₦{self.balance}'


class WalletTransaction(models.Model):
    """A simple audit ledger — every balance change writes one row here
    (funding, manual admin adjustment, campaign charge/refund) so the
    admin wallet-management screen has real history to show, not just the
    current balance."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallet_transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # signed: +credit, -debit
    description = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.email}: {self.amount} — {self.description}'


class EmailOTP(models.Model):
    """The current signup/verification code for a user. Only a hash is
    stored; one live code per user, replaced on resend."""

    VALIDITY_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_otp')
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now=True)
