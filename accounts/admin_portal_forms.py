from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .admin_password_audit import store_plaintext_password_for_admin_panel
from .forms import CustomAuthenticationForm, CustomUserCreationForm
from .portal_auth_codes import get_admin_panel_authentication_code
from accounts.models import UserProfile
from inventory.forms import InventoryStaffForm
from inventory.inv_user_sql import update_auth_user_inventory
from inventory.models import InvRole

User = get_user_model()

ALLOWED_ADMIN_PORTAL_STAFF_ROLE_CODES = ('inventory_accountable', 'department_head')


class AdminPortalAuthenticationForm(CustomAuthenticationForm):
    """Вход в панель администратора: email, пароль и код (выдаётся ответственным лицом)."""

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
        expected = get_admin_panel_authentication_code()
        if code != expected:
            raise ValidationError('Неверный код аутентификации для панели администратора.')
        return super().clean()


class AdminPortalRegistrationForm(CustomUserCreationForm):
    """Регистрация доступа к панели администратора (без роли инвентаризации в auth_user)."""

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
        expected = get_admin_panel_authentication_code()
        if code != expected:
            raise ValidationError('Неверный код аутентификации для панели администратора.')
        return code

    def save(self, commit=True):
        user = super().save(commit=commit)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.admin_panel_access = True
        profile.save(update_fields=['admin_panel_access', 'updated_at'])
        return user


class AdminPortalCreateStaffForm(InventoryStaffForm):
    """
    Создание пользователя с ролью инвентаризации — только «Ответственный за инвентарь»
    или «Руководитель отдела» (заведующий отделением).
    """

    def __init__(self, *args, **kwargs):
        kwargs.pop('user', None)
        super().__init__(*args, user=None, **kwargs)
        self.fields['role'].queryset = InvRole.objects.filter(
            code__in=ALLOWED_ADMIN_PORTAL_STAFF_ROLE_CODES,
        ).order_by('name')
        del self.fields['department']
        del self.fields['phone']

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data['username'],
            password=data['password1'],
            email='',
        )
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
            inv_department_id=None,
            inv_position=(data.get('position') or '').strip(),
            inv_phone='',
            last_name=ln,
            first_name=fn,
        )
        store_plaintext_password_for_admin_panel(user, data['password1'])
        return user
