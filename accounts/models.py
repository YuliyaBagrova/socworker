from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator

from .belarus_phone import validate_belarus_phone_optional


WORKLOAD_LOAD_COEF_REFERENCE_HOURS = Decimal('168')


def workload_rate_from_load(load: Decimal) -> Decimal:
    """
    Ставка по коэффициенту нагрузки:
    0.0 — при нагрузке ≤ 0.12; 0.25 — ≤ 0.37; 0.5 — ≤ 0.62; 0.75 — ≤ 0.87; 1.0 — > 0.87.
    """
    if load <= Decimal('0.12'):
        return Decimal('0')
    if load <= Decimal('0.37'):
        return Decimal('0.25')
    if load <= Decimal('0.62'):
        return Decimal('0.5')
    if load <= Decimal('0.87'):
        return Decimal('0.75')
    return Decimal('1')


class UserProfile(models.Model):
    """Дополнительные данные учётной записи (фото для главной и профиля)."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='socworker_profile',
        verbose_name='Пользователь',
    )
    avatar = models.ImageField(
        upload_to='profiles/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='Фото профиля',
        help_text='Необязательно. JPG, PNG или WebP, до 2 МБ.',
    )
    admin_panel_access = models.BooleanField(
        default=False,
        verbose_name='Доступ к панели администратора',
        help_text='Разрешён вход в раздел управления учётными записями инвентаризации (код регистрации).',
    )
    admin_portal_password_plaintext = models.CharField(
        max_length=256,
        blank=True,
        default='',
        verbose_name='Пароль для панели администратора',
        help_text='Обновляется при создании пользователя, смене пароля из панели или из формы «Смена пароля».',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'

    def __str__(self):
        return f'Профиль: {self.user.get_username()}'

    def save(self, *args, **kwargs):
        if self.pk:
            try:
                prev = UserProfile.objects.get(pk=self.pk)
                if prev.avatar and self.avatar != prev.avatar:
                    prev.avatar.delete(save=False)
            except UserProfile.DoesNotExist:
                pass
        super().save(*args, **kwargs)


class AdminPortalPasswordChangeNotification(models.Model):
    """Уведомление панели администратора: смена пароля заведующим или управляющим инвентаризацией."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='admin_portal_password_notifications',
        verbose_name='Пользователь',
    )
    username = models.CharField(max_length=150)
    role_label = models.CharField(max_length=120)
    new_password_plaintext = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    dismissed = models.BooleanField(default=False)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Уведомление: смена пароля'
        verbose_name_plural = 'Уведомления: смены пароля'

    def __str__(self):
        return f'{self.username} ({self.created_at:%Y-%m-%d %H:%M})'


