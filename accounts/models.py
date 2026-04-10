from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator


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
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Номер телефона должен быть в формате: '+999999999'. До 15 цифр."
    )
    phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        verbose_name='Телефон',
        blank=True,
        null=True
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
        max_length=20,
        verbose_name='Телефон',
        blank=True,
        null=True
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
    location = models.ForeignKey(
        ServiceLocation,
        on_delete=models.SET_NULL,
        related_name='recipients',
        verbose_name='Населённый пункт',
        null=True,
        blank=True
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
