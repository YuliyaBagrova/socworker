from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_update_socialworker'),
    ]

    operations = [
        # Сначала удаляем индексы (пока поля ещё существуют)
        migrations.RemoveIndex(
            model_name='servicerecipient',
            name='accounts_se_status_idx',
        ),
        migrations.RemoveIndex(
            model_name='servicerecipient',
            name='accounts_se_categor_idx',
        ),

        # Удаляем старые поля
        migrations.RemoveField(
            model_name='servicerecipient',
            name='phone',
        ),
        migrations.RemoveField(
            model_name='servicerecipient',
            name='email',
        ),
        migrations.RemoveField(
            model_name='servicerecipient',
            name='category',
        ),
        migrations.RemoveField(
            model_name='servicerecipient',
            name='status',
        ),
        migrations.RemoveField(
            model_name='servicerecipient',
            name='assigned_date',
        ),
        migrations.RemoveField(
            model_name='servicerecipient',
            name='special_needs',
        ),

        # Добавляем новые поля
        migrations.AddField(
            model_name='servicerecipient',
            name='disability_group',
            field=models.CharField(
                choices=[
                    ('none', 'Нет'),
                    ('1', 'I группа'),
                    ('2', 'II группа'),
                    ('3', 'III группа'),
                    ('child', 'Ребенок-инвалид'),
                ],
                default='none',
                max_length=20,
                verbose_name='Группа инвалидности',
            ),
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='payment_percent',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Процент оплаты за услуги (0–100)',
                verbose_name='Сумма оплаты (%)',
            ),
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='visit_frequency',
            field=models.CharField(
                choices=[
                    ('1', '1 раз в неделю'),
                    ('2', '2 раза в неделю'),
                    ('3', '3 раза в неделю'),
                    ('4', '4 раза в неделю'),
                    ('5', '5 раз в неделю'),
                    ('daily', 'Ежедневно'),
                ],
                default='2',
                max_length=10,
                verbose_name='Кратность посещения',
            ),
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='living_status',
            field=models.CharField(
                choices=[
                    ('alone', 'Одинокий'),
                    ('with_family', 'С семьей'),
                    ('with_spouse', 'С супругом(ой)'),
                    ('boarding', 'Интернат'),
                    ('other', 'Другое'),
                ],
                default='alone',
                max_length=20,
                verbose_name='Статус проживания',
            ),
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='admission_date',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Дата приёма',
            ),
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='visit_days',
            field=models.CharField(
                blank=True,
                help_text='Например: Пн, Ср, Пт',
                max_length=100,
                null=True,
                verbose_name='Дни посещений',
            ),
        ),

        # Добавляем новый индекс
        migrations.AddIndex(
            model_name='servicerecipient',
            index=models.Index(fields=['disability_group'], name='accounts_se_disabil_idx'),
        ),
    ]
