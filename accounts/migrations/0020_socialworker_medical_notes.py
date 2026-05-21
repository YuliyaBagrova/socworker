# Generated manually for medical_notes field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0019_rename_accounts_se_employe_idx_accounts_se_employe_b86ce8_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialworker',
            name='medical_notes',
            field=models.TextField(
                blank=True,
                help_text='Сведения о здоровье и медосмотре (раздел «Прохождение медосмотра»).',
                null=True,
                verbose_name='Примечания по медосмотру',
            ),
        ),
    ]