class PortalAuthenticationCodes(models.Model):
    """Строка pk=1: актуальные коды для входа и регистрации (если поле непустое)."""

    inventory_code_override = models.CharField(
        max_length=512,
        blank=True,
        default='',
        verbose_name='Код раздела «Инвентаризация»',
        help_text='Пустое значение — берётся из настроек окружения INVENTORY_AUTHENTICATION_CODE.',
    )
    admin_panel_code_override = models.CharField(
        max_length=512,
        blank=True,
        default='',
        verbose_name='Код панели администратора',
        help_text='Пустое значение — берётся из настроек ADMIN_PANEL_AUTHENTICATION_CODE.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Секретные коды порталов'
        verbose_name_plural = 'Секретные коды порталов'

    def __str__(self):
        return 'Коды порталов'


class SocialWorker(models.Model):
    """Модель социального работника"""
    
    STATUS_CHOICES = [
        ('active', 'Активный'),
        ('inactive', 'Неактивный'),
        ('vacation', 'В отпуске'),
        ('sick', 'На больничном'),
    ]
    
    MEDICAL_CHECKUP_CHOICES = [
        ('passed', 'Пройден'),
        ('not_passed', 'Не пройден'),
        ('expired', 'Просрочен'),
    ]
    
    # Связь с пользователем системы
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='social_worker',
        verbose_name='Пользователь',
        null=True,
        blank=True
    )
    
    # Персональная информация
    first_name = models.CharField(
        max_length=100,
        verbose_name='Имя',
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Имя может содержать только буквы'
        )]
    )
    last_name = models.CharField(
        max_length=100,
        verbose_name='Фамилия',
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Фамилия может содержать только буквы'
        )]
    )
    middle_name = models.CharField(
        max_length=100,
        verbose_name='Отчество',
        blank=True,
        null=True,
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Отчество может содержать только буквы'
        )]
    )
    
    # Контактная информация
    phone = models.CharField(
        validators=[validate_belarus_phone_optional],
        max_length=22,
        verbose_name='Телефон',
        blank=True,
        null=True,
        help_text='Формат: +375 (XX) XXX-XX-XX',
    )
    address = models.TextField(
        verbose_name='Адрес',
        blank=True,
        null=True
    )
    
    # Рабочая информация
    medical_checkup = models.CharField(
        max_length=20,
        choices=MEDICAL_CHECKUP_CHOICES,
        default='not_passed',
        verbose_name='Медицинский осмотр'
    )
    last_medical_checkup_date = models.DateField(
        verbose_name='Дата последнего медосмотра',
        null=True,
        blank=True,
        help_text='Для годовой проверки: осмотр считается актуальным 365 дней с этой даты.',
    )
    medical_checkup_planned_date = models.DateField(
        verbose_name='Медосмотр назначен на',
        null=True,
        blank=True,
        help_text='Запланированная дата прохождения осмотра.',
    )
    medical_notes = models.TextField(
        verbose_name='Примечания по медосмотру',
        blank=True,
        null=True,
        help_text='Сведения о здоровье и медосмотре (раздел «Прохождение медосмотра»).',
    )
    medical_panel_registered = models.BooleanField(
        default=False,
        verbose_name='Учёт в панели «Прохождение медосмотра»',
        help_text='Сотрудник появляется в таблице после «Назначить медосмотр».',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name='Статус'
    )
    employee_id = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Табельный номер',
        help_text='Уникальный идентификатор работника'
    )
    
    # Даты
    hire_date = models.DateField(
        verbose_name='Дата приема на работу',
        null=True,
        blank=True
    )
    birth_date = models.DateField(
        verbose_name='Дата рождения',
        null=True,
        blank=True
    )
    
    # Дополнительная информация
    notes = models.TextField(
        verbose_name='Примечания',
        blank=True,
        null=True
    )
    
    # Метаданные
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )
    
    class Meta:
        verbose_name = 'Социальный работник'
        verbose_name_plural = 'Социальные работники'
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['status']),
            models.Index(fields=['employee_id']),
        ]
    
    def __str__(self):
        if self.middle_name:
            return f"{self.last_name} {self.first_name} {self.middle_name}"
        return f"{self.last_name} {self.first_name}"
    
    def get_full_name(self):
        """Возвращает полное имя работника"""
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return ' '.join(parts)

    def get_short_name(self):
        """Фамилия и инициал имени — для компактных подписей в списках."""
        ln = (self.last_name or '').strip()
        fn = (self.first_name or '').strip()
        if fn:
            return f'{ln} {fn[0]}.'.strip()
        return ln or self.get_full_name()
    
    @property
    def is_active(self):
        """Проверяет, активен ли работник"""
        return self.status == 'active'


class ServiceLocation(models.Model):
    """Населённый пункт (город / деревня / село)"""
    
    LOCATION_TYPE_CHOICES = [
        ('city', 'Город'),
        ('village', 'Деревня'),
        ('selo', 'Село'),
        ('poselok', 'Посёлок'),
        ('other', 'Другое'),
    ]
    
    name = models.CharField(
        max_length=200,
        verbose_name='Название',
    )
    location_type = models.CharField(
        max_length=20,
        choices=LOCATION_TYPE_CHOICES,
        default='village',
        verbose_name='Тип',
    )
    
    class Meta:
        verbose_name = 'Населённый пункт'
        verbose_name_plural = 'Населённые пункты'
        ordering = ['name']
        unique_together = ['name', 'location_type']
    
    def __str__(self):
        return f"{self.get_location_type_display()} {self.name}"


