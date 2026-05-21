from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_migrate_inventory_profile_remove'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryunit',
            name='equipment_photo',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='inventory/equipment/%Y/%m/',
                verbose_name='Фото техники',
            ),
        ),
    ]
