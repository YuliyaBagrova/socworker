# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_servicerecipient_visit_planning_panel_registered'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerecipient',
            name='housing_type',
            field=models.CharField(
                choices=[('house', 'Дом'), ('apartment', 'Квартира')],
                default='apartment',
                help_text='Используется при автозаполнении «Расчёта нагрузки» и в отчётах по подопечному.',
                max_length=20,
                verbose_name='Тип жилья (дом / квартира)',
            ),
        ),
    ]
