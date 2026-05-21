from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Value, When
from accounts.belarus_phone import BY_PHONE_EXAMPLE, normalize_belarus_phone
from accounts.forms import CustomAuthenticationForm, CustomUserCreationForm
from accounts.portal_auth_codes import get_inventory_authentication_code

from .inv_user_sql import (
    inv_inventory_fields_for_user,
    inv_role_code_for_user,
    inv_role_id_for_user,
    update_auth_user_inventory,
    user_ids_with_inv_role_assigned,
    user_ids_with_inv_role_id,
)
from .models import Department, InvRole, InventoryUnit
from .permissions import INVENTORY_ACCOUNTABLE_CODE

User = get_user_model()


class InventoryUnitForm(forms.ModelForm):
    class Meta:
        model = InventoryUnit
        fields = ['inventory_number', 'name', 'cost', 'responsible', 'equipment_photo']
        widgets = {
            'inventory_number': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'responsible': forms.Select(attrs={'class': 'form-select'}),
            'equipment_photo': forms.ClearableFileInput(
                attrs={'class': 'form-control inv-unit-file-input', 'accept': 'image/*'}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        self.fields['inventory_number'].label = 'Инвентарный номер'
        self.fields['name'].label = 'Название'
        self.fields['cost'].label = 'Стоимость'
        self.fields['equipment_photo'].label = 'Фото техники'
        self.fields['equipment_photo'].required = False
        self.fields['responsible'].label = 'Ответственный'

        if user is None:
            accountable = InvRole.objects.filter(code=INVENTORY_ACCOUNTABLE_CODE).first()
            exclude_pks = user_ids_with_inv_role_id(accountable.pk) if accountable else set()
            qs = User.objects.filter(is_active=True)
            if exclude_pks:
                qs = qs.exclude(pk__in=exclude_pks)
            self.fields['responsible'].queryset = qs.order_by(
                'last_name', 'first_name', 'username'
            )
            return

        accountable = InvRole.objects.filter(code=INVENTORY_ACCOUNTABLE_CODE).first()
        exclude_pks = user_ids_with_inv_role_id(accountable.pk) if accountable else set()
        qs = User.objects.filter(is_active=True)
        if exclude_pks:
            qs = qs.exclude(pk__in=exclude_pks)
        if self.instance and self.instance.pk and self.instance.responsible_id:
            qs = (qs | User.objects.filter(pk=self.instance.responsible_id)).distinct()

        qs = (
            qs.annotate(
                _me_first=Case(
                    When(pk=user.pk, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by('_me_first', 'last_name', 'first_name', 'username')
        )
        self.fields['responsible'].queryset = qs

        u = user

        def _label_from_instance(obj):
            name = (obj.get_full_name() or '').strip() or obj.username
            if obj.pk == u.pk:
                return f'Вы — {name} ({obj.username})'
            return f'{name} ({obj.username})'

        self.fields['responsible'].label_from_instance = _label_from_instance

    def clean_responsible(self):
        responsible = self.cleaned_data.get('responsible')
        user = self._user
        if user is None:
            return responsible
        if responsible is None:
            return responsible
        allowed = set(self.fields['responsible'].queryset.values_list('pk', flat=True))
        if responsible.pk not in allowed:
            raise forms.ValidationError(
                'Выберите пользователя из списка. Учётные записи, созданные только через регистрацию '
                'в разделе «Инвентаризация», в списке не отображаются.'
            )
        return responsible

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self._user is not None and not obj.pk:
            obj.created_by = self._user
        if commit:
            obj.save()
        return obj


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'head']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'head': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Название отделения'
        self.fields['head'].label = 'Руководитель отделения'
        ids = user_ids_with_inv_role_assigned()
        self.fields['head'].queryset = User.objects.filter(pk__in=ids).order_by('last_name', 'first_name', 'username')
        self.fields['head'].required = False


class InventoryAuthenticationForm(CustomAuthenticationForm):
    """Вход в раздел «Инвентаризация»: email, пароль и секретный код (выдаётся начальником)."""

    access_code = forms.CharField(
        label='Код аутентификации',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
        }),
    )

    def clean(self):
        code = (self.data.get('access_code') or '').strip()
        expected = get_inventory_authentication_code()
        if code != expected:
            raise ValidationError('Неверный код аутентификации.')
        return super().clean()


class InventoryRegistrationForm(CustomUserCreationForm):
    """Регистрация для доступа к инвентаризации; роль «Ответственный за инвентарь» в inv_roles / auth_user."""

    access_code = forms.CharField(
        label='Код аутентификации',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'off',
        }),
    )

    def clean_access_code(self):
        code = (self.cleaned_data.get('access_code') or '').strip()
        expected = get_inventory_authentication_code()
        if code != expected:
            raise ValidationError('Неверный код аутентификации.')
        return code

    def save(self, commit=True):
        user = super().save(commit=commit)
        role, _created = InvRole.objects.get_or_create(
            code=INVENTORY_ACCOUNTABLE_CODE,
            defaults={'name': 'Ответственный за инвентарь'},
        )
        update_auth_user_inventory(
            user.pk,
            inv_role_id=role.pk,
            inv_department_id=None,
            inv_position='',
            inv_phone='',
        )
        if inv_role_id_for_user(user.pk) != role.pk:
            raise RuntimeError(
                'Роль в справочнике есть, но поле inv_role_id в auth_user не обновилось. '
                'Проверьте БД и миграции inventory (таблица auth_user, MySQL).'
            )
        return user


