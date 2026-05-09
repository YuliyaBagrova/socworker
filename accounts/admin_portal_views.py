from functools import wraps
from urllib.parse import quote, urlencode, urlparse

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from inventory.inv_user_sql import (
    inventory_staff_users_for_admin_panel,
    inv_role_code_for_user,
    inv_role_id_for_user,
    update_auth_user_inventory,
)
from inventory.permissions import INVENTORY_ACCOUNTABLE_CODE

from .admin_portal_forms import (
    AdminPortalAuthenticationForm,
    AdminPortalCreateStaffForm,
    AdminPortalRegistrationForm,
    ALLOWED_ADMIN_PORTAL_STAFF_ROLE_CODES,
)
from .admin_portal_permissions import has_admin_panel_access, user_has_admin_panel_flag
from .admin_portal_staff_queries import (
    soc_department_managers_rows_for_admin_panel,
    user_is_soc_department_manager,
)

User = get_user_model()


def _safe_admin_portal_next(request):
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts=None,
        require_https=request.is_secure(),
    ):
        return next_url
    return ''


def _safe_admin_portal_panel_return(request):
    """Только обратно на панель администратора (тот же path), чтобы избежать open redirect."""
    raw = (request.GET.get('next') or request.POST.get('next') or '').strip()
    panel_base = reverse('accounts:admin_portal_panel')
    if not raw:
        return panel_base
    panel_path = urlparse(panel_base).path.rstrip('/') or '/'
    try:
        parsed = urlparse(raw)
    except ValueError:
        return panel_base
    cand_path = (parsed.path or '').rstrip('/') or '/'
    if cand_path != panel_path:
        return panel_base
    host = {request.get_host()}
    if raw.startswith('/') and not raw.startswith('//'):
        if url_has_allowed_host_and_scheme(
            raw,
            allowed_hosts=host,
            require_https=request.is_secure(),
        ):
            return raw
        return panel_base
    if url_has_allowed_host_and_scheme(
        raw,
        allowed_hosts=host,
        require_https=request.is_secure(),
    ):
        return raw
    return panel_base


def _portal_target_role_summary(user) -> str:
    bits = []
    if user_is_soc_department_manager(user):
        bits.append('Заведующий отделением')
    for row in inventory_staff_users_for_admin_panel():
        if row.get('id') == user.pk:
            rn = (row.get('role_name') or '').strip()
            if rn:
                bits.append(rn)
            break
    seen = set()
    ordered = []
    for b in bits:
        if b not in seen:
            seen.add(b)
            ordered.append(b)
    return ' · '.join(ordered) if ordered else 'Учётная запись из панели администратора'


def admin_panel_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=reverse('accounts:admin_portal_login'),
            )
        if not has_admin_panel_access(request.user):
            messages.error(
                request,
                'У этой учётной записи нет доступа к панели администратора. '
                'Зарегистрируйтесь или войдите под учётной записью администратора портала.',
            )
            return redirect('accounts:admin_portal_login')
        return view_func(request, *args, **kwargs)

    return _wrapped


def admin_portal_login(request):
    if request.user.is_authenticated and has_admin_panel_access(request.user):
        nxt = _safe_admin_portal_next(request)
        return redirect(nxt) if nxt else redirect('accounts:admin_portal_panel')
    if request.method == 'POST':
        form = AdminPortalAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not has_admin_panel_access(user):
                messages.error(
                    request,
                    'У этой учётной записи нет доступа к панели администратора. '
                    'Обратитесь к ответственному лицу или пройдите регистрацию с кодом доступа.',
                )
            else:
                login(request, user)
                messages.success(request, f'Добро пожаловать в Панель Администратора, {user.get_username()}!')
                nxt = _safe_admin_portal_next(request)
                return redirect(nxt) if nxt else redirect('accounts:admin_portal_panel')
    else:
        form = AdminPortalAuthenticationForm(request)
    return render(request, 'accounts/admin_portal_login.html', {'form': form})


def admin_portal_register(request):
    if request.user.is_authenticated and has_admin_panel_access(request.user):
        return redirect('accounts:admin_portal_panel')
    if request.method == 'POST':
        form = AdminPortalRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                'Учётная запись создана. Вам открыт доступ к панели администратора.',
            )
            login(request, user)
            nxt = _safe_admin_portal_next(request)
            return redirect(nxt) if nxt else redirect('accounts:admin_portal_panel')
    else:
        form = AdminPortalRegistrationForm()
    return render(request, 'accounts/admin_portal_register.html', {'form': form})


