from functools import wraps
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import (
    AssignInventoryAccountableForm,
    DepartmentForm,
    InventoryAuthenticationForm,
    InventoryRegistrationForm,
    InventoryStaffForm,
    InventoryUnitForm,
)

from accounts.admin_password_audit import remember_plaintext_password_if_missing_for_panel_tables
from accounts.models import UserProfile

from .inv_user_sql import staff_rows_for_template
from .models import Department, InventoryUnit
from .permissions import (
    can_create_inventory_unit,
    can_manage_inventory,
    can_modify_inventory_unit,
    has_inventory_access,
)


def _safe_inventory_auth_next(request):
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts=None,
        require_https=request.is_secure(),
    ):
        return next_url
    return ''


def inventory_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=reverse('inventory:login'),
            )
        if not has_inventory_access(request.user):
            return render(request, 'inventory/no_access.html', status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


def inventory_login(request):
    if request.user.is_authenticated and has_inventory_access(request.user):
        nxt = _safe_inventory_auth_next(request)
        return redirect(nxt) if nxt else redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not has_inventory_access(user):
                messages.error(
                    request,
                    'У этой учётной записи нет доступа к инвентаризации. '
                    'Обратитесь к ответственному за инвентарь или зарегистрируйтесь.',
                )
            else:
                login(request, user)
                messages.success(request, f'Добро пожаловать, {user.get_username()}!')
                nxt = _safe_inventory_auth_next(request)
                return redirect(nxt) if nxt else redirect('inventory:panel')
    else:
        form = InventoryAuthenticationForm(request)
    return render(request, 'inventory/inventory_login.html', {'form': form})


def inventory_register(request):
    if request.user.is_authenticated and has_inventory_access(request.user):
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except RuntimeError as e:
                messages.error(request, str(e))
            else:
                remember_plaintext_password_if_missing_for_panel_tables(
                    user, form.cleaned_data.get('password1') or '',
                )
                messages.success(
                    request,
                    'Учётная запись создана. Вам назначена роль «Ответственный за инвентарь».',
                )
                login(request, user)
                nxt = _safe_inventory_auth_next(request)
                return redirect(nxt) if nxt else redirect('inventory:panel')
    else:
        form = InventoryRegistrationForm()
    return render(request, 'inventory/inventory_register.html', {'form': form})


def inventory_logout(request):
    logout(request)
    messages.info(request, 'Вы вышли из раздела «Инвентаризация».')
    return redirect('inventory:login')


def public_inventory_responsible_list(request):
    """Публичный список ответственных и закреплённого за ними инвентаря (без авторизации в разделе)."""
    units = list(
        InventoryUnit.objects.select_related('responsible').order_by(
            'responsible__last_name',
            'responsible__first_name',
            'responsible__username',
            'inventory_number',
        )
    )
    user_ids = {u.responsible_id for u in units if u.responsible_id}
    avatar_by_user_id = {}
    if user_ids:
        for prof in UserProfile.objects.filter(user_id__in=user_ids).only(
            'user_id',
            'avatar',
        ):
            if prof.avatar:
                avatar_by_user_id[prof.user_id] = prof.avatar.url

    responsible_groups = []
    for _, grp in groupby(units, key=lambda u: u.responsible_id):
        chunk = list(grp)
        if chunk:
            uid = chunk[0].responsible_id
            responsible_groups.append(
                {
                    'user': chunk[0].responsible,
                    'units': chunk,
                    'avatar_url': avatar_by_user_id.get(uid),
                },
            )
    return render(
        request,
        'inventory/responsible_public_list.html',
        {'responsible_groups': responsible_groups},
    )


@inventory_access_required
def assign_inventory_accountable(request):
    if not can_manage_inventory(request.user):
        messages.error(
            request,
            'Назначать ответственных могут только завхоз или ответственный за инвентарь.',
        )
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = AssignInventoryAccountableForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Пользователю назначена роль «Ответственный за инвентарь».',
            )
            return redirect('inventory:staff_list')
    else:
        form = AssignInventoryAccountableForm()
    return render(request, 'inventory/assign_accountable.html', {'form': form})


