from django.db import migrations


def add_inventory_accountable_role(apps, schema_editor):
    InvRole = apps.get_model('inventory', 'InvRole')
    InvRole.objects.get_or_create(
        code='inventory_accountable',
        defaults={'name': 'Ответственный за инвентарь'},
    )


def remove_inventory_accountable_role(apps, schema_editor):
    InvRole = apps.get_model('inventory', 'InvRole')
    InvRole.objects.filter(code='inventory_accountable').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_inventoryunit_created_by'),
    ]

    operations = [
        migrations.RunPython(add_inventory_accountable_role, remove_inventory_accountable_role),
    ]
