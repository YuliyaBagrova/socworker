# Таблица inv_roles, справочник, столбцы инвентаризации в auth_user (MySQL).

from django.db import migrations, models


def seed_inv_roles(apps, schema_editor):
    InvRole = apps.get_model('inventory', 'InvRole')
    rows = [
        ('employee', 'Сотрудник'),
        ('department_head', 'Руководитель отдела'),
        ('warehouse_keeper', 'Завхоз'),
    ]
    for code, name in rows:
        InvRole.objects.get_or_create(code=code, defaults={'name': name})


def unseed_inv_roles(apps, schema_editor):
    InvRole = apps.get_model('inventory', 'InvRole')
    InvRole.objects.filter(code__in=('employee', 'department_head', 'warehouse_keeper')).delete()


def _mysql_exec(cursor, sql, params=None):
    if params is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, params)


def forwards_add_auth_inv_columns(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        raise RuntimeError(
            'Миграция добавления inv_* в auth_user рассчитана на MySQL.'
        )
    with connection.cursor() as cursor:
        for col, ddl in [
            ('inv_role_id', 'BIGINT NULL'),
            ('inv_department_id', 'BIGINT NULL'),
            ('inv_position', "VARCHAR(255) NOT NULL DEFAULT ''"),
            ('inv_phone', "VARCHAR(40) NOT NULL DEFAULT ''"),
        ]:
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_user' AND COLUMN_NAME = %s
                """,
                [col],
            )
            if cursor.fetchone()[0]:
                continue
            _mysql_exec(cursor, f'ALTER TABLE auth_user ADD COLUMN {col} {ddl}')

        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_user'
              AND CONSTRAINT_NAME = 'auth_user_inv_role_id_fk_inv_roles'
            """
        )
        if not cursor.fetchone()[0]:
            _mysql_exec(
                cursor,
                """
                ALTER TABLE auth_user
                ADD CONSTRAINT auth_user_inv_role_id_fk_inv_roles
                FOREIGN KEY (inv_role_id) REFERENCES inv_roles(id) ON DELETE SET NULL
                """,
            )

        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_user'
              AND CONSTRAINT_NAME = 'auth_user_inv_department_id_fk_inventory_department'
            """
        )
        if not cursor.fetchone()[0]:
            _mysql_exec(
                cursor,
                """
                ALTER TABLE auth_user
                ADD CONSTRAINT auth_user_inv_department_id_fk_inventory_department
                FOREIGN KEY (inv_department_id) REFERENCES inventory_department(id) ON DELETE SET NULL
                """,
            )


def backwards_drop_auth_inv_columns(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return
    with connection.cursor() as cursor:
        for cname in (
            'auth_user_inv_department_id_fk_inventory_department',
            'auth_user_inv_role_id_fk_inv_roles',
        ):
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_user'
                  AND CONSTRAINT_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'
                """,
                [cname],
            )
            if cursor.fetchone()[0]:
                _mysql_exec(cursor, f'ALTER TABLE auth_user DROP FOREIGN KEY `{cname}`')
        for col in ('inv_phone', 'inv_position', 'inv_department_id', 'inv_role_id'):
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_user' AND COLUMN_NAME = %s
                """,
                [col],
            )
            if cursor.fetchone()[0]:
                _mysql_exec(cursor, f'ALTER TABLE auth_user DROP COLUMN {col}')


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_alter_inventoryprofile_phone'),
    ]

    operations = [
        migrations.CreateModel(
            name='InvRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=32, unique=True, verbose_name='Код')),
                ('name', models.CharField(max_length=100, verbose_name='Название')),
            ],
            options={
                'verbose_name': 'Роль инвентаризации',
                'verbose_name_plural': 'Роли инвентаризации',
                'db_table': 'inv_roles',
                'ordering': ['code'],
            },
        ),
        migrations.RunPython(seed_inv_roles, unseed_inv_roles),
        migrations.RunPython(forwards_add_auth_inv_columns, backwards_drop_auth_inv_columns),
    ]
