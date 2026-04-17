from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from accounts.belarus_phone import BY_PHONE_EXAMPLE, normalize_belarus_phone

from .models import Department, InventoryProfile, InventoryUnit
from .permissions import inventory_role


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
            prof = getattr(user, 'inventory_profile', None)
            dept_id = prof.department_id if prof else None
            if dept_id:
                self.fields['responsible'].queryset = (
                    User.objects.filter(
                        Q(pk=user.pk) | Q(inventory_profile__department_id=dept_id),
                    )
                    .distinct()
                    .order_by('username')
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
            prof = getattr(user, 'inventory_profile', None)
            dept_id = prof.department_id if prof else None
            if not dept_id:
                if responsible != user:
                    raise forms.ValidationError('Укажите себя как ответственного или закрепите отделение в профиле.')
                return responsible
            r_prof = getattr(responsible, 'inventory_profile', None)
            ok = responsible.pk == user.pk or (
                r_prof is not None and r_prof.department_id == dept_id
            )
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
        self.fields['head'].queryset = User.objects.filter(
            inventory_profile__isnull=False,
        ).order_by('inventory_profile__full_name', 'username')
        self.fields['head'].required = False


class InventoryStaffForm(forms.Form):
    """Создание пользователя с профилем инвентаризации (логин/пароль в User)."""

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
    role = forms.ChoiceField(
        label='Роль',
        choices=InventoryProfile.ROLE_CHOICES,
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
        profile = InventoryProfile.objects.create(
            user=user,
            full_name=data['full_name'].strip(),
            position=(data.get('position') or '').strip(),
            department=data.get('department'),
            role=data['role'],
            phone=(data.get('phone') or '').strip(),
        )
        profile.sync_user_names()
        return user, profile
