from collections import OrderedDict

from django import forms
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
    PasswordChangeForm,
)
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import (
    SocialWorker,
    ServiceRecipient,
    ServiceLocation,
    PlannedVisit,
    VisitTaskReminder,
    SafetyBriefingRecord,
    WorkloadRecord,
    UserProfile,
)
from .belarus_phone import BY_PHONE_EXAMPLE, normalize_belarus_phone
from .visit_schedule import validate_visit_frequency_and_days

_PHONE_WIDGET_ATTRS = {
    'class': 'form-control js-belarus-phone',
    'placeholder': BY_PHONE_EXAMPLE,
    'maxlength': '22',
}


class UserProfileAvatarForm(forms.ModelForm):
    """Загрузка фото профиля (необязательно)."""

    class Meta:
        model = UserProfile
        fields = ['avatar']
        labels = {'avatar': 'Изображение'}
        widgets = {
            'avatar': forms.FileInput(attrs={
                'class': 'form-control sw-profile-avatar-input js-profile-avatar-input',
                'accept': 'image/jpeg,image/png,image/webp,image/gif',
            }),
        }

    def clean_avatar(self):
        f = self.cleaned_data.get('avatar')
        if not f:
            return f
        try:
            size = f.size
        except (AttributeError, OSError, TypeError):
            return f
        if size > 2 * 1024 * 1024:
            raise ValidationError('Размер файла не более 2 МБ.')
        name = (getattr(f, 'name', '') or '').lower()
        if not name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            raise ValidationError('Допустимы форматы: JPG, PNG, WebP, GIF.')
        return f