def admin_portal_logout(request):
    logout(request)
    messages.info(request, 'Вы вышли из панели администратора.')
    return redirect('accounts:admin_portal_login')


def _user_is_portal_managed_target(user_id: int) -> bool:
    """
    Заведующий отделением (основное приложение) или пользователь с ролью инвентаризации,
    управляемой из этой панели (ответственный за инвентарь / руководитель отдела в inv_roles).
    """
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return False
    if user_is_soc_department_manager(user):
        return True
    code = inv_role_code_for_user(user_id)
    return bool(code and code in ALLOWED_ADMIN_PORTAL_STAFF_ROLE_CODES)


def _portal_actor_may_modify_target(actor, target_id: int, request) -> bool:
    if actor.is_superuser:
        return True
    if target_id == actor.pk:
        messages.error(request, 'Нельзя выполнить это действие над собственной учётной записью.')
        return False
    if User.objects.filter(pk=target_id, is_superuser=True).exists():
        messages.error(request, 'Действие над учётной записью суперпользователя недоступно.')
        return False
    if user_has_admin_panel_flag(target_id):
        messages.error(
            request,
            'Действие недоступно: эта учётная запись относится к другому администратору портала. '
            'Обратитесь к суперпользователю Django.',
        )
        return False
    return True


def _gv_ap(request, key: str) -> str:
    return (request.POST.get(key) or request.GET.get(key) or '').strip()


def _normalize_ap_account_status(raw: str) -> str:
    v = (raw or '').strip()
    return v if v in ('active', 'inactive') else ''


def _normalize_ap_status_sort(raw: str) -> str:
    v = (raw or '').strip()
    return v if v in ('active_first', 'inactive_first') else ''


def _admin_portal_panel_ap_state(request) -> dict:
    return {
        'q_heads': _gv_ap(request, 'q_heads'),
        'q_inv': _gv_ap(request, 'q_inv'),
        'q_other': _gv_ap(request, 'q_other'),
        'h_status': _normalize_ap_account_status(_gv_ap(request, 'h_status')),
        'h_sort': _normalize_ap_status_sort(_gv_ap(request, 'h_sort')),
        'i_status': _normalize_ap_account_status(_gv_ap(request, 'i_status')),
        'i_sort': _normalize_ap_status_sort(_gv_ap(request, 'i_sort')),
        'o_status': _normalize_ap_account_status(_gv_ap(request, 'o_status')),
        'o_sort': _normalize_ap_status_sort(_gv_ap(request, 'o_sort')),
    }


def _admin_portal_ap_url(state: dict) -> str:
    params = {k: v for k, v in state.items() if v}
    base = reverse('accounts:admin_portal_panel')
    if not params:
        return base
    return f'{base}?{urlencode(params)}'


def _admin_portal_ap_default_url(state: dict, section: str) -> str:
    drops = {
        'heads': ('q_heads', 'h_status', 'h_sort'),
        'inv': ('q_inv', 'i_status', 'i_sort'),
        'other': ('q_other', 'o_status', 'o_sort'),
    }[section]
    reduced = {k: v for k, v in state.items() if k not in drops}
    return _admin_portal_ap_url(reduced)


def _admin_portal_panel_redirect(request):
    return redirect(_admin_portal_ap_url(_admin_portal_panel_ap_state(request)))


@admin_panel_required
def admin_portal_user_delete(request, pk):
    panel_return = _safe_admin_portal_panel_return(request)
    user_obj = User.objects.filter(pk=pk).first()
    if not user_obj:
        messages.error(request, 'Пользователь не найден.')
        return redirect(panel_return)

    if not _user_is_portal_managed_target(pk):
        messages.error(
            request,
            'Удаление из этой панели доступно только для заведующих отделением '
            'и пользователей с заданными здесь ролями инвентаризации.',
        )
        return redirect(panel_return)

    if not _portal_actor_may_modify_target(request.user, pk, request):
        return redirect(panel_return)

    if request.method == 'POST':
        name = user_obj.get_username()
        try:
            user_obj.delete()
            messages.success(request, f'Учётная запись «{name}» удалена из системы.')
        except ProtectedError:
            messages.error(
                request,
                'Нельзя удалить пользователя: есть связанные записи (например, инвентарные единицы). '
                'Снимите роль или заблокируйте вход.',
            )
        return redirect(_safe_admin_portal_panel_return(request))

    return render(
        request,
        'accounts/admin_portal_user_confirm_delete.html',
        {
            'target_user': user_obj,
            'role_summary': _portal_target_role_summary(user_obj),
            'panel_return_url': panel_return,
        },
    )


