from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import (
    SocialWorker,
    ServiceRecipient,
    ServiceLocation,
    PlannedVisit,
    VisitTaskReminder,
    SafetyBriefingRecord,
)
from .visit_schedule import validate_visit_frequency_and_days


class CustomUserCreationForm(UserCreationForm):
    """Форма регистрации пользователя"""
    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите email'
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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    """Форма входа пользователя"""
    username = forms.CharField(
        label='Имя пользователя',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите имя пользователя',
            'autofocus': True
        })
    )
    password = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите пароль'
        })
    )

    error_messages = {
        'invalid_login': 'Неверное имя пользователя или пароль.',
        'inactive': 'Этот аккаунт неактивен.',
    }


class SocialWorkerForm(forms.ModelForm):
    """Форма для создания и редактирования социального работника"""
    
    class Meta:
        model = SocialWorker
        fields = [
            'first_name', 'last_name', 'middle_name',
            'birth_date', 'phone', 'address',
            'medical_checkup', 'last_medical_checkup_date', 'medical_checkup_planned_date',
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
            'birth_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+7 (999) 123-45-67'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Введите адрес'
            }),
            'medical_checkup': forms.Select(attrs={
                'class': 'form-select'
            }),
            'last_medical_checkup_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'medical_checkup_planned_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select'
            }),
            'employee_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Табельный номер'
            }),
            'hire_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Дополнительные примечания'
            }),
        }


class ServiceRecipientForm(forms.ModelForm):
    """Форма для создания и редактирования получателя услуг"""

    class Meta:
        model = ServiceRecipient
        fields = [
            'employee_id', 'first_name', 'last_name', 'middle_name',
            'birth_date', 'phone', 'address', 'disability_group',
            'payment_percent', 'visit_frequency', 'living_status',
            'admission_date', 'visit_days', 'fire_detector_count',
            'social_worker', 'location', 'notes'
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
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+7 (999) 123-45-67'
            }),
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
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Дополнительные примечания'
            }),
        }

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
    """Явная запись визита на дату (дополняет график по карточке подопечного)."""

    class Meta:
        model = PlannedVisit
        fields = ['social_worker', 'recipient', 'visit_date', 'visit_time', 'notes']
        widgets = {
            'social_worker': forms.Select(attrs={'class': 'form-select'}),
            'recipient': forms.Select(attrs={'class': 'form-select'}),
            'visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'visit_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['social_worker'].queryset = SocialWorker.objects.order_by(
            'last_name', 'first_name',
        )
        self.fields['social_worker'].label = 'Сотрудник из базы'
        self.fields['recipient'].queryset = ServiceRecipient.objects.filter(
            social_worker__isnull=False,
        ).select_related('social_worker').order_by('last_name', 'first_name')
        self.fields['recipient'].label = 'Подопечный'
        self.fields['visit_date'].label = 'Дата визита'
        self.fields['visit_time'].label = 'Время (необязательно)'
        self.fields['notes'].label = 'Примечание'

    def clean_recipient(self):
        r = self.cleaned_data['recipient']
        if not r.social_worker_id:
            raise ValidationError('У подопечного должен быть закреплён социальный работник.')
        return r

    def clean(self):
        cleaned = super().clean()
        r = cleaned.get('recipient')
        d = cleaned.get('visit_date')
        if r and d:
            qs = PlannedVisit.objects.filter(recipient=r, visit_date=d)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError(
                    'На эту дату для выбранного подопечного уже есть запланированный визит.',
                )
        return cleaned


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
            'briefing_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
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
        self.fields['passed'].label = 'Инструктаж уже пройден'
        self.fields['passed'].required = False
        if not self.instance.pk:
            self.fields['passed'].initial = True
        self.fields['notes'].label = 'Примечание'