def _all_inventory_units():
    return InventoryUnit.objects.select_related('responsible').order_by('inventory_number')


def _panel_filter_users():
    User = get_user_model()
    return User.objects.order_by('last_name', 'first_name', 'username')


@inventory_access_required
def panel(request):
    qs = InventoryUnit.objects.select_related('responsible').all()
    responsible_raw = (request.GET.get('responsible') or '').strip()
    name_raw = (request.GET.get('name') or '').strip()
    sort_order = (request.GET.get('sort') or 'inv_asc').strip()

    if responsible_raw.isdigit():
        qs = qs.filter(responsible_id=int(responsible_raw))

    if name_raw:
        qs = qs.filter(
            Q(name__icontains=name_raw) | Q(inventory_number__icontains=name_raw)
        )

    if sort_order == 'name_asc':
        qs = qs.order_by('name', 'inventory_number')
    elif sort_order == 'resp_asc':
        qs = qs.order_by(
            'responsible__last_name',
            'responsible__first_name',
            'responsible__username',
            'inventory_number',
        )
    elif sort_order == 'inv_desc':
        qs = qs.order_by('-inventory_number')
    elif sort_order == 'cost_desc':
        qs = qs.order_by('-cost', 'inventory_number')
    elif sort_order == 'cost_asc':
        qs = qs.order_by('cost', 'inventory_number')
    else:
        qs = qs.order_by('inventory_number')

    units = list(qs)
    editable_ids = {u.pk for u in units if can_modify_inventory_unit(request.user, u)}
    _valid_sorts = (
        'inv_asc',
        'inv_desc',
        'name_asc',
        'resp_asc',
        'cost_desc',
        'cost_asc',
    )
    filter_sort_norm = sort_order if sort_order in _valid_sorts else 'inv_asc'
    return render(
        request,
        'inventory/panel.html',
        {
            'n_units': InventoryUnit.objects.count(),
            'units': units,
            'inventory_editable_unit_ids': editable_ids,
            'filter_users': _panel_filter_users(),
            'filter_responsible': responsible_raw,
            'filter_name': name_raw,
            'filter_sort': filter_sort_norm,
        },
    )


@inventory_access_required
def unit_list(request):
    return redirect('inventory:panel')


@inventory_access_required
def unit_detail(request, pk):
    unit = get_object_or_404(
        InventoryUnit.objects.select_related('responsible', 'created_by'),
        pk=pk,
    )
    return render(
        request,
        'inventory/unit_detail.html',
        {
            'unit': unit,
            'inventory_can_edit_unit': can_modify_inventory_unit(request.user, unit),
        },
    )


@inventory_access_required
def unit_create(request):
    if not can_create_inventory_unit(request.user):
        messages.error(request, 'Недостаточно прав для создания единицы учёта.')
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryUnitForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Единица учёта сохранена.')
            return redirect('inventory:panel')
    else:
        form = InventoryUnitForm(user=request.user)
    return render(
        request,
        'inventory/unit_form.html',
        {'form': form, 'is_edit': False},
    )


