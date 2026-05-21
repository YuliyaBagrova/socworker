"""Создаёт в БД роль «Ответственный за инвентарь», если её ещё нет."""
from django.core.management.base import BaseCommand

from inventory.models import InvRole
from inventory.permissions import INVENTORY_ACCOUNTABLE_CODE


class Command(BaseCommand):
    help = (
        'Добавляет в справочник inv_roles запись inventory_accountable '
        '(«Ответственный за инвентарь»). Безопасно запускать повторно.'
    )

    def handle(self, *args, **options):
        role, created = InvRole.objects.get_or_create(
            code=INVENTORY_ACCOUNTABLE_CODE,
            defaults={'name': 'Ответственный за инвентарь'},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Создана роль: {role.code} — {role.name}'))
        else:
            self.stdout.write(f'Роль уже есть: {role.code} — {role.name}')
