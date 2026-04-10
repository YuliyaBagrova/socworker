# Generated manually

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=100, validators=[django.core.validators.RegexValidator(message='Имя может содержать только буквы', regex='^[А-Яа-яЁёA-Za-z\\s]+$')], verbose_name='Имя')),
                ('last_name', models.CharField(max_length=100, validators=[django.core.validators.RegexValidator(message='Фамилия может содержать только буквы', regex='^[А-Яа-яЁёA-Za-z\\s]+$')], verbose_name='Фамилия')),
                ('middle_name', models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='Отчество может содержать только буквы', regex='^[А-Яа-яЁёA-Za-z\\s]+$')], verbose_name='Отчество')),
                ('birth_date', models.DateField(blank=True, null=True, verbose_name='Дата рождения')),
                ('phone', models.CharField(blank=True, max_length=17, null=True, validators=[django.core.validators.RegexValidator(message="Номер телефона должен быть в формате: '+999999999'. До 15 цифр.", regex='^\\+?1?\\d{9,15}$')], verbose_name='Телефон')),
                ('email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='Email')),
                ('address', models.TextField(blank=True, null=True, verbose_name='Адрес проживания')),
                ('category', models.CharField(choices=[('elderly', 'Пожилой'), ('disabled', 'Инвалид'), ('child', 'Ребенок'), ('family', 'Многодетная семья'), ('other', 'Другое')], default='other', max_length=30, verbose_name='Категория')),
                ('status', models.CharField(choices=[('active', 'Активный'), ('inactive', 'Неактивный'), ('archived', 'Архивный')], default='active', max_length=20, verbose_name='Статус')),
                ('assigned_date', models.DateField(blank=True, null=True, verbose_name='Дата назначения')),
                ('special_needs', models.TextField(blank=True, null=True, verbose_name='Особые потребности')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='Примечания')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Дата обновления')),
                ('social_worker', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recipients', to='accounts.socialworker', verbose_name='Социальный работник')),
            ],
            options={
                'verbose_name': 'Получатель услуг',
                'verbose_name_plural': 'Получатели услуг',
                'ordering': ['last_name', 'first_name'],
                'indexes': [
                    models.Index(fields=['last_name', 'first_name'], name='accounts_se_last_na_idx'),
                    models.Index(fields=['status'], name='accounts_se_status_idx'),
                    models.Index(fields=['category'], name='accounts_se_categor_idx'),
                    models.Index(fields=['social_worker'], name='accounts_se_social__idx'),
                ],
            },
        ),
    ]
