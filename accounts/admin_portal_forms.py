from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from accounts.forms import CustomAuthenticationForm, CustomUserCreationForm
from accounts.models import UserProfile
from inventory.forms import InventoryStaffForm
from inventory.models import InvRole

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
        expected = getattr(settings, 'ADMIN_PANEL_AUTHENTICATION_CODE', 'administrator')
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
        expected = getattr(settings, 'ADMIN_PANEL_AUTHENTICATION_CODE', 'administrator')
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