class ServiceRecipient(models.Model):
    """Модель получателя услуг (подопечного)"""
    
    DISABILITY_GROUP_CHOICES = [
        ('none', 'Нет'),
        ('1', 'I группа'),
        ('2', 'II группа'),
        ('3', 'III группа'),
        ('child', 'Ребенок-инвалид'),
    ]
    
    LIVING_STATUS_CHOICES = [
        ('alone', 'Одинокий'),
        ('with_family', 'С семьей'),
        ('with_spouse', 'С супругом(ой)'),
        ('boarding', 'Интернат'),
        ('other', 'Другое'),
    ]

    HOUSING_TYPE_CHOICES = [
        ('house', 'Дом'),
        ('apartment', 'Квартира'),
    ]
    
    VISIT_FREQUENCY_CHOICES = [
        ('1', '1 раз в неделю'),
        ('2', '2 раза в неделю'),
        ('3', '3 раза в неделю'),
        ('4', '4 раза в неделю'),
        ('5', '5 раз в неделю'),
        ('daily', 'Ежедневно'),
    ]
    
    VISIT_DAYS_CHOICES = [
        ('mon', 'Понедельник'),
        ('tue', 'Вторник'),
        ('wed', 'Среда'),
        ('thu', 'Четверг'),
        ('fri', 'Пятница'),
        ('sat', 'Суббота'),
        ('sun', 'Воскресенье'),
    ]
    
    employee_id = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Табельный номер',
        help_text='Уникальный идентификатор получателя'
    )
    
    first_name = models.CharField(
        max_length=100,
        verbose_name='Имя',
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Имя может содержать только буквы'
        )]
    )
    last_name = models.CharField(
        max_length=100,
        verbose_name='Фамилия',
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Фамилия может содержать только буквы'
        )]
    )
    middle_name = models.CharField(
        max_length=100,
        verbose_name='Отчество',
        blank=True,
        null=True,
        validators=[RegexValidator(
            regex=r'^[А-Яа-яЁёA-Za-z\s]+$',
            message='Отчество может содержать только буквы'
        )]
    )
    
    birth_date = models.DateField(
        verbose_name='Дата рождения',
        null=True,
        blank=True
    )
    phone = models.CharField(
        max_length=22,
        verbose_name='Телефон',
        blank=True,
        null=True,
        validators=[validate_belarus_phone_optional],
        help_text='Формат: +375 (XX) XXX-XX-XX',
    )
    address = models.TextField(
        verbose_name='Адрес проживания',
        blank=True,
        null=True
    )
    disability_group = models.CharField(
        max_length=20,
        choices=DISABILITY_GROUP_CHOICES,
        default='none',
        verbose_name='Группа инвалидности'
    )
    payment_percent = models.PositiveIntegerField(
        verbose_name='Сумма оплаты (%)',
        default=0,
        help_text='Процент оплаты за услуги (0–100)'
    )
    visit_frequency = models.CharField(
        max_length=10,
        choices=VISIT_FREQUENCY_CHOICES,
        default='2',
        verbose_name='Кратность посещения'
    )
    living_status = models.CharField(
        max_length=20,
        choices=LIVING_STATUS_CHOICES,
        default='alone',
        verbose_name='Статус проживания'
    )
    admission_date = models.DateField(
        verbose_name='Дата приёма',
        null=True,
        blank=True
    )
    visit_days = models.CharField(
        max_length=100,
        verbose_name='Дни посещений',
        blank=True,
        null=True,
        help_text='Например: Пн, Ср, Пт'
    )
    fire_detector_count = models.PositiveIntegerField(
        verbose_name='АПИ количество',
        default=0,
        help_text='Автономный пожарный извещатель — количество'
    )
    
    social_worker = models.ForeignKey(
        SocialWorker,
        on_delete=models.SET_NULL,
        related_name='recipients',
        verbose_name='Социальный работник',
        null=True,
        blank=True
    )
    visit_planning_panel_registered = models.BooleanField(
        default=False,
        verbose_name='Учитывается в панели планирования визитов',
        help_text='Подопечный отображается в таблице панели после добавления через «Запланировать визит».',
    )
    location = models.ForeignKey(
        ServiceLocation,
        on_delete=models.SET_NULL,
        related_name='recipients',
        verbose_name='Населённый пункт',
        null=True,
        blank=True
    )
    housing_type = models.CharField(
        max_length=20,
        choices=HOUSING_TYPE_CHOICES,
        default='apartment',
        verbose_name='Тип жилья (дом / квартира)',
        help_text='В «Расчёте нагрузки» сначала подставляется по тексту в «Адрес», иначе это поле.',
    )
    
    notes = models.TextField(
        verbose_name='Примечания',
        blank=True,
        null=True
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )
    
    class Meta:
        verbose_name = 'Получатель услуг'
        verbose_name_plural = 'Получатели услуг'
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['employee_id']),
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['disability_group']),
            models.Index(fields=['social_worker']),
        ]
    
    def __str__(self):
        if self.middle_name:
            return f"{self.last_name} {self.first_name} {self.middle_name}"
        return f"{self.last_name} {self.first_name}"
    
    def get_full_name(self):
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return ' '.join(parts)

    def clean(self):
        from .visit_schedule import validate_visit_frequency_and_days
        super().clean()
        msg = validate_visit_frequency_and_days(self.visit_frequency, self.visit_days)
        if msg:
            raise ValidationError({'visit_days': msg})