def _filter_admin_portal_staff_rows(rows, query: str):
    q = (query or '').strip().lower()
    if not q:
        return list(rows)
    filtered = []
    for row in rows:
        fn = (row.get('first_name') or '').strip()
        ln = (row.get('last_name') or '').strip()
        hay = ' '.join([
            row.get('username') or '',
            row.get('email') or '',
            fn,
            ln,
            f'{ln} {fn}'.strip(),
        ]).lower()
        if q in hay:
            filtered.append(row)
    return filtered


def _apply_admin_portal_account_status_filter(rows, status_filter: str):
    rows = list(rows)
    if status_filter == 'active':
        return [r for r in rows if r.get('is_active')]
    if status_filter == 'inactive':
        return [r for r in rows if not r.get('is_active')]
    return rows


def _sort_admin_portal_rows_by_account_status(rows, sort_key: str):
    rows = list(rows)
    if sort_key == 'active_first':
        return sorted(rows, key=lambda r: not bool(r.get('is_active')))
    if sort_key == 'inactive_first':
        return sorted(rows, key=lambda r: bool(r.get('is_active')))
    return rows


def _admin_portal_pipeline_rows(rows_src, q_text: str, status_filter: str, sort_key: str):
    rows = _filter_admin_portal_staff_rows(rows_src, q_text)
    rows = _apply_admin_portal_account_status_filter(rows, status_filter)
    return _sort_admin_portal_rows_by_account_status(rows, sort_key)


