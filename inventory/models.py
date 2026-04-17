from django.conf import settings
from django.db import models

from accounts.belarus_phone import validate_belarus_phone_optional


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


class InventoryProfile(models.Model):
    """
    Профиль пользователя для инвентаризации: ФИО, должность, отделение, роль, телефон.
    Логин и пароль хранятся в стандартной модели User (django.contrib.auth).
    """

    ROLE_EMPLOYEE = 'employee'
    ROLE_DEPT_HEAD = 'department_head'
    ROLE_WAREHOUSE = 'warehouse_keeper'

    ROLE_CHOICES = [
        (ROLE_EMPLOYEE, 'Сотрудник'),
        (ROLE_DEPT_HEAD, 'Руководитель отдела'),
        (ROLE_WAREHOUSE, 'Завхоз'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inventory_profile',
        verbose_name='Пользователь',
    )
    full_name = models.CharField(max_length=255, verbose_name='ФИО')
    position = models.CharField(max_length=255, blank=True, verbose_name='Должность')
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_profiles',
        verbose_name='Отделение',
    )
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default=ROLE_EMPLOYEE,
        verbose_name='Роль',
    )
    phone = models.CharField(
        max_length=40,
        blank=True,
        verbose_name='Телефон',
        validators=[validate_belarus_phone_optional],
        help_text='Формат: +375 (XX) XXX-XX-XX',
    )

    class Meta:
        verbose_name = 'Профиль инвентаризации'
        verbose_name_plural = 'Профили инвентаризации (пользователи)'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} ({self.get_role_display()})'

    def sync_user_names(self):
        """Дублирует ФИО в first_name/last_name User для отображения в шапке."""
        parts = (self.full_name or '').strip().split(None, 1)
        if len(parts) >= 2:
            self.user.last_name, self.user.first_name = parts[0], parts[1]
        elif parts:
            self.user.last_name, self.user.first_name = parts[0], ''
        else:
            self.user.last_name, self.user.first_name = '', ''
        self.user.save(update_fields=['first_name', 'last_name'])


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Единица учёта'
        verbose_name_plural = 'Единицы учёта'
        ordering = ['inventory_number']

    def __str__(self):
        return f'{self.inventory_number} — {self.name[:40]}'
