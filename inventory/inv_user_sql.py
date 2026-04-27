"""Чтение/обновление полей инвентаризации в таблице auth_user (без подмены AUTH_USER_MODEL)."""
from __future__ import annotations

from typing import List, Optional, Set

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.utils import DatabaseError, OperationalError, ProgrammingError

User = get_user_model()

_DB_READ_ERRORS = (DatabaseError, ProgrammingError, OperationalError)


def inv_role_code_for_user(user_id: int) -> Optional[str]:
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT r.code
                FROM auth_user u
                LEFT JOIN inv_roles r ON r.id = u.inv_role_id
                WHERE u.id = %s
                """,
                [user_id],
            )
            row = c.fetchone()
    except _DB_READ_ERRORS:
        return None
    if not row:
        return None
    return row[0]


def inv_department_id_for_user(user_id: int) -> Optional[int]:
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT inv_department_id FROM auth_user WHERE id = %s",
                [user_id],
            )
            row = c.fetchone()
    except _DB_READ_ERRORS:
        return None
    if not row:
        return None
    return row[0]


def user_ids_with_inv_role_assigned() -> List[int]:
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT id FROM auth_user WHERE inv_role_id IS NOT NULL ORDER BY last_name, first_name, username"
            )
            return [row[0] for row in c.fetchall()]
    except _DB_READ_ERRORS:
        return []


def user_ids_in_department_or_self(dept_id: int, self_id: int) -> Set[int]:
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT id FROM auth_user
                WHERE inv_department_id = %s OR id = %s
                """,
                [dept_id, self_id],
            )
            return {row[0] for row in c.fetchall()}
    except _DB_READ_ERRORS:
        return {self_id}


def update_auth_user_inventory(
    user_id: int,
    *,
    inv_role_id: Optional[int],
    inv_department_id: Optional[int],
    inv_position: str = '',
    inv_phone: str = '',
    last_name: Optional[str] = None,
    first_name: Optional[str] = None,
):
    fields = [
        'inv_role_id = %s',
        'inv_department_id = %s',
        'inv_position = %s',
        'inv_phone = %s',
    ]
    params: List = [inv_role_id, inv_department_id, inv_position or '', inv_phone or '']
    if last_name is not None:
        fields.append('last_name = %s')
        params.append(last_name)
    if first_name is not None:
        fields.append('first_name = %s')
        params.append(first_name)
    params.append(user_id)
    sql = f"UPDATE auth_user SET {', '.join(fields)} WHERE id = %s"
    try:
        with connection.cursor() as c:
            c.execute(sql, params)
    except _DB_READ_ERRORS as e:
        raise RuntimeError(
            'Не удалось сохранить поля инвентаризации в auth_user. '
            'Выполните миграции: python manage.py migrate'
        ) from e


def staff_rows_for_template() -> List[dict]:
    """Строки для staff_list: JOIN auth_user, inv_roles, inventory_department."""
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.username, u.first_name, u.last_name, u.inv_position,
                       d.name, r.name, u.inv_phone
                FROM auth_user u
                LEFT JOIN inv_roles r ON r.id = u.inv_role_id
                LEFT JOIN inventory_department d ON d.id = u.inv_department_id
                WHERE u.inv_role_id IS NOT NULL
                ORDER BY u.last_name, u.first_name, u.username
                """
            )
            rows = []
            for row in c.fetchall():
                rows.append({
                    'username': row[0],
                    'first_name': row[1] or '',
                    'last_name': row[2] or '',
                    'inv_position': row[3] or '',
                    'department_name': row[4] or '',
                    'role_name': row[5] or '',
                    'inv_phone': row[6] or '',
                })
            return rows
    except _DB_READ_ERRORS:
        return []


def responsible_row_for_csv(responsible_id: int) -> tuple:
    """ФИО, название отделения для CSV."""
    try:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT u.first_name, u.last_name, d.name
                FROM auth_user u
                LEFT JOIN inventory_department d ON d.id = u.inv_department_id
                WHERE u.id = %s
                """,
                [responsible_id],
            )
            row = c.fetchone()
    except _DB_READ_ERRORS:
        return '', ''
    if not row:
        return '', ''
    fn, ln, dept = row
    name = (f'{ln or ""} {fn or ""}').strip()
    return name, (dept or '')
