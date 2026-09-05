from django.db import migrations

# Moving the shared/admin-only sender ID pools from hardcoded Python tuples
# (integrations.sendchamp.DEFAULT_SENDER_IDS, integrations.kudisms.
# DEFAULT_SENDER_IDS / ADMIN_ONLY_SENDER_IDS) to real, admin-editable rows.
# Seeded here so existing behavior doesn't regress the moment this ships —
# every name below was already confirmed live against its provider earlier
# this session; going forward these are managed from the admin console
# instead of a code change + deploy.
SEED = [
    # name, provider, visibility
    ('Sendchamp', 'sendchamp', 'shared'),
    ('SAlert', 'sendchamp', 'shared'),
    ('SC-OTP', 'sendchamp', 'shared'),
    ('algaddafhub', 'kudisms', 'shared'),
    ('AT-HUB', 'kudisms', 'shared'),
    ('Darrang', 'kudisms', 'shared'),
    ('DAK', 'kudisms', 'admin_only'),
    ('phee-dev', 'kudisms', 'admin_only'),
]


def seed(apps, schema_editor):
    SenderID = apps.get_model('campaigns', 'SenderID')
    for name, provider, visibility in SEED:
        SenderID.objects.get_or_create(
            user=None,
            name=name,
            defaults={'provider': provider, 'visibility': visibility, 'platform_status': 'active', 'termii_dnd_whitelisted': True},
        )


def unseed(apps, schema_editor):
    SenderID = apps.get_model('campaigns', 'SenderID')
    SenderID.objects.filter(user=None, name__in=[name for name, _, _ in SEED]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0008_alter_senderid_unique_together_senderid_visibility_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