class CustomUserCreationForm(UserCreationForm):
    """Форма регистрации пользователя"""
    email = forms.EmailField(
        required=True,
        label='Электронная почта',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите адрес электронной почты'
        })
    )
    first_name = forms.CharField(
        required=True,
        label='Имя',
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите имя'
        })
    )
    last_name = forms.CharField(
        required=True,
        label='Фамилия',
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите фамилию'
        })
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите имя пользователя'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Имя пользователя'
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Введите пароль'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Подтвердите пароль'
        })
        self.fields['password1'].label = 'Пароль'
        self.fields['password2'].label = 'Подтверждение пароля'
        self.fields['password1'].help_text = (
            'Пароль не должен быть слишком похож на имя пользователя, '
            'должен содержать не менее 8 символов и не быть слишком простым.'
        )
        self.fields['password2'].help_text = ''

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    """Вход по адресу электронной почты и паролю (поле username в POST — email)."""

    username = forms.EmailField(
        label='Электронная почта',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите email',
            'autocomplete': 'email',
            'autofocus': True,
        }),
    )
    password = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите пароль',
            'autocomplete': 'current-password',
        }),
    )

    error_messages = {
        'invalid_login': 'Неверный email или пароль.',
        'inactive': 'Этот аккаунт неактивен.',
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields['username'].max_length = 254
        if hasattr(self.fields['username'].widget, 'attrs'):
            self.fields['username'].widget.attrs['maxlength'] = '254'

    def clean(self):
        email = (self.cleaned_data.get('username') or '').strip()
        password = self.cleaned_data.get('password')
        self.user_cache = None
        if email and password:
            UserModel = get_user_model()
            matches = list(UserModel.objects.filter(email__iexact=email))
            if len(matches) == 1:
                self.user_cache = authenticate(
                    self.request,
                    username=matches[0].get_username(),
                    password=password,
                )
            elif len(matches) > 1:
                raise ValidationError(
                    'Найдено несколько учётных записей с этим email. Обратитесь к администратору.',
                    code='ambiguous_email',
                )
            else:
                self.user_cache = authenticate(
                    self.request,
                    username=email,
                    password=password,
                )
        if self.user_cache is None:
            raise self.get_invalid_login_error()
        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

    def get_invalid_login_error(self):
        return ValidationError(
            self.error_messages['invalid_login'],
            code='invalid_login',
        )


class StyledPasswordChangeForm(PasswordChangeForm):
    """Смена пароля с классами Bootstrap для полей."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'Текущий пароль'
        self.fields['new_password1'].label = 'Новый пароль'
        self.fields['new_password2'].label = 'Подтверждение нового пароля'
        for name, field in self.fields.items():
            ac = 'current-password' if name == 'old_password' else 'new-password'
            field.widget.attrs.update({'class': 'form-control', 'autocomplete': ac})


class SocialWorkerForm(forms.ModelForm):
    """Форма для создания и редактирования социального работника"""
    
    class Meta:
        model = SocialWorker
        fields = [
            'first_name', 'last_name', 'middle_name',
            'birth_date', 'phone', 'address',
            'medical_checkup',
            'status', 'employee_id',
            'hire_date', 'notes'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите имя'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите фамилию'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите отчество (необязательно)'
            }),
            'birth_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                },
                format='%Y-%m-%d',
            ),
            'phone': forms.TextInput(attrs=_PHONE_WIDGET_ATTRS.copy()),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Введите адрес'
            }),
            'medical_checkup': forms.Select(attrs={
                'class': 'form-select'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            }),
            'employee_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Табельный номер'
            }),
            'hire_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                },
                format='%Y-%m-%d',
            ),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Дополнительные примечания'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # type=date ожидает ISO в value; при ru-локали виджет иначе отдаёт dd.mm.yyyy
        for name in ('birth_date', 'hire_date'):
            field = self.fields[name]
            if '%Y-%m-%d' not in field.input_formats:
                field.input_formats = ['%Y-%m-%d'] + list(field.input_formats)

    def clean_phone(self):
        return normalize_belarus_phone(self.cleaned_data.get('phone') or '')


class MedicalCheckupEditForm(forms.Form):
    """Редактирование данных медосмотра с панели «Прохождение медосмотра»."""

    medical_checkup = forms.ChoiceField(
        label='Поле в системе',
        choices=[('passed', 'Пройден'), ('not_passed', 'Не пройден')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    last_medical_checkup_date = forms.DateField(
        label='Дата последнего осмотра',
        required=False,
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'},
            format='%Y-%m-%d',
        ),
    )
    valid_until = forms.DateField(
        label='Годен до',
        required=False,
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'},
            format='%Y-%m-%d',
        ),
    )
    mc_ok_12 = forms.ChoiceField(
        label='Актуально 12 месяцев',
        required=False,
        choices=[('', '—'), ('yes', 'Да'), ('no', 'Нет')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    medical_checkup_planned_date = forms.DateField(
        label='Назначен на',
        required=False,
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'},
            format='%Y-%m-%d',
        ),
    )
    medical_notes = forms.CharField(
        label='Примечания',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Сведения о здоровье и медосмотре (необязательно)',
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('last_medical_checkup_date', 'valid_until', 'medical_checkup_planned_date'):
            field = self.fields[name]
            if '%Y-%m-%d' not in field.input_formats:
                field.input_formats = ['%Y-%m-%d'] + list(field.input_formats)


class ServiceRecipientForm(forms.ModelForm):
    """Форма для создания и редактирования получателя услуг"""

    class Meta:
        model = ServiceRecipient
        fields = [
            'employee_id', 'first_name', 'last_name', 'middle_name',
            'birth_date', 'phone', 'address', 'disability_group',
            'payment_percent', 'visit_frequency', 'living_status',
            'admission_date', 'visit_days', 'fire_detector_count',
            'social_worker', 'location', 'housing_type', 'notes',
        ]
        help_texts = {
            'visit_frequency': 'Число визитов в неделю должно совпадать с количеством указанных дней ниже.',
            'visit_days': 'Перечислите дни через запятую (Пн, Ср, Пт). Для «Ежедневно» оставьте пустым или укажите все 7 дней.',
        }
        widgets = {
            'employee_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Табельный номер'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите имя'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите фамилию'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите отчество (необязательно)'
            }),
            'birth_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'phone': forms.TextInput(attrs=_PHONE_WIDGET_ATTRS.copy()),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Введите адрес проживания'
            }),
            'disability_group': forms.Select(attrs={
                'class': 'form-select'
            }),
            'payment_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'max': 100,
                'placeholder': '0–100'
            }),
            'visit_frequency': forms.Select(attrs={
                'class': 'form-select'
            }),
            'living_status': forms.Select(attrs={
                'class': 'form-select'
            }),
            'admission_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'visit_days': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Пн, Ср, Пт'
            }),
            'fire_detector_count': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'placeholder': '0'
            }),
            'social_worker': forms.Select(attrs={
                'class': 'form-select'
            }),
            'location': forms.Select(attrs={
                'class': 'form-select'
            }),
            'housing_type': forms.Select(attrs={
                'class': 'form-select',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Дополнительные примечания'
            }),
        }

    def clean_phone(self):
        return normalize_belarus_phone(self.cleaned_data.get('phone') or '')

    def clean(self):
        cleaned_data = super().clean()
        err = validate_visit_frequency_and_days(
            cleaned_data.get('visit_frequency'),
            cleaned_data.get('visit_days'),
        )
        if err:
            self.add_error('visit_days', err)
        return cleaned_data


class ServiceLocationForm(forms.ModelForm):
    class Meta:
        model = ServiceLocation
        fields = ['name', 'location_type']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название населённого пункта'
            }),
            'location_type': forms.Select(attrs={
                'class': 'form-select'
            }),
        }


class PlannedVisitForm(forms.ModelForm):
    """Явная запись визита на дату; поля кратности/дней сохраняются в карточке подопечного."""

    recipient_visit_frequency = forms.ChoiceField(
        label='Кратность',
        choices=ServiceRecipient.VISIT_FREQUENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Число визитов в неделю должно совпадать с количеством указанных дней ниже.',
    )
    recipient_visit_days = forms.CharField(
        label='Дни посещений',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Пн, Ср, Пт',
        }),
        help_text='Перечислите дни через запятую. Для «Ежедневно» оставьте пустым или укажите все 7 дней.',
    )

    class Meta:
        model = PlannedVisit
        fields = ['social_worker', 'recipient', 'visit_date', 'visit_time', 'notes']
        widgets = {
            'social_worker': forms.Select(attrs={'class': 'form-select'}),
            'recipient': forms.Select(attrs={'class': 'form-select'}),
            'visit_date': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'visit_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(
        self, *args, recipient_queryset=None, for_panel_assign=False,
        planning_panel_short=False, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.for_panel_assign = for_panel_assign
        self.planning_panel_short = planning_panel_short
        self.fields['social_worker'].queryset = SocialWorker.objects.order_by(
            'last_name', 'first_name',
        )
        self.fields['social_worker'].label = 'Сотрудник из базы'
        if recipient_queryset is not None:
            rec_qs = recipient_queryset
        elif self.instance.pk and self.instance.recipient_id:
            rec_qs = ServiceRecipient.objects.filter(
                social_worker__isnull=False,
            ).filter(
                Q(visit_planning_panel_registered=True)
                | Q(pk=self.instance.recipient_id),
            ).select_related('social_worker').order_by('last_name', 'first_name')
        else:
            rec_qs = ServiceRecipient.objects.filter(
                social_worker__isnull=False,
                visit_planning_panel_registered=True,
            ).select_related('social_worker').order_by('last_name', 'first_name')
        self.fields['recipient'].queryset = rec_qs
        self.fields['recipient'].label = 'Подопечный'
        self.fields['visit_date'].label = 'Дата визита'
        self.fields['visit_time'].label = 'Время (необязательно)'
        if 'notes' in self.fields:
            self.fields['notes'].label = 'Примечание'
        if for_panel_assign or planning_panel_short:
            self.fields.pop('notes', None)

        vd_field = self.fields['visit_date']
        if '%Y-%m-%d' not in vd_field.input_formats:
            vd_field.input_formats = ['%Y-%m-%d'] + list(vd_field.input_formats)

        if self.instance.pk:
            rec = self.instance.recipient
            self.fields['recipient_visit_frequency'].initial = rec.visit_frequency
            self.fields['recipient_visit_days'].initial = rec.visit_days or ''
        else:
            self.fields['recipient_visit_frequency'].initial = '2'
            self.fields['recipient_visit_days'].initial = ''

        order = [
            'social_worker', 'recipient',
            'recipient_visit_frequency', 'recipient_visit_days',
            'visit_date', 'visit_time',
        ]
        if 'notes' in self.fields:
            order.append('notes')
        self.fields = OrderedDict((k, self.fields[k]) for k in order if k in self.fields)

    def clean_recipient(self):
        r = self.cleaned_data['recipient']
        if not r.social_worker_id:
            raise ValidationError('У подопечного должен быть закреплён социальный работник.')
        editing_same = (
            self.instance
            and self.instance.pk
            and self.instance.recipient_id == r.pk
        )
        if (
            not self.for_panel_assign
            and not r.visit_planning_panel_registered
            and not editing_same
        ):
            raise ValidationError(
                'Подопечный не внесён в панель планирования. '
                'Сначала добавьте его через «Запланировать визит» на панели.',
            )
        return r

    def clean(self):
        cleaned = super().clean()
        r = cleaned.get('recipient')
        d = cleaned.get('visit_date')
        freq = cleaned.get('recipient_visit_frequency')
        days = cleaned.get('recipient_visit_days')
        if freq is not None:
            err = validate_visit_frequency_and_days(freq, days)
            if err:
                self.add_error('recipient_visit_days', err)
        if r and d:
            qs = PlannedVisit.objects.filter(recipient=r, visit_date=d)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    'На эту дату для выбранного подопечного уже есть запланированный визит.',
                )
        return cleaned

    def save(self, commit=True):
        inst = super().save(commit=commit)
        if not commit:
            return inst
        freq = self.cleaned_data['recipient_visit_frequency']
        days = (self.cleaned_data.get('recipient_visit_days') or '').strip()
        r = inst.recipient
        r.visit_frequency = freq
        r.visit_days = days
        r.save(update_fields=['visit_frequency', 'visit_days', 'updated_at'])
        return inst


class VisitTaskReminderForm(forms.ModelForm):
    class Meta:
        model = VisitTaskReminder
        fields = ['social_worker', 'recipient', 'task_date', 'description']
        widgets = {
            'social_worker': forms.Select(attrs={'class': 'form-select'}),
            'recipient': forms.Select(attrs={'class': 'form-select'}),
            'task_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['social_worker'].queryset = SocialWorker.objects.order_by(
            'last_name', 'first_name',
        )
        self.fields['social_worker'].label = 'Социальный работник'
        self.fields['recipient'].queryset = ServiceRecipient.objects.filter(
            social_worker__isnull=False,
            visit_planning_panel_registered=True,
        ).select_related('social_worker').order_by('last_name', 'first_name')
        self.fields['recipient'].label = 'Подопечный'
        self.fields['recipient'].required = False
        self.fields['recipient'].empty_label = '— не указан —'
        self.fields['task_date'].label = 'Дата выполнения'
        self.fields['description'].label = 'Описание задачи'

    def clean_recipient(self):
        return self.cleaned_data.get('recipient') or None


class SafetyBriefingRecordForm(forms.ModelForm):
    class Meta:
        model = SafetyBriefingRecord
        fields = ['social_worker', 'briefing_title', 'briefing_date', 'passed', 'notes']
        widgets = {
            'social_worker': forms.Select(attrs={'class': 'form-select'}),
            'briefing_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Например: вводный инструктаж на рабочем месте',
            }),
            # ISO-день для type="date"; иначе браузер не показывает значение при локали dd.mm.yyyy
            'briefing_date': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'},
            ),
            'passed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['social_worker'].queryset = SocialWorker.objects.order_by(
            'last_name', 'first_name',
        )
        self.fields['social_worker'].label = 'Социальный работник'
        self.fields['briefing_title'].label = 'Название инструктажа'
        self.fields['briefing_date'].label = 'Дата инструктажа (план / факт)'
        self.fields['briefing_date'].input_formats = [
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
        ]
        self.fields['passed'].label = 'Инструктаж уже пройден'
        self.fields['passed'].required = False
        if not self.instance.pk:
            self.fields['passed'].initial = True
        self.fields['notes'].label = 'Примечание'


class WorkloadRecordForm(forms.ModelForm):
    """Ввод строки учёта нагрузки; отработанное время, коэффициент и ставка считаются автоматически."""

    class Meta:
        model = WorkloadRecord
        fields = [
            'social_worker',
            'recipient',
            'location',
            'housing_type',
            'period_year',
            'period_month',
            'visits_per_week',
            'visits_per_month',
            'visit_duration_minutes',
            'work_time_norm_minutes',
            'notes',
        ]
        help_texts = {
            'visits_per_month': 'Необязательно: если пусто — кратность за месяц = за неделю × 4.',
            'work_time_norm_minutes': 'Справочное поле (мин/мес). Коэффициент нагрузки в таблице всегда считается как отработано (часы) ÷ 168 ч.',
        }
        widgets = {
            'social_worker': forms.Select(
                attrs={'class': 'form-select js-wl-social-worker', 'id': 'id_social_worker'},
            ),
            'recipient': forms.Select(
                attrs={'class': 'form-select js-wl-recipient', 'id': 'id_recipient'},
            ),
            'location': forms.Select(
                attrs={'class': 'form-select js-wl-location', 'id': 'id_location'},
            ),
            'housing_type': forms.Select(
                attrs={'class': 'form-select js-wl-housing', 'id': 'id_housing_type'},
            ),
            'period_year': forms.NumberInput(
                attrs={'class': 'form-control js-wl-period-y', 'min': 2000, 'max': 2100, 'id': 'id_period_year'},
            ),
            'period_month': forms.NumberInput(
                attrs={'class': 'form-control js-wl-period-m', 'min': 1, 'max': 12, 'id': 'id_period_month'},
            ),
            'visits_per_week': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': 0,
                    'id': 'id_visits_per_week',
                },
            ),
            'visits_per_month': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'visit_duration_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'work_time_norm_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['social_worker'].queryset = SocialWorker.objects.order_by('last_name', 'first_name')
        self.fields['social_worker'].label = 'Работник'
        self.fields['recipient'].queryset = ServiceRecipient.objects.select_related(
            'social_worker', 'location',
        ).order_by('last_name', 'first_name')
        self.fields['recipient'].label = 'Подопечный'
        self.fields['recipient'].required = False
        self.fields['recipient'].empty_label = '— не указан —'
        self.fields['location'].queryset = ServiceLocation.objects.order_by('name')
        self.fields['location'].label = 'Населённый пункт'
        self.fields['location'].required = False
        self.fields['location'].empty_label = '— не указан —'
        self.fields['housing_type'].label = 'Тип жилья'
        self.fields['period_year'].label = 'Год'
        self.fields['period_month'].label = 'Месяц'
        self.fields['visits_per_week'].label = 'Кратность посещений (раз в неделю)'
        self.fields['visits_per_month'].label = 'Кратность посещений (раз в месяц)'
        self.fields['visits_per_month'].required = False
        self.fields['visit_duration_minutes'].label = 'Время 1 посещения (минут)'
        self.fields['work_time_norm_minutes'].label = 'Норма рабочего времени (минут в месяц)'
        self.fields['notes'].label = 'Примечание'

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        sw = cleaned.get('social_worker')
        rec = cleaned.get('recipient')
        loc = cleaned.get('location')

        if rec and rec.social_worker_id:
            if sw and rec.social_worker_id != sw.pk:
                self.add_error(
                    'recipient',
                    'Подопечный не закреплён за выбранным сотрудником.',
                )
                return cleaned
            cleaned['social_worker'] = rec.social_worker
        if not self.errors.get('recipient') and rec and not loc and rec.location_id:
            cleaned['location'] = rec.location
        return cleaned
