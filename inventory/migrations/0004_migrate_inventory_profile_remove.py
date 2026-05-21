# Перенос данных из inventory_inventoryprofile в auth_user, затем удаление профиля.

from django.db import connection, migrations


def copy_profiles_to_user(apps, schema_editor):
    Profile = apps.get_model('inventory', 'InventoryProfile')
    InvRole = apps.get_model('inventory', 'InvRole')
    code_to_id = {r.code: r.pk for r in InvRole.objects.all()}
    for p in Profile.objects.select_related('user').iterator():
        uid = p.user_id
        rid = code_to_id.get(p.role)
        dept_id = p.department_id
        pos = (p.position or '').strip()
        phone = (p.phone or '').strip()
        fn = (p.full_name or '').strip()
        last_name, first_name = '', ''
        if fn:
            parts = fn.split(None, 1)
            if len(parts) >= 2:
                last_name, first_name = parts[0], parts[1]
            elif parts:
                last_name, first_name = parts[0], ''
        with connection.cursor() as c:
            c.execute(
                """
                UPDATE auth_user
                SET inv_role_id = %s, inv_department_id = %s, inv_position = %s, inv_phone = %s,
                    last_name = %s, first_name = %s
                WHERE id = %s
                """,
                [rid, dept_id, pos, phone, last_name, first_name, uid],
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_inv_roles_and_user'),
    ]

    operations = [
        migrations.RunPython(copy_profiles_to_user, noop_reverse),
        migrations.DeleteModel(
            name='InventoryProfile',
        ),
    ]
