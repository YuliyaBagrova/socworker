from django.db import migrations, models


def populate_employee_ids(apps, schema_editor):
    ServiceRecipient = apps.get_model('accounts', 'ServiceRecipient')
    for i, r in enumerate(ServiceRecipient.objects.order_by('id'), start=1):
        r.employee_id = f'R-{i:04d}'
        r.save(update_fields=['employee_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_servicerecipient_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerecipient',
            name='employee_id',
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                verbose_name='Табельный номер',
                help_text='Уникальный идентификатор получателя',
            ),
        ),
        migrations.RunPython(populate_employee_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='servicerecipient',
            name='employee_id',
            field=models.CharField(
                max_length=50,
                unique=True,
                verbose_name='Табельный номер',
                help_text='Уникальный идентификатор получателя',
            ),
        ),
        migrations.AddIndex(
            model_name='servicerecipient',
            index=models.Index(fields=['employee_id'], name='accounts_se_employe_idx'),
        ),
    ]
