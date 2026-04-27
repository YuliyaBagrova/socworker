import csv
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DepartmentForm, InventoryStaffForm, InventoryUnitForm
from .inv_user_sql import (
    inv_department_id_for_user,
    responsible_row_for_csv,
    staff_rows_for_template,
    user_ids_in_department_or_self,
)
from .models import Department, InventoryUnit
from .permissions import (
    can_create_inventory_unit,
    can_manage_inventory,
    has_inventory_access,
    inventory_role,
)


def inventory_access_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not has_inventory_access(request.user):
            return render(request, 'inventory/no_access.html', status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


def _units_for_user(user):
    qs = InventoryUnit.objects.select_related('responsible').order_by('inventory_number')
    role = inventory_role(user)
    if role == 'warehouse_keeper':
        return qs
    if role == 'department_head':
        dept_id = inv_department_id_for_user(user.pk)
        if not dept_id:
            return qs.none()
        ids = user_ids_in_department_or_self(dept_id, user.pk)
        return qs.filter(responsible_id__in=ids)
    return qs.filter(responsible=user)


def _report_filename(user):
    role = inventory_role(user)
    if role == 'warehouse_keeper':
        return 'inventory_report_org.csv'
    if role == 'department_head':
        return 'inventory_report_department.csv'
    return 'inventory_report_my.csv'


@inventory_access_required
def panel(request):
    n_units = _units_for_user(request.user).count()
    return render(
        request,
        'inventory/panel.html',
        {
            'n_units': n_units,
        },
    )


@inventory_access_required
def unit_list(request):
    units = _units_for_user(request.user)
    return render(
        request,
        'inventory/unit_list.html',
        {
            'units': units,
        },
    )


@inventory_access_required
def unit_create(request):
    if not can_create_inventory_unit(request.user):
        messages.error(request, 'Недостаточно прав для создания единицы учёта.')
        return redirect('inventory:unit_list')
    if request.method == 'POST':
        form = InventoryUnitForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Единица учёта сохранена.')
            return redirect('inventory:unit_list')
    else:
        form = InventoryUnitForm(user=request.user)
    return render(
        request,
        'inventory/unit_form.html',
        {'form': form, 'is_edit': False},
    )


@inventory_access_required
def unit_edit(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, 'Только завхоз может редактировать единицы.')
        return redirect('inventory:unit_list')
    obj = get_object_or_404(InventoryUnit, pk=pk)
    if request.method == 'POST':
        form = InventoryUnitForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Изменения сохранены.')
            return redirect('inventory:unit_list')
    else:
        form = InventoryUnitForm(instance=obj, user=request.user)
    return render(
        request,
        'inventory/unit_form.html',
        {'form': form, 'is_edit': True, 'unit': obj},
    )


@inventory_access_required
def unit_delete(request, pk):
    if not can_manage_inventory(request.user):
        messages.error(request, 'Только завхоз может удалять единицы.')
        return redirect('inventory:unit_list')
    obj = get_object_or_404(InventoryUnit, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.info(request, 'Единица удалена.')
        return redirect('inventory:unit_list')
    return render(request, 'inventory/unit_confirm_delete.html', {'unit': obj})


@inventory_access_required
def report_csv(request):
    units = _units_for_user(request.user)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{_report_filename(request.user)}"'
    response.write('\ufeff')
    w = csv.writer(
        response,
        delimiter=';',
        quoting=csv.QUOTE_MINIMAL,
        lineterminator='\r\n',
    )
    w.writerow([
        'Инвентарный номер',
        'Название',
        'Стоимость',
        'Ответственный (логин)',
        'ФИО ответственного',
        'Отделение ответственного',
    ])
    for u in units:
        name, dept = responsible_row_for_csv(u.responsible_id)
        w.writerow([
            u.inventory_number,
            u.name,
            str(u.cost),
            u.responsible.username,
            name,
            dept,
        ])
    return response


@inventory_access_required
def department_list(request):
    if not can_manage_inventory(request.user):
        messages.error(request, 'Управление отделениями доступно только завхозу.')
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
        messages.error(request, 'Список учётных записей инвентаризации доступен только завхозу.')
        return redirect('inventory:panel')
    staff_rows = staff_rows_for_template()
    return render(request, 'inventory/staff_list.html', {'staff_rows': staff_rows})


@inventory_access_required
def staff_create(request):
    if not can_manage_inventory(request.user):
        return redirect('inventory:panel')
    if request.method == 'POST':
        form = InventoryStaffForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Пользователь создан. Можно выдать роль и закрепить в отделении.')
            return redirect('inventory:staff_list')
    else:
        form = InventoryStaffForm()
    return render(request, 'inventory/staff_form.html', {'form': form})