@admin_panel_required
def admin_portal_panel(request):
    department_head_rows_src = soc_department_managers_rows_for_admin_panel()
    rows_all = inventory_staff_users_for_admin_panel()
    inventory_accountable_rows_src = [
        r for r in rows_all if (r.get('role_code') or '') == INVENTORY_ACCOUNTABLE_CODE
    ]
    other_inv_src = [
        r for r in rows_all if (r.get('role_code') or '') != INVENTORY_ACCOUNTABLE_CODE
    ]

    st = _admin_portal_panel_ap_state(request)
    department_head_rows = _admin_portal_pipeline_rows(
        department_head_rows_src,
        st['q_heads'],
        st['h_status'],
        st['h_sort'],
    )
    inventory_accountable_rows = _admin_portal_pipeline_rows(
        inventory_accountable_rows_src,
        st['q_inv'],
        st['i_status'],
        st['i_sort'],
    )
    other_inv_rows = _admin_portal_pipeline_rows(
        other_inv_src,
        st['q_other'],
        st['o_status'],
        st['o_sort'],
    )
    show_other_inv_panel = bool(other_inv_src)

    create_form = AdminPortalCreateStaffForm()

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        uid_raw = (request.POST.get('user_id') or '').strip()

        try:
            uid = int(uid_raw)
        except ValueError:
            uid = None

        if action == 'create_staff':
            create_form = AdminPortalCreateStaffForm(request.POST)
            if create_form.is_valid():
                create_form.save()
                messages.success(request, 'Пользователь добавлен и получил роль в системе инвентаризации.')
                return _admin_portal_panel_redirect(request)
        elif uid is not None and action == 'toggle_active':
            if not _user_is_portal_managed_target(uid):
                messages.error(
                    request,
                    'Это действие доступно только для заведующих отделением (основное приложение) '
                    'и пользователей с ролями инвентаризации, которые задаются в этой панели.',
                )
            elif _portal_actor_may_modify_target(request.user, uid, request):
                user_obj = User.objects.filter(pk=uid).first()
                if user_obj:
                    user_obj.is_active = not user_obj.is_active
                    user_obj.save(update_fields=['is_active'])
                    uname = user_obj.get_username()
                    if user_obj.is_active:
                        messages.success(
                            request,
                            f'Учётная запись «{uname}» разблокирована. Вход в систему снова разрешён.',
                        )
                    else:
                        messages.success(
                            request,
                            f'Учётная запись «{uname}» заблокирована. '
                            f'Вход в приложение для этой учётной записи запрещён.',
                            extra_tags='ap-panel-flash-dark',
                        )
                else:
                    messages.error(request, 'Пользователь не найден.')
            return _admin_portal_panel_redirect(request)

        elif uid is not None and action == 'strip_inventory':
            if inv_role_id_for_user(uid) is None:
                messages.error(
                    request,
                    'Снять роль инвентаризации можно только у пользователя, у которого она назначена.',
                )
            elif not _user_is_portal_managed_target(uid):
                messages.error(
                    request,
                    'Снятие этой роли из панели недоступно для данной учётной записи.',
                )
            elif _portal_actor_may_modify_target(request.user, uid, request):
                update_auth_user_inventory(
                    uid,
                    inv_role_id=None,
                    inv_department_id=None,
                    inv_position='',
                    inv_phone='',
                )
                messages.success(
                    request,
                    'Роль инвентаризации снята. Пользователь теряет доступ к разделу «Инвентаризация».',
                )
            return _admin_portal_panel_redirect(request)

        elif uid is not None and action == 'set_password':
            if not _user_is_portal_managed_target(uid):
                messages.error(
                    request,
                    'Смена пароля из этой панели доступна только для заведующих отделением '
                    'и пользователей с ролями инвентаризации из этой панели.',
                )
            elif _portal_actor_may_modify_target(request.user, uid, request):
                p1 = (request.POST.get('new_password') or '').strip()
                p2 = (request.POST.get('new_password_confirm') or '').strip()
                user_obj = User.objects.filter(pk=uid).first()
                if not user_obj:
                    messages.error(request, 'Пользователь не найден.')
                elif not p1 or not p2:
                    messages.error(request, 'Укажите новый пароль и подтверждение.')
                elif p1 != p2:
                    messages.error(request, 'Пароли не совпадают.')
                else:
                    try:
                        validate_password(p1, user_obj)
                    except DjangoValidationError as exc:
                        for msg in exc.messages:
                            messages.error(request, msg)
                    else:
                        user_obj.set_password(p1)
                        user_obj.save(update_fields=['password'])
                        messages.success(
                            request,
                            f'Пароль для учётной записи «{user_obj.get_username()}» изменён.',
                        )
            return _admin_portal_panel_redirect(request)

    seen_pw = set()
    password_pick_users = []
    for r in list(department_head_rows_src) + list(inventory_accountable_rows_src):
        uid = r.get('id')
        if uid is None or uid in seen_pw:
            continue
        seen_pw.add(uid)
        uname = r.get('username') or ''
        fn = (r.get('first_name') or '').strip()
        ln = (r.get('last_name') or '').strip()
        display = ' '.join(x for x in [ln, fn] if x).strip()
        label = uname if not display else f'{uname} — {display}'
        password_pick_users.append({'id': uid, 'username': uname, 'label': label})

    heads_filtered = bool(st['q_heads'] or st['h_status'] or st['h_sort'])
    inv_filtered = bool(st['q_inv'] or st['i_status'] or st['i_sort'])
    other_filtered = bool(st['q_other'] or st['o_status'] or st['o_sort'])

    heads_empty_message = (
        'Нет записей по заданным условиям.'
        if heads_filtered and department_head_rows_src and not department_head_rows
        else 'Нет таких учётных записей.'
    )
    inv_empty_message = (
        'Нет записей по заданным условиям.'
        if inv_filtered and inventory_accountable_rows_src and not inventory_accountable_rows
        else 'Нет пользователей с ролью ответственного за инвентарь.'
    )
    other_empty_message = (
        'Нет записей по заданным условиям.'
        if other_filtered and other_inv_src and not other_inv_rows
        else 'Нет записей.'
    )

    return render(
        request,
        'accounts/admin_portal_panel.html',
        {
            'department_head_rows': department_head_rows,
            'inventory_accountable_rows': inventory_accountable_rows,
            'other_inv_rows': other_inv_rows,
            'show_other_inv_panel': show_other_inv_panel,
            'create_form': create_form,
            'password_pick_users': password_pick_users,
            **st,
            'heads_filter_default_url': _admin_portal_ap_default_url(st, 'heads'),
            'inv_filter_default_url': _admin_portal_ap_default_url(st, 'inv'),
            'other_filter_default_url': _admin_portal_ap_default_url(st, 'other'),
            'heads_empty_message': heads_empty_message,
            'inv_empty_message': inv_empty_message,
            'other_empty_message': other_empty_message,
            'admin_portal_panel_return_enc': quote(_admin_portal_ap_url(st), safe=''),
        },
    )