@inventory_access_required
def unit_edit(request, pk):
    obj = get_object_or_404(InventoryUnit, pk=pk)
    if not can_modify_inventory_unit(request.user, obj):
        messages.error(
            request,
            'Редактирование недоступно: запись создана другим пользователем с вашей ролью инвентаризации.',
        )
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryUnitForm(request.POST, request.FILES, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Изменения сохранены.')
            return redirect('inventory:panel')
    else:
        form = InventoryUnitForm(instance=obj, user=request.user)
    return render(
        request,
        'inventory/unit_form.html',
        {'form': form, 'is_edit': True, 'unit': obj},
    )


@inventory_access_required
def unit_delete(request, pk):
    obj = get_object_or_404(InventoryUnit, pk=pk)
    if not can_modify_inventory_unit(request.user, obj):
        messages.error(
            request,
            'Удаление недоступно: запись создана другим пользователем с вашей ролью инвентаризации.',
        )
        return redirect('inventory:panel')
    if request.method == 'POST':
        obj.delete()
        messages.info(request, 'Единица удалена.')
        return redirect('inventory:panel')
    return render(request, 'inventory/unit_confirm_delete.html', {'unit': obj})


@inventory_access_required
def unit_photo_upload(request, pk):
    if request.method != 'POST':
        return redirect('inventory:panel')
    obj = get_object_or_404(InventoryUnit, pk=pk)
    if not can_modify_inventory_unit(request.user, obj):
        messages.error(
            request,
            'Загрузка фото недоступна: запись создана другим пользователем с вашей ролью инвентаризации.',
        )
        return redirect('inventory:panel')
    uploaded = request.FILES.get('equipment_photo')
    if not uploaded:
        messages.warning(request, 'Выберите файл изображения.')
        return redirect('inventory:panel')
    if uploaded.size > 5 * 1024 * 1024:
        messages.error(request, 'Размер файла не более 5 МБ.')
        return redirect('inventory:panel')
    ct = (getattr(uploaded, 'content_type', None) or '').lower()
    allowed_ct = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    if ct and ct not in allowed_ct:
        messages.error(request, 'Допустимы только изображения (JPEG, PNG, WebP, GIF).')
        return redirect('inventory:panel')
    if not ct:
        name = (getattr(uploaded, 'name', '') or '').lower()
        if not any(name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            messages.error(request, 'Допустимы только файлы изображений.')
            return redirect('inventory:panel')
    if obj.equipment_photo:
        obj.equipment_photo.delete(save=False)
    obj.equipment_photo = uploaded
    obj.save()
    messages.success(request, 'Фото техники сохранено.')
    return redirect('inventory:panel')


@inventory_access_required
def report_csv(request):
    """Совместимость со старыми ссылкам; выгрузка через единый обработчик CSV."""
    return redirect('accounts:report_csv', report_type='inventory')


@inventory_access_required
def department_list(request):
    if not can_manage_inventory(request.user):
        messages.error(
            request, 'Управление отделениями доступно только завхозу или ответственному за инвентарь.'
        )
        return redirect('inventory:panel')
    departments = Department.objects.select_related('head').order_by('name')
    return render(request, 'inventory/department_list.html', {'departments': departments})


@inventory_access_required
def department_create(request):
    if not can_manage_inventory(request.user):
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Отделение создано.')
            return redirect('inventory:department_list')
    else:
        form = DepartmentForm()
    return render(request, 'inventory/department_form.html', {'form': form, 'is_edit': False})


@inventory_access_required
def department_edit(request, pk):
    if not can_manage_inventory(request.user):
        return redirect('inventory:panel')
    obj = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Отделение обновлено.')
            return redirect('inventory:department_list')
    else:
        form = DepartmentForm(instance=obj)
    return render(request, 'inventory/department_form.html', {'form': form, 'is_edit': True, 'department': obj})


@inventory_access_required
def staff_list(request):
    if not can_manage_inventory(request.user):
        messages.error(
            request, 'Список учётных записей инвентаризации доступен только завхозу или ответственному за инвентарь.'
        )
        return redirect('inventory:panel')
    staff_rows = staff_rows_for_template()
    return render(request, 'inventory/staff_list.html', {'staff_rows': staff_rows})


@inventory_access_required
def staff_create(request):
    if not can_manage_inventory(request.user):
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryStaffForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Пользователь создан. Можно выдать роль и закрепить в отделении.')
            return redirect('inventory:staff_list')
    else:
        form = InventoryStaffForm(user=request.user)
    return render(request, 'inventory/staff_form.html', {'form': form})
