from django.conf import settings
from django.db import models

from accounts.belarus_phone import validate_belarus_phone_optional


class InvRole(models.Model):
    """Справочник ролей инвентаризации (таблица inv_roles)."""

    code = models.CharField(max_length=32, unique=True, verbose_name='Код')
    name = models.CharField(max_length=100, verbose_name='Название')

    class Meta:
        db_table = 'inv_roles'
        verbose_name = 'Роль инвентаризации'
        verbose_name_plural = 'Роли инвентаризации'
        ordering = ['code']

    def __str__(self):
        return self.name


class Department(models.Model):
    """Отделение организации."""

    name = models.CharField(max_length=255, verbose_name='Название отделения')
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='headed_inventory_departments',
        verbose_name='Руководитель отделения',
    )

    class Meta:
        verbose_name = 'Отделение'
        verbose_name_plural = 'Отделения'
        ordering = ['name']

    def __str__(self):
        return self.name


class InventoryUnit(models.Model):
    """Единица учёта: техника, мебель и т.д."""

    inventory_number = models.CharField(
        max_length=64,
        unique=True,
        verbose_name='Инвентарный номер',
    )
    name = models.CharField(max_length=500, verbose_name='Название')
    cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name='Стоимость',
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='inventory_units',
        verbose_name='Ответственный',
    )
    equipment_photo = models.ImageField(
        upload_to='inventory/equipment/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='Фото техники',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_units_created',
        verbose_name='Кем заведена запись',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Единица учёта'
        verbose_name_plural = 'Единицы учёта'
        ordering = ['inventory_number']

    def __str__(self):
        return f'{self.inventory_number} — {self.name[:40]}'

    def delete(self, *args, **kwargs):
        if self.equipment_photo:
            self.equipment_photo.delete(save=False)
        super().delete(*args, **kwargs)
