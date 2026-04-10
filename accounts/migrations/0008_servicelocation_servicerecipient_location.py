from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_servicerecipient_employee_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceLocation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('location_type', models.CharField(
                    choices=[
                        ('city', 'Город'),
                        ('village', 'Деревня'),
                        ('selo', 'Село'),
                        ('poselok', 'Посёлок'),
                        ('other', 'Другое'),
                    ],
                    default='village',
                    max_length=20,
                    verbose_name='Тип',
                )),
            ],
            options={
                'verbose_name': 'Населённый пункт',
                'verbose_name_plural': 'Населённые пункты',
                'ordering': ['name'],
                'unique_together': {('name', 'location_type')},
            },
        ),
        migrations.AddField(
            model_name='servicerecipient',
            name='location',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='recipients',
                to='accounts.servicelocation',
                verbose_name='Населённый пункт',
            ),
        ),
    ]
