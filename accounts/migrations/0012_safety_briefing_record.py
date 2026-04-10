from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_socialworker_medical_dates'),
    ]

    operations = [
        migrations.CreateModel(
            name='SafetyBriefingRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('briefing_title', models.CharField(max_length=255, verbose_name='Название инструктажа')),
                ('briefing_date', models.DateField(verbose_name='Дата инструктажа')),
                ('notes', models.TextField(blank=True, verbose_name='Примечание')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'social_worker',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='safety_briefing_records',
                        to='accounts.socialworker',
                        verbose_name='Социальный работник',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Запись инструктажа (ТБ)',
                'verbose_name_plural': 'Инструктажи по технике безопасности',
                'ordering': ['-briefing_date', 'social_worker__last_name', 'pk'],
            },
        ),
    ]