class AssignInventoryAccountableForm(forms.Form):
    """Назначить существующему пользователю роль «Ответственный за инвентарь»."""

    user = forms.ModelChoiceField(
        label='Пользователь системы',
        queryset=User.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.order_by(
            'last_name', 'first_name', 'username'
        )

    def save(self):
        target = self.cleaned_data['user']
        role, _ = InvRole.objects.get_or_create(
            code=INVENTORY_ACCOUNTABLE_CODE,
            defaults={'name': 'Ответственный за инвентарь'},
        )
        dept_id, pos, phone = inv_inventory_fields_for_user(target.pk)
        update_auth_user_inventory(
            target.pk,
            inv_role_id=role.pk,
            inv_department_id=dept_id,
            inv_position=pos,
            inv_phone=phone,
        )
        return target


class InventoryStaffForm(forms.Form):
    """Создание пользователя с полями инвентаризации (логин/пароль в auth_user)."""

    username = forms.CharField(label='Логин', max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    password1 = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    password2 = forms.CharField(
        label='Пароль ещё раз',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    full_name = forms.CharField(label='ФИО', max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    position = forms.CharField(label='Должность', max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    department = forms.ModelChoiceField(
        label='Отделение',
        queryset=Department.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    role = forms.ModelChoiceField(
        label='Роль',
        queryset=InvRole.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control js-belarus-phone',
            'placeholder': BY_PHONE_EXAMPLE,
            'maxlength': '22',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = InvRole.objects.all().order_by('code')
        if user is not None and not user.is_superuser:
            actor_code = inv_role_code_for_user(user.pk)
            if actor_code == INVENTORY_ACCOUNTABLE_CODE:
                qs = InvRole.objects.filter(code=INVENTORY_ACCOUNTABLE_CODE).order_by('code')
        self.fields['role'].queryset = qs

    def clean_username(self):
        u = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('Пользователь с таким логином уже есть.')
        return u

    def clean_phone(self):
        return normalize_belarus_phone(self.cleaned_data.get('phone') or '')

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Пароли не совпадают.')
        if p1:
            validate_password(p1)
        return data

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data['username'],
            password=data['password1'],
            email='',
        )
        dept = data.get('department')
        role = data['role']
        parts = (data.get('full_name') or '').strip().split(None, 1)
        if len(parts) >= 2:
            ln, fn = parts[0], parts[1]
        elif parts:
            ln, fn = parts[0], ''
        else:
            ln, fn = '', ''
        update_auth_user_inventory(
            user.pk,
            inv_role_id=role.pk,
            inv_department_id=dept.pk if dept else None,
            inv_position=(data.get('position') or '').strip(),
            inv_phone=(data.get('phone') or '').strip(),
            last_name=ln,
            first_name=fn,
        )
        return user
