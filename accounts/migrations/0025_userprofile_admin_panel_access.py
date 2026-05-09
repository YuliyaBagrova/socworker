from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0024_servicerecipient_housing_help'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='admin_panel_access',
            field=models.BooleanField(
                default=False,
                help_text='Разрешён вход в раздел управления учётными записями инвентаризации (код регистрации).',
                verbose_name='Доступ к панели администратора',
            ),
        ),
    ]
