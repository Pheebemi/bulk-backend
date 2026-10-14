from decimal import Decimal

from django.db import migrations, models


def backfill(apps, schema_editor):
    """Estimate the provider cost of past customer sends so the profit
    report isn't wildly flattering: delivered x segments x default cost."""
    from apps.campaigns.utils import count_segments

    Campaign = apps.get_model('campaigns', 'Campaign')
    costs = {'generic': Decimal('6.95'), 'dnd': Decimal('5.95')}
    for c in Campaign.objects.filter(is_admin_campaign=False, delivered__gt=0, termii_cost=0).exclude(provider='termii'):
        per = Decimal(count_segments(c.message)) * costs.get(c.channel, costs['generic'])
        c.unit_provider_cost = per
        c.termii_cost = per * c.delivered
        c.save(update_fields=['unit_provider_cost', 'termii_cost'])


class Migration(migrations.Migration):
    dependencies = [('campaigns', '0012_senderid_rejection_reason')]

    operations = [
        migrations.AddField('platformrate', 'cost_generic', models.DecimalField(decimal_places=2, default=Decimal('6.95'), max_digits=6)),
        migrations.AddField('platformrate', 'cost_dnd', models.DecimalField(decimal_places=2, default=Decimal('5.95'), max_digits=6)),
        migrations.AddField('campaign', 'unit_provider_cost', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
