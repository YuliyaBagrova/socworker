from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_servicerecipient_fire_detector_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerecipient',
            name='phone',
            field=models.CharField(
                blank=True,
                max_length=20,
                null=True,
                verbose_name='Телефон',
            ),
        ),
    ]
