from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from accounts.belarus_phone import BY_PHONE_EXAMPLE, normalize_belarus_phone

from .inv_user_sql import (
    inv_department_id_for_user,
    update_auth_user_inventory,
    user_ids_in_department_or_self,
    user_ids_with_inv_role_assigned,
)
from .models import Department, InvRole, InventoryUnit
from .permissions import inventory_role

User = get_user_model()


class InventoryUnitForm(forms.ModelForm):
    class Meta:
        model = InventoryUnit
        fields = ['inventory_number', 'name', 'cost', 'responsible']
        widgets = {
            'inventory_number': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'responsible': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        self.fields['inventory_number'].label = 'Инвентарный номер'
        self.fields['name'].label = 'Название'
        self.fields['cost'].label = 'Стоимость'
        self.fields['responsible'].label = 'Ответственный (пользователь)'
        if user is None:
            self.fields['responsible'].queryset = User.objects.order_by('username')
            return
        role = inventory_role(user)
        if role == 'warehouse_keeper':
            self.fields['responsible'].queryset = User.objects.order_by('username')
        elif role == 'department_head':
            dept_id = inv_department_id_for_user(user.pk)
            if dept_id:
                ids = user_ids_in_department_or_self(dept_id, user.pk)
                self.fields['responsible'].queryset = (
                    User.objects.filter(pk__in=ids).order_by('username')
                )
            else:
                self.fields['responsible'].queryset = User.objects.filter(pk=user.pk).order_by('username')
        else:
            del self.fields['responsible']

    def clean_responsible(self):
        responsible = self.cleaned_data.get('responsible')
        user = self._user
        if user is None:
            return responsible
        role = inventory_role(user)
        if role == 'department_head':
            dept_id = inv_department_id_for_user(user.pk)
            if not dept_id:
                if responsible != user:
                    raise forms.ValidationError('Укажите себя как ответственного или закрепите отделение в профиле.')
                return responsible
            r_dept = inv_department_id_for_user(responsible.pk)
            ok = responsible.pk == user.pk or (r_dept is not None and r_dept == dept_id)
            if not ok:
                raise forms.ValidationError('Ответственный должен быть из вашего отделения.')
        return responsible

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self._user is not None and inventory_role(self._user) == 'employee':
            obj.responsible = self._user
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
        queryset=InvRole.objects.all(),
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

