from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0005_inventoryunit_equipment_photo'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryunit',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='inventory_units_created',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Кем заведена запись',
            ),
        ),
    ]