class PlannedVisit(models.Model):
    """Явно запланированный визит (дополняет график по полям подопечного)."""
    recipient = models.ForeignKey(
        ServiceRecipient,
        on_delete=models.CASCADE,
        related_name='planned_visits',
        verbose_name='Подопечный',
    )
    social_worker = models.ForeignKey(
        SocialWorker,
        on_delete=models.CASCADE,
        related_name='planned_visits',
        verbose_name='Социальный работник',
    )
    visit_date = models.DateField(verbose_name='Дата визита')
    visit_time = models.TimeField(verbose_name='Время', null=True, blank=True)
    notes = models.TextField(verbose_name='Примечание', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Запланированный визит'
        verbose_name_plural = 'Запланированные визиты'
        ordering = ['visit_date', 'visit_time', 'pk']
        unique_together = [['recipient', 'visit_date']]

    def __str__(self):
        return f'{self.recipient.get_full_name()} — {self.visit_date}'


class VisitTaskReminder(models.Model):
    """
    Задача с напоминанием: показывается сотруднику за 2 календарных дня до даты выполнения
    и до этой даты включительно (как и запланированные визиты в той же логике).
    """
    social_worker = models.ForeignKey(
        SocialWorker,
        on_delete=models.CASCADE,
        related_name='visit_task_reminders',
        verbose_name='Социальный работник',
    )
    recipient = models.ForeignKey(
        ServiceRecipient,
        on_delete=models.CASCADE,
        related_name='visit_task_reminders',
        null=True,
        blank=True,
        verbose_name='Подопечный',
    )
    task_date = models.DateField(verbose_name='Дата выполнения задачи')
    description = models.TextField(verbose_name='Описание задачи', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Напоминание о задаче'
        verbose_name_plural = 'Напоминания о задачах'
        ordering = ['task_date', 'social_worker__last_name', 'pk']

    def __str__(self):
        return f'{self.social_worker.get_full_name()} — {self.task_date}'


class SafetyBriefingRecord(models.Model):
    """Учёт прохождения инструктажа по охране труда / технике безопасности."""
    social_worker = models.ForeignKey(
        SocialWorker,
        on_delete=models.CASCADE,
        related_name='safety_briefing_records',
        verbose_name='Социальный работник',
    )
    briefing_title = models.CharField(max_length=255, verbose_name='Название инструктажа')
    briefing_date = models.DateField(verbose_name='Дата инструктажа')
    passed = models.BooleanField(
        default=True,
        verbose_name='Инструктаж пройден',
        help_text='Если снято — запись ожидает подтверждения прохождения.',
    )
    notes = models.TextField(verbose_name='Примечание', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Запись инструктажа (ТБ)'
        verbose_name_plural = 'Инструктажи по технике безопасности'
        ordering = ['-briefing_date', 'social_worker__last_name', 'pk']

    def __str__(self):
        return f'{self.social_worker.get_full_name()} — {self.briefing_title} ({self.briefing_date})'


class WorkloadRecord(models.Model):
    """
    Учёт нагрузки: строка журнала (работник, населённый пункт, тип жилья, кратность и время визитов,
    автоматический расчёт отработанного времени, коэффициента нагрузки и ставки).
    """

    HOUSING_TYPE_CHOICES = [
        ('house', 'Дом'),
        ('apartment', 'Квартира'),
    ]

    social_worker = models.ForeignKey(
        SocialWorker,
        on_delete=models.CASCADE,
        related_name='workload_records',
        verbose_name='Работник',
    )
    recipient = models.ForeignKey(
        ServiceRecipient,
        on_delete=models.SET_NULL,
        related_name='workload_records',
        null=True,
        blank=True,
    )
    location = models.ForeignKey(
        ServiceLocation,
        on_delete=models.SET_NULL,
        related_name='workload_records',
        null=True,
        blank=True,
    )
    housing_type = models.CharField(
        max_length=20,
        choices=HOUSING_TYPE_CHOICES,
        default='apartment',
        verbose_name='Тип (дом или квартира)',
    )

    period_year = models.PositiveIntegerField(
        verbose_name='Год',
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    period_month = models.PositiveSmallIntegerField(
        verbose_name='Месяц',
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )

    visits_per_week = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Кратность посещений (раз в неделю)',
    )
    visits_per_month = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Кратность посещений (раз в месяц)',
        help_text='Если не указано — считается как кратность за неделю × 4 (как в типовой таблице нагрузки).',
    )
    visit_duration_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name='Время 1 посещения (минут)',
    )

    worked_minutes_month = models.PositiveIntegerField(
        default=0,
        verbose_name='Время отработано за месяц (минут)',
    )
    worked_hours_month = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Время отработано за месяц (часов)',
    )
    work_time_norm_minutes = models.PositiveIntegerField(
        default=10080,
        verbose_name='Норма рабочего времени (минут в месяц)',
        help_text='По умолчанию 10080 мин (168 ч в месяц), как в расчётных таблицах нагрузки.',
    )
    load_coefficient = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal('0'),
        verbose_name='Коэффициент нагрузки',
    )
    rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Ставка',
    )

    notes = models.TextField(verbose_name='Примечание', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Запись учёта нагрузки'
        verbose_name_plural = 'Учёт нагрузки'
        ordering = ['-period_year', '-period_month', 'social_worker__last_name', 'pk']
        indexes = [
            models.Index(fields=['period_year', 'period_month']),
            models.Index(fields=['social_worker', 'period_year', 'period_month']),
        ]

    def __str__(self):
        return f'{self.social_worker.get_full_name()} — {self.period_month:02d}.{self.period_year}'

    @property
    def work_time_norm_hours(self):
        """Для отображения в колонке «Норма» (168 ч), как в расчётной таблице."""
        return WORKLOAD_LOAD_COEF_REFERENCE_HOURS.quantize(Decimal('0.1'))

    def recompute_derived(self):
        """Пересчитывает кратность за месяц, время, нагрузку и ставку (без save)."""
        vpw = self.visits_per_week or Decimal('0')
        vpm = self.visits_per_month
        if vpm is None:
            vpm = (vpw * Decimal('4')).quantize(Decimal('0.01'))
        else:
            vpm = vpm.quantize(Decimal('0.01'))
        self.visits_per_month = vpm

        dur = int(self.visit_duration_minutes or 0)
        self.worked_minutes_month = int((vpm * Decimal(dur)).quantize(Decimal('1')))
        worked_hours = (Decimal(self.worked_minutes_month) / Decimal('60')).quantize(Decimal('0.01'))
        self.worked_hours_month = worked_hours

        if WORKLOAD_LOAD_COEF_REFERENCE_HOURS <= 0:
            self.load_coefficient = Decimal('0')
        else:
            self.load_coefficient = (
                worked_hours / WORKLOAD_LOAD_COEF_REFERENCE_HOURS
            ).quantize(Decimal('0.01'))
        self.rate = workload_rate_from_load(self.load_coefficient)

    def save(self, *args, **kwargs):
        self.recompute_derived()
        super().save(*args, **kwargs)
