import io
import os
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, date, timedelta
from urllib.parse import quote, urlencode

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import IntegerField, Q
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.utils.html import strip_tags

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    SocialWorkerForm,
    MedicalCheckupEditForm,
    ServiceRecipientForm,
    ServiceLocationForm,
    PlannedVisitForm,
    VisitTaskReminderForm,
    SafetyBriefingRecordForm,
    UserProfileAvatarForm,
)
from .models import (
    SocialWorker,
    ServiceRecipient,
    ServiceLocation,
    PlannedVisit,
    VisitTaskReminder,
    SafetyBriefingRecord,
    UserProfile,
    WorkloadRecord,
)
from .tab_numbering import compact_service_recipient_employee_ids, compact_social_worker_employee_ids
from .visit_schedule import (
    RU_MONTHS,
    RU_WEEKDAYS_SHORT,
    add_months,
    calendar_month_grid,
    plan_day_entries,
    ru_month_year,
    validate_visit_frequency_and_days,
    visit_weekday_flags,
    visits_per_week_from_frequency,
    week_start_monday,
)

from inventory.permissions import has_inventory_access

MEDICAL_CHECKUP_VALID_DAYS = 365


def _apply_tab_employee_sort(qs, sort_order):
    """
    Сортировка списков с полем employee_id: по таб. № как по числу (1,2,…,10),
    затем фамилия и имя. Нецифровые табельные номера в MySQL дают 0 при CAST.
    """
    if sort_order == 'tab_asc':
        return qs.annotate(
            _tab_sort_num=Cast('employee_id', IntegerField()),
        ).order_by('_tab_sort_num', 'last_name', 'first_name')
    if sort_order == 'tab_desc':
        return qs.annotate(
            _tab_sort_num=Cast('employee_id', IntegerField()),
        ).order_by('-_tab_sort_num', 'last_name', 'first_name')
    return qs.order_by('last_name', 'first_name')


def _apply_social_worker_related_tab_sort(qs, sort_order, prefix='social_worker', extra=()):
    """
    Сортировка queryset по полям закреплённого SocialWorker (таб. № как число, ФИО).
    extra — доп. поля порядка (например '-briefing_date', 'pk' для записей ТБ).
    """
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'
    ln, fn = f'{prefix}__last_name', f'{prefix}__first_name'
    emp = f'{prefix}__employee_id'
    if sort_order == 'tab_asc':
        return qs.annotate(
            _sw_rel_tab=Cast(emp, IntegerField()),
        ).order_by('_sw_rel_tab', ln, fn, *extra)
    if sort_order == 'tab_desc':
        return qs.annotate(
            _sw_rel_tab=Cast(emp, IntegerField()),
        ).order_by('-_sw_rel_tab', ln, fn, *extra)
    return qs.order_by(ln, fn, *extra)


def _export_plain_text(value, max_len=500):
    """Текст для PDF/CSV: без HTML, одна строка по возможности."""
    if not value:
        return '—'
    t = strip_tags(str(value)).strip()
    if not t:
        return '—'
    t = ' '.join(t.split())
    if len(t) > max_len:
        return t[: max_len - 1] + '…'
    return t


def _recipient_location_export_label(recipient):
    """Населённый пункт для PDF/CSV (как в карточке получателя)."""
    loc = getattr(recipient, 'location', None)
    if loc:
        return f'{loc.get_location_type_display()} {loc.name}'.strip()
    return '—'


def _inventory_responsible_export_cell(user):
    """Ответственный в одной колонке — как в таблице панели инвентаризации."""
    if getattr(user, 'last_name', None) or getattr(user, 'first_name', None):
        name = f'{user.last_name or ""} {user.first_name or ""}'.strip()
        return f'{name} ({user.username})'
    return user.username


def _report_tab_sort_param(request):
    """Сортировка списков соцработников/получателей для PDF/CSV (как на экране)."""
    raw = request.POST.get('sort')
    if not raw:
        raw = request.GET.get('sort') or request.GET.get('rec_sort') or 'surname'
    if raw not in ('tab_asc', 'tab_desc', 'surname'):
        return 'surname'
    return raw


def _inventory_report_order_qs(qs, sort_order: str):
    """Тот же порядок строк, что на панели инвентаризации."""
    so = (sort_order or 'inv_asc').strip()
    valid = frozenset({
        'inv_asc', 'inv_desc', 'name_asc', 'resp_asc', 'cost_desc', 'cost_asc',
    })
    if so not in valid:
        so = 'inv_asc'
    if so == 'name_asc':
        return qs.order_by('name', 'inventory_number')
    if so == 'resp_asc':
        return qs.order_by(
            'responsible__last_name',
            'responsible__first_name',
            'responsible__username',
            'inventory_number',
        )
    if so == 'inv_desc':
        return qs.order_by('-inventory_number')
    if so == 'cost_desc':
        return qs.order_by('-cost', 'inventory_number')
    if so == 'cost_asc':
        return qs.order_by('cost', 'inventory_number')
    return qs.order_by('inventory_number')


def _register_fonts():
    """Register a Cyrillic-capable font; fall back to Helvetica if unavailable."""
    font_name = 'CyrFont'
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    candidates = [
        os.path.join(os.path.dirname(__file__), 'fonts', 'arial.ttf'),
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/calibri.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        if os.path.isfile(path):
            pdfmetrics.registerFont(TTFont(font_name, path))
            return font_name
    return 'Helvetica'


def register_view(request):
    """Страница регистрации"""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Аккаунт успешно создан для {user.username}!')
            login(request, user)
            return redirect('accounts:dashboard')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    """Страница входа"""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Добро пожаловать, {user.username}!')
            next_url = request.GET.get('next', 'accounts:dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Неверное имя пользователя или пароль.')
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'accounts/login.html', {'form': form})


@login_required
def logout_view(request):
    """Выход из системы"""
    logout(request)
    messages.info(request, 'Вы успешно вышли из системы.')
    return redirect('accounts:login')


@login_required
def dashboard_view(request):
    """Главная страница после входа: статистика, напоминания, запланированные визиты."""
    user = request.user
    today = date.today()
    dash_year = today.year
    dash_month = today.month

    def _dash_initials(u):
        fn = (u.first_name or '').strip()
        ln = (u.last_name or '').strip()
        if ln and fn:
            return (ln[0] + fn[0]).upper()
        if ln:
            return ln[:2].upper()
        if fn:
            return fn[:2].upper()
        em = (u.email or '').strip()
        if em:
            return em[:2].upper()
        return (u.username or '?')[:2].upper()

    profile = UserProfile.objects.filter(user_id=user.pk).first()

    worker_count = SocialWorker.objects.count()
    worker_active_count = SocialWorker.objects.filter(status='active').count()
    location_count = ServiceLocation.objects.count()
    recipient_count = ServiceRecipient.objects.count()

    planned_visits_month = PlannedVisit.objects.filter(
        visit_date__year=dash_year,
        visit_date__month=dash_month,
    ).count()

    week_end = today + timedelta(days=6)
    tasks_week_count = VisitTaskReminder.objects.filter(
        task_date__gte=today,
        task_date__lte=week_end,
    ).count()

    workload_rows_month = WorkloadRecord.objects.filter(
        period_year=dash_year,
        period_month=dash_month,
    ).count()

    planning_today_count = (
        PlannedVisit.objects.filter(visit_date=today).count()
        + VisitTaskReminder.objects.filter(task_date=today).count()
    )

    med_threshold = today - timedelta(days=MEDICAL_CHECKUP_VALID_DAYS)
    medical_overdue_count = SocialWorker.objects.filter(
        medical_panel_registered=True,
    ).filter(
        Q(last_medical_checkup_date__isnull=True)
        | Q(last_medical_checkup_date__lt=med_threshold)
    ).count()

    try:
        from inventory.models import InventoryUnit

        inventory_units_count = InventoryUnit.objects.count()
    except Exception:
        inventory_units_count = None

    dash_reminders = _visit_planning_active_reminders(today, None, None, None)[:25]

    upcoming_visits = list(
        PlannedVisit.objects.filter(visit_date__gte=today)
        .select_related('recipient', 'social_worker')
        .order_by('visit_date', 'visit_time', 'pk')[:15]
    )

    recent_workload = list(
        WorkloadRecord.objects.select_related('social_worker', 'recipient')
        .order_by('-updated_at')[:8]
    )

    return render(request, 'accounts/dashboard.html', {
        'user': user,
        'dash_user_profile': profile,
        'dash_initials': _dash_initials(user),
        'dash_today': today,
        'dash_year': dash_year,
        'dash_month': dash_month,
        'worker_count': worker_count,
        'worker_active_count': worker_active_count,
        'location_count': location_count,
        'recipient_count': recipient_count,
        'planned_visits_month': planned_visits_month,
        'tasks_week_count': tasks_week_count,
        'workload_rows_month': workload_rows_month,
        'planning_today_count': planning_today_count,
        'medical_overdue_count': medical_overdue_count,
        'inventory_units_count': inventory_units_count,
        'dash_reminders': dash_reminders,
        'upcoming_visits': upcoming_visits,
        'recent_workload': recent_workload,
    })


def profile_interface_role(request):
    """Подпись роли на «О пользователе»: администратор, управляющий инвентарём или заведующий."""
    user = request.user
    if user.is_staff or user.is_superuser:
        return {'label': 'Администратор', 'variant': 'admin'}
    if has_inventory_access(user):
        return {'label': 'Управляющий инвентарём', 'variant': 'inventory'}
    return {'label': 'Заведующий отделением', 'variant': 'department'}


def _user_avatar_initials(user):
    fn = (user.first_name or '').strip()
    ln = (user.last_name or '').strip()
    if fn and ln:
        return (fn[0] + ln[0]).upper()
    if fn:
        return (fn[:2] if len(fn) >= 2 else fn).upper()
    if ln:
        return (ln[:2] if len(ln) >= 2 else ln).upper()
    un = (user.username or '?').strip()
    return un[:2].upper()


@login_required
def profile_view(request):
    """Страница «О пользователе»: профиль, загрузка фото, быстрые ссылки."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    initials = _user_avatar_initials(request.user)

    if request.method == 'POST':
        if request.POST.get('clear_avatar'):
            if profile.avatar:
                profile.avatar.delete(save=False)
                profile.avatar = None
                profile.save()
            messages.success(request, 'Фото профиля удалено.')
            return redirect('accounts:profile')
        if request.POST.get('save_avatar'):
            if not request.FILES.get('avatar'):
                messages.warning(request, 'Выберите файл изображения (JPG, PNG, WebP или GIF, до 2 МБ).')
                avatar_form = UserProfileAvatarForm(instance=profile)
            else:
                form = UserProfileAvatarForm(request.POST, request.FILES, instance=profile)
                if form.is_valid():
                    form.save()
                    messages.success(request, 'Фото профиля сохранено.')
                    return redirect('accounts:profile')
                avatar_form = form
        else:
            avatar_form = UserProfileAvatarForm(instance=profile)
    else:
        avatar_form = UserProfileAvatarForm(instance=profile)

    role = profile_interface_role(request)
    return render(request, 'accounts/profile.html', {
        'user': request.user,
        'socworker_profile': profile,
        'avatar_form': avatar_form,
        'avatar_initials': initials,
        'profile_role_label': role['label'],
        'profile_role_variant': role['variant'],
    })


# Представления для управления социальными работниками
@login_required
def social_workers_list(request):
    """Список социальных работников"""
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    sort_order = request.GET.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'

    workers = SocialWorker.objects.all()

    # Поиск
    if search_query:
        workers = workers.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(middle_name__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Фильтр по статусу
    if status_filter:
        workers = workers.filter(status=status_filter)

    # Сортировка (как в выпадающем списке на панели)
    workers = _apply_tab_employee_sort(workers, sort_order)

    # Пагинация
    paginator = Paginator(workers, 10)  # 10 работников на страницу
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'sort_order': sort_order,
        'has_active_filters': bool(search_query or status_filter),
        'status_choices': SocialWorker.STATUS_CHOICES,
    }

    return render(request, 'accounts/social_workers_list.html', context)


@login_required
def medical_checkup_panel(request):
    """Таблица сотрудников: годовая актуальность медосмотра, назначение даты."""
    worker_filter = request.GET.get('worker', '')
    status_filter = request.GET.get('status', '')
    sort_order = request.GET.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'

    workers = SocialWorker.objects.filter(medical_panel_registered=True)
    if worker_filter and str(worker_filter).isdigit():
        workers = workers.filter(pk=int(worker_filter))
    if status_filter:
        workers = workers.filter(status=status_filter)

    workers = _apply_tab_employee_sort(workers, sort_order)
    paginator = Paginator(workers, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    today = date.today()
    for w in page_obj:
        if w.last_medical_checkup_date:
            valid_until = w.last_medical_checkup_date + timedelta(days=MEDICAL_CHECKUP_VALID_DAYS)
            w.mc_valid_until = valid_until
            w.mc_is_current_year_ok = valid_until >= today
            w.mc_days_overdue = (today - valid_until).days if valid_until < today else 0
        else:
            w.mc_valid_until = None
            w.mc_is_current_year_ok = False
            w.mc_days_overdue = None

    query = ''
    if request.GET:
        query = urlencode(
            {k: v for k, v in request.GET.items() if k != 'page' and v},
            doseq=True,
        )

    assignable_workers = SocialWorker.objects.filter(
        medical_panel_registered=False,
    ).order_by('last_name', 'first_name')

    return render(request, 'accounts/medical_checkup_panel.html', {
        'page_obj': page_obj,
        'filter_worker': worker_filter if (worker_filter and str(worker_filter).isdigit()) else '',
        'status_filter': status_filter,
        'sort_order': sort_order,
        'has_active_filters': bool(
            (worker_filter and str(worker_filter).isdigit())
            or status_filter
            or sort_order != 'surname',
        ),
        'status_choices': SocialWorker.STATUS_CHOICES,
        'all_workers': SocialWorker.objects.filter(
            medical_panel_registered=True,
        ).order_by('last_name', 'first_name'),
        'assignable_workers': assignable_workers,
        'page_query': query,
        'medical_panel_back': request.get_full_path(),
        'medical_panel_back_quoted': quote(request.get_full_path(), safe='/'),
    })


@login_required
def medical_checkup_mark_passed(request):
    if request.method != 'POST':
        return redirect('accounts:medical_checkup_panel')
    pk = request.POST.get('worker_pk')
    if not pk or not str(pk).isdigit():
        messages.error(request, 'Не указан сотрудник.')
        return redirect('accounts:medical_checkup_panel')
    worker = get_object_or_404(SocialWorker, pk=int(pk))
    if not worker.medical_panel_registered:
        messages.warning(
            request,
            'Этот сотрудник не в таблице панели медосмотра.',
        )
        next_q = request.POST.get('next', '')
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:medical_checkup_panel')
    passed_str = request.POST.get('passed_on', '').strip()
    try:
        passed_on = date.fromisoformat(passed_str) if passed_str else date.today()
    except ValueError:
        passed_on = date.today()
    worker.last_medical_checkup_date = passed_on
    worker.medical_checkup = 'passed'
    worker.medical_checkup_planned_date = None
    worker.save(update_fields=[
        'last_medical_checkup_date', 'medical_checkup',
        'medical_checkup_planned_date', 'updated_at',
    ])
    messages.success(
        request,
        f'Отмечено прохождение медосмотра: {worker.get_full_name()} ({passed_on.strftime("%d.%m.%Y")}).',
    )
    next_q = request.POST.get('next', '')
    if next_q.startswith('/') and not next_q.startswith('//'):
        return redirect(next_q)
    return redirect('accounts:medical_checkup_panel')


@login_required
def medical_checkup_clear_mark(request):
    """Снять отметку о прохождении (дата и статус «не пройден»); назначенная дата не трогается."""
    if request.method != 'POST':
        return redirect('accounts:medical_checkup_panel')
    pk = request.POST.get('worker_pk')
    if not pk or not str(pk).isdigit():
        messages.error(request, 'Не указан сотрудник.')
        return redirect('accounts:medical_checkup_panel')
    worker = get_object_or_404(SocialWorker, pk=int(pk))
    if not worker.medical_panel_registered:
        messages.warning(
            request,
            'Этот сотрудник не в таблице панели медосмотра.',
        )
        next_q = request.POST.get('next', '')
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:medical_checkup_panel')
    worker.last_medical_checkup_date = None
    worker.medical_checkup = 'not_passed'
    worker.save(update_fields=[
        'last_medical_checkup_date', 'medical_checkup', 'updated_at',
    ])
    messages.success(
        request,
        f'Отметка о прохождении медосмотра снята: {worker.get_full_name()}.',
    )
    next_q = request.POST.get('next', '')
    if next_q.startswith('/') and not next_q.startswith('//'):
        return redirect(next_q)
    return redirect('accounts:medical_checkup_panel')


@login_required
def medical_checkup_assign(request):
    """Страница «Назначить медосмотр»: добавление сотрудника в панель (полный набор полей)."""
    assignable_workers = SocialWorker.objects.filter(
        medical_panel_registered=False,
    ).order_by('last_name', 'first_name')
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if request.method == 'POST':
        pk = request.POST.get('worker_pk', '').strip()
        if not pk or not str(pk).isdigit():
            messages.error(request, 'Выберите сотрудника.')
            form = MedicalCheckupEditForm(request.POST)
            return render(request, 'accounts/medical_checkup_assign.html', {
                'assign_medical_form': form,
                'assignable_workers': assignable_workers,
                'next_url': next_q,
            })
        worker = get_object_or_404(SocialWorker, pk=int(pk))
        if worker.medical_panel_registered:
            messages.warning(
                request,
                f'Сотрудник {worker.get_full_name()} уже есть в таблице панели медосмотра.',
            )
            form = MedicalCheckupEditForm(request.POST)
            return render(request, 'accounts/medical_checkup_assign.html', {
                'assign_medical_form': form,
                'assignable_workers': assignable_workers,
                'next_url': next_q,
            })
        today = date.today()
        form = MedicalCheckupEditForm(request.POST)
        if form.is_valid():
            _apply_medical_checkup_edit(worker, form.cleaned_data, today)
            worker.medical_panel_registered = True
            worker.save(update_fields=[
                'last_medical_checkup_date', 'medical_checkup',
                'medical_checkup_planned_date', 'medical_notes',
                'medical_panel_registered', 'updated_at',
            ])
            messages.success(
                request,
                f'Сотрудник {worker.get_full_name()} добавлен в панель медосмотра.',
            )
            if next_q.startswith('/') and not next_q.startswith('//'):
                return redirect(next_q)
            return redirect('accounts:medical_checkup_panel')
        messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
        return render(request, 'accounts/medical_checkup_assign.html', {
            'assign_medical_form': form,
            'assignable_workers': assignable_workers,
            'next_url': next_q,
        })

    form = MedicalCheckupEditForm()
    return render(request, 'accounts/medical_checkup_assign.html', {
        'assign_medical_form': form,
        'assignable_workers': assignable_workers,
        'next_url': next_q,
    })


@login_required
def medical_checkup_remove_from_panel(request, pk):
    """Подтверждение и снятие сотрудника с учёта в панели медосмотра (без удаления карточки)."""
    worker = get_object_or_404(SocialWorker, pk=pk)
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if not worker.medical_panel_registered:
        messages.warning(
            request,
            'Этот сотрудник уже не отображается в панели медосмотра.',
        )
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:medical_checkup_panel')

    if request.method == 'POST':
        name = worker.get_full_name()
        worker.medical_panel_registered = False
        worker.save(update_fields=['medical_panel_registered', 'updated_at'])
        compact_social_worker_employee_ids()
        messages.success(
            request,
            f'{name} убран из панели прохождения медосмотра.',
        )
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:medical_checkup_panel')

    return render(request, 'accounts/medical_checkup_remove_confirm.html', {
        'worker': worker,
        'next_url': next_q,
    })


def _apply_medical_checkup_edit(worker, cleaned, today):
    """Заполняет поля медосмотра из MedicalCheckupEditForm.cleaned_data."""
    valid_days = MEDICAL_CHECKUP_VALID_DAYS
    medical_checkup = cleaned['medical_checkup']
    last_date = cleaned.get('last_medical_checkup_date')
    valid_until = cleaned.get('valid_until')
    mc_ok_12 = (cleaned.get('mc_ok_12') or '').strip()
    planned = cleaned.get('medical_checkup_planned_date')
    notes = cleaned.get('medical_notes')
    if notes is not None:
        notes = notes.strip()
    else:
        notes = ''

    last = None
    if valid_until:
        last = valid_until - timedelta(days=valid_days)
    if last is None and last_date:
        last = last_date

    if mc_ok_12 == 'yes':
        if last is not None:
            vu = last + timedelta(days=valid_days)
            if vu < today:
                last = today - timedelta(days=valid_days - 1)
    elif mc_ok_12 == 'no':
        if last is not None:
            vu = last + timedelta(days=valid_days)
            if vu >= today:
                last = today - timedelta(days=valid_days + 1)

    worker.last_medical_checkup_date = last
    worker.medical_checkup = medical_checkup
    worker.medical_checkup_planned_date = planned
    worker.medical_notes = notes or None


@login_required
def medical_checkup_edit(request, pk):
    """Страница «Изменить информацию о медосмотре» для выбранного сотрудника."""
    worker = get_object_or_404(SocialWorker, pk=pk)
    if not worker.medical_panel_registered:
        messages.warning(
            request,
            'Этот сотрудник не в таблице панели медосмотра. Сначала нажмите «Назначить медосмотр».',
        )
        return redirect('accounts:medical_checkup_panel')
    today = date.today()
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if request.method == 'POST':
        form = MedicalCheckupEditForm(request.POST)
        if form.is_valid():
            _apply_medical_checkup_edit(worker, form.cleaned_data, today)
            worker.save(update_fields=[
                'last_medical_checkup_date', 'medical_checkup',
                'medical_checkup_planned_date', 'medical_notes', 'updated_at',
            ])
            messages.success(
                request,
                f'Данные медосмотра сохранены: {worker.get_full_name()}.',
            )
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect('accounts:medical_checkup_panel')
        messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        vu = None
        if worker.last_medical_checkup_date:
            vu = worker.last_medical_checkup_date + timedelta(days=MEDICAL_CHECKUP_VALID_DAYS)
        mc_ok = ''
        if worker.last_medical_checkup_date:
            mc_ok = 'yes' if vu >= today else 'no'
        initial = {
            'medical_checkup': (
                'passed' if worker.medical_checkup in ('passed', 'expired') else 'not_passed'
            ),
            'last_medical_checkup_date': worker.last_medical_checkup_date,
            'valid_until': vu,
            'mc_ok_12': mc_ok,
            'medical_checkup_planned_date': worker.medical_checkup_planned_date,
            'medical_notes': worker.medical_notes or '',
        }
        form = MedicalCheckupEditForm(initial=initial)

    return render(request, 'accounts/medical_checkup_edit.html', {
        'worker': worker,
        'form': form,
        'next_url': next_url,
    })


@login_required
def safety_briefing_panel(request):
    """Панель техники безопасности: инструктажи, статус прохождения, действия."""
    worker_filter = request.GET.get('worker', '')
    title_q = request.GET.get('title', '').strip()
    sort_order = request.GET.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'

    records = SafetyBriefingRecord.objects.select_related('social_worker').all()
    if worker_filter and str(worker_filter).isdigit():
        records = records.filter(social_worker_id=int(worker_filter))
    if title_q:
        records = records.filter(briefing_title__icontains=title_q)

    records = _apply_social_worker_related_tab_sort(
        records, sort_order, 'social_worker', ('-briefing_date', 'pk'),
    )
    paginator = Paginator(records, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    query = ''
    if request.GET:
        query = urlencode(
            {k: v for k, v in request.GET.items() if k != 'page' and v},
            doseq=True,
        )

    return render(request, 'accounts/safety_briefing_panel.html', {
        'page_obj': page_obj,
        'filter_worker': worker_filter if (worker_filter and str(worker_filter).isdigit()) else '',
        'filter_title': title_q,
        'sort_order': sort_order,
        'has_active_filters': bool(
            (worker_filter and str(worker_filter).isdigit())
            or title_q
            or sort_order != 'surname',
        ),
        'all_workers': SocialWorker.objects.order_by('last_name', 'first_name'),
        'page_query': query,
        'panel_back': request.get_full_path(),
        'safety_panel_back_quoted': quote(request.get_full_path(), safe='/'),
    })


@login_required
def safety_briefing_add(request):
    """Страница «Новая запись об инструктаже» — полноэкранная форма, как «Назначить медосмотр»."""
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if request.method == 'POST':
        form = SafetyBriefingRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Запись об инструктаже добавлена.')
            if next_q.startswith('/') and not next_q.startswith('//'):
                return redirect(next_q)
            return redirect('accounts:safety_briefing_panel')
        messages.error(request, 'Исправьте ошибки в форме.')
    else:
        form = SafetyBriefingRecordForm()

    return render(request, 'accounts/safety_briefing_add.html', {
        'briefing_form': form,
        'next_url': next_q,
    })


@login_required
def safety_briefing_edit(request, pk):
    """Страница редактирования записи журнала техники безопасности (дата, статус, примечание)."""
    rec = get_object_or_404(
        SafetyBriefingRecord.objects.select_related('social_worker'),
        pk=pk,
    )
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if request.method == 'POST':
        form = SafetyBriefingRecordForm(request.POST, instance=rec)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Запись об инструктаже сохранена: «{rec.briefing_title}» ({rec.social_worker.get_full_name()}).',
            )
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect('accounts:safety_briefing_panel')
        messages.error(request, 'Исправьте ошибки в форме.')
    else:
        form = SafetyBriefingRecordForm(instance=rec)

    return render(request, 'accounts/safety_briefing_edit.html', {
        'record': rec,
        'form': form,
        'next_url': next_url,
    })


@login_required
def safety_briefing_delete(request, pk):
    record = get_object_or_404(
        SafetyBriefingRecord.objects.select_related('social_worker'),
        pk=pk,
    )
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if request.method == 'POST':
        title = record.briefing_title
        name = record.social_worker.get_full_name()
        record.delete()
        compact_social_worker_employee_ids()
        messages.success(
            request,
            f'Запись об инструктаже «{title}» ({name}) удалена.',
        )
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:safety_briefing_panel')

    return render(request, 'accounts/safety_briefing_delete_confirm.html', {
        'record': record,
        'next_url': next_q,
    })


@login_required
def safety_briefing_mark_passed(request, pk):
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    rec = get_object_or_404(SafetyBriefingRecord, pk=pk)
    passed_str = request.POST.get('briefing_date', '').strip()
    if passed_str:
        try:
            rec.briefing_date = date.fromisoformat(passed_str)
        except ValueError:
            rec.briefing_date = date.today()
    else:
        # Как «Прошёл» на панели медосмотра: дата подтверждения — сегодня
        rec.briefing_date = date.today()
    rec.passed = True
    rec.save(update_fields=['briefing_date', 'passed'])
    messages.success(
        request,
        f'Отмечено прохождение инструктажа «{rec.briefing_title}» для {rec.social_worker.get_full_name()}.',
    )
    next_url = request.POST.get('next', '')
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('accounts:safety_briefing_panel')


@login_required
def safety_briefing_clear_passed(request, pk):
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    rec = get_object_or_404(SafetyBriefingRecord, pk=pk)
    rec.passed = False
    rec.save(update_fields=['passed'])
    messages.success(
        request,
        f'Отметка о прохождении снята: «{rec.briefing_title}», {rec.social_worker.get_full_name()}.',
    )
    next_url = request.POST.get('next', '')
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('accounts:safety_briefing_panel')


@login_required
def social_worker_create(request):
    """Создание нового социального работника"""
    if request.method == 'POST':
        form = SocialWorkerForm(request.POST)
        if form.is_valid():
            worker = form.save()
            messages.success(request, f'Социальный работник {worker.get_full_name()} успешно добавлен!')
            return redirect('accounts:social_workers_list')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = SocialWorkerForm()
    
    return render(request, 'accounts/social_worker_form.html', {
        'form': form,
        'title': 'Добавить социального работника',
        'button_text': 'Добавить',
        'is_edit': False,
    })


@login_required
def social_worker_detail(request, pk):
    """Детальная информация о социальном работнике"""
    worker = get_object_or_404(SocialWorker, pk=pk)
    return render(request, 'accounts/social_worker_detail.html', {
        'worker': worker
    })


@login_required
def social_worker_edit(request, pk):
    """Редактирование социального работника"""
    worker = get_object_or_404(SocialWorker, pk=pk)

    if request.method == 'POST':
        form = SocialWorkerForm(request.POST, instance=worker)
        if form.is_valid():
            worker = form.save()
            messages.success(request, f'Информация о {worker.get_full_name()} успешно обновлена!')
            return redirect('accounts:social_worker_detail', pk=worker.pk)
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = SocialWorkerForm(instance=worker)

    return render(request, 'accounts/social_worker_form.html', {
        'form': form,
        'worker': worker,
        'title': 'Редактировать социального работника',
        'button_text': 'Сохранить изменения',
        'is_edit': True,
    })


@login_required
def social_worker_delete(request, pk):
    """Удаление социального работника"""
    worker = get_object_or_404(SocialWorker, pk=pk)
    
    if request.method == 'POST':
        worker_name = worker.get_full_name()
        worker.delete()
        messages.success(request, f'Социальный работник {worker_name} успешно удален!')
        return redirect('accounts:social_workers_list')
    
    return render(request, 'accounts/social_worker_confirm_delete.html', {
        'worker': worker
    })


# Представления для управления получателями услуг
@login_required
def recipients_list(request):
    """Список получателей услуг"""
    search_query = request.GET.get('search', '')
    living_filter = request.GET.get('living', '')
    # rec_sort — основной параметр; sort — для совместимости со старыми ссылками
    sort_order = request.GET.get('rec_sort') or request.GET.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'

    recipients = ServiceRecipient.objects.select_related('social_worker').all()

    if search_query:
        recipients = recipients.filter(
            Q(employee_id__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(middle_name__icontains=search_query) |
            Q(address__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    if living_filter:
        recipients = recipients.filter(living_status=living_filter)

    recipients = _apply_tab_employee_sort(recipients, sort_order)

    paginator = Paginator(recipients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'living_filter': living_filter,
        'sort_order': sort_order,
        'has_active_filters': bool(search_query or living_filter),
        'living_choices': ServiceRecipient.LIVING_STATUS_CHOICES,
    }
    return render(request, 'accounts/recipients_list.html', context)


def _visit_planning_active_reminders(today, wid, living, wstatus):
    """
    Окно «за 2 дня»: показ задач и визитов с датой от сегодня до сегодня+2 включительно
    (в первый день окна до выполнения ровно 2 дня).
    """
    remind_end = today + timedelta(days=2)
    manual = VisitTaskReminder.objects.filter(
        task_date__gte=today,
        task_date__lte=remind_end,
    ).select_related('social_worker', 'recipient')
    if wid and str(wid).isdigit():
        manual = manual.filter(social_worker_id=int(wid))
    if living:
        manual = manual.filter(
            Q(recipient__living_status=living) | Q(recipient__isnull=True)
        )
    if wstatus:
        manual = manual.filter(social_worker__status=wstatus)
    manual = manual.filter(
        Q(recipient__isnull=True) | Q(recipient__visit_planning_panel_registered=True),
    )

    planned = PlannedVisit.objects.filter(
        visit_date__gte=today,
        visit_date__lte=remind_end,
        recipient__visit_planning_panel_registered=True,
    ).select_related('social_worker', 'recipient')
    if wid and str(wid).isdigit():
        planned = planned.filter(social_worker_id=int(wid))
    if living:
        planned = planned.filter(recipient__living_status=living)
    if wstatus:
        planned = planned.filter(social_worker__status=wstatus)

    rows = []
    for m in manual:
        rows.append({
            'kind': 'manual',
            'task_date': m.task_date,
            'social_worker': m.social_worker,
            'recipient': m.recipient,
            'description': (m.description or '').strip() or '—',
            'manual': m,
            'planned_visit': None,
        })
    for p in planned:
        note = (p.notes or '').strip()
        desc = note or f'Запланированный визит: {p.recipient.get_full_name()}'
        rows.append({
            'kind': 'planned',
            'task_date': p.visit_date,
            'social_worker': p.social_worker,
            'recipient': p.recipient,
            'description': desc,
            'manual': None,
            'planned_visit': p,
        })
    rows.sort(key=lambda x: (
        x['task_date'],
        x['social_worker'].last_name or '',
        x['social_worker'].first_name or '',
        x['kind'],
        x['description'][:40],
    ))
    return rows


def _planned_visit_vpw_hint(form):
    """Число «визитов в неделю» по полю кратности (для подсказки в форме)."""
    if form.is_bound:
        freq = form.data.get('recipient_visit_frequency') or form.fields['recipient_visit_frequency'].initial or '2'
    else:
        freq = form.fields['recipient_visit_frequency'].initial or '2'
    return visits_per_week_from_frequency(str(freq))


@login_required
def visit_planning(request):
    """Планирование визитов: таблица, календарь, списки, таймлайн; фильтры; выходные."""
    tab = request.GET.get('tab', 'table')
    if tab not in ('table', 'calendar', 'list', 'timeline'):
        tab = 'table'
    cal_view = request.GET.get('cal', 'month')
    if cal_view not in ('day', 'week', 'month', 'year'):
        cal_view = 'month'
    ref_str = request.GET.get('ref')
    ref_date = date.today()
    if ref_str:
        try:
            ref_date = date.fromisoformat(ref_str)
        except ValueError:
            pass

    sort_order = request.GET.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'

    recipients = ServiceRecipient.objects.filter(
        social_worker__isnull=False,
        visit_planning_panel_registered=True,
    ).select_related('social_worker')

    wid = request.GET.get('worker')
    if wid and str(wid).isdigit():
        recipients = recipients.filter(social_worker_id=int(wid))
    living = request.GET.get('living')
    if living:
        recipients = recipients.filter(living_status=living)
    wstatus = request.GET.get('wstatus')
    if wstatus:
        recipients = recipients.filter(social_worker__status=wstatus)

    recipient_options = recipients.order_by(
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )
    rid = request.GET.get('recipient')
    if rid and str(rid).isdigit():
        recipients = recipients.filter(pk=int(rid))

    recipients = _apply_tab_employee_sort(recipients, sort_order)
    rec_list = list(recipients)
    rec_ids = [r.pk for r in rec_list]
    today = date.today()
    planned_by_date = defaultdict(list)
    upcoming_planned_by_recipient = defaultdict(list)
    all_planned_by_recipient = defaultdict(list)
    if rec_ids:
        for pv in PlannedVisit.objects.filter(recipient_id__in=rec_ids).select_related(
            'recipient', 'social_worker',
        ).order_by('visit_date', 'visit_time', 'pk'):
            planned_by_date[pv.visit_date].append(pv)
            all_planned_by_recipient[pv.recipient_id].append(pv)
            if pv.visit_date >= today:
                upcoming_planned_by_recipient[pv.recipient_id].append(pv)

    weekday_labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    def day_entries(d):
        return plan_day_entries(rec_list, d, planned_by_date)

    planning_back_url = request.get_full_path()

    rows = []
    total_visits_week = 0
    for r in rec_list:
        n = visits_per_week_from_frequency(r.visit_frequency)
        total_visits_week += n
        day_flags = visit_weekday_flags(r.visit_days)
        mismatch = validate_visit_frequency_and_days(r.visit_frequency, r.visit_days)
        upcoming_list = upcoming_planned_by_recipient[r.pk]
        all_list = all_planned_by_recipient[r.pk]
        # Для кнопок в строке: ближайший визит с сегодня и далее; иначе последний прошедший (удаление всё равно возможно)
        if upcoming_list:
            planned_visit_primary = upcoming_list[0]
        else:
            planned_visit_primary = all_list[-1] if all_list else None
        rows.append({
            'recipient': r,
            'worker': r.social_worker,
            'visits_per_week': n,
            'schedule_label': r.get_visit_frequency_display(),
            'visit_days_text': (r.visit_days or '').strip() or '—',
            'day_flags': day_flags,
            'schedule_ok': mismatch is None,
            'schedule_warn': mismatch,
            'planned_visits_upcoming': upcoming_list,
            'planned_visit_primary': planned_visit_primary,
        })

    tomorrow = today + timedelta(days=1)
    today_entries = day_entries(today)
    tomorrow_entries = day_entries(tomorrow)
    active_task_reminders = _visit_planning_active_reminders(
        today, wid, living, wstatus,
    )

    worker_ids = {r.social_worker_id for r in rec_list}
    tl_monday = week_start_monday(ref_date)
    rec_id_set = set(rec_ids)
    for i in range(7):
        for pv in planned_by_date.get(tl_monday + timedelta(days=i), ()):
            if pv.recipient_id in rec_id_set:
                worker_ids.add(pv.social_worker_id)
    worker_ids.discard(None)
    workers_tl = list(
        SocialWorker.objects.filter(pk__in=worker_ids).order_by('last_name', 'first_name')
    )
    timeline_rows = []
    for w in workers_tl:
        cells = []
        for i in range(7):
            d = tl_monday + timedelta(days=i)
            day_e = [
                e for e in day_entries(d)
                if e['worker'] and e['worker'].pk == w.pk
            ]
            cells.append({
                'date': d,
                'is_weekend': d.weekday() >= 5,
                'entries': day_e,
                'count': len(day_e),
            })
        timeline_rows.append({'worker': w, 'cells': cells})

    col_max = [0] * 7
    for row in timeline_rows:
        for i in range(7):
            col_max[i] = max(col_max[i], row['cells'][i]['count'])
    col_max = [m if m > 0 else 1 for m in col_max]
    for row in timeline_rows:
        for i, c in enumerate(row['cells']):
            c['load_ratio'] = c['count'] / col_max[i]
    timeline = timeline_rows

    timeline_columns = []
    for i in range(7):
        d = tl_monday + timedelta(days=i)
        timeline_columns.append({
            'label': RU_WEEKDAYS_SHORT[d.weekday()],
            'date': d,
            'is_weekend': d.weekday() >= 5,
        })

    all_workers = SocialWorker.objects.filter(
        recipients__visit_planning_panel_registered=True,
    ).distinct().order_by('last_name', 'first_name')

    assignable_recipients = ServiceRecipient.objects.filter(
        social_worker__isnull=False,
        visit_planning_panel_registered=False,
    ).order_by(
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )

    has_active_filters = bool(
        (wid and str(wid).isdigit())
        or (rid and str(rid).isdigit())
        or living
        or wstatus
        or sort_order != 'surname'
    )

    ctx = {
        'tab': tab,
        'cal_view': cal_view,
        'ref_date': ref_date,
        'ref_iso': ref_date.isoformat(),
        'rows': rows,
        'weekday_labels': weekday_labels,
        'total_recipients': len(rows),
        'total_visits_week': total_visits_week,
        'today': today,
        'tomorrow': tomorrow,
        'today_entries': today_entries,
        'tomorrow_entries': tomorrow_entries,
        'task_reminder_form': VisitTaskReminderForm(),
        'active_task_reminders': active_task_reminders,
        'task_reminder_count': len(active_task_reminders),
        'planning_back_url': planning_back_url,
        'planning_next_quoted': quote(request.get_full_path(), safe=''),
        'planning_back_quoted': quote(request.get_full_path(), safe='/'),
        'all_workers': all_workers,
        'assignable_recipients': assignable_recipients,
        'has_active_filters': has_active_filters,
        'recipient_options': recipient_options,
        'filter_worker': wid or '',
        'filter_recipient': rid if (rid and str(rid).isdigit()) else '',
        'filter_living': living or '',
        'filter_wstatus': wstatus or '',
        'sort_order': sort_order,
        'living_choices': ServiceRecipient.LIVING_STATUS_CHOICES,
        'worker_status_choices': SocialWorker.STATUS_CHOICES,
        'timeline': timeline,
        'timeline_columns': timeline_columns,
        'tl_week_start': tl_monday,
        'RU_MONTHS': RU_MONTHS,
        'today_is_weekend': today.weekday() >= 5,
        'tomorrow_is_weekend': tomorrow.weekday() >= 5,
        'ref_is_weekend': ref_date.weekday() >= 5,
        'today_wd': RU_WEEKDAYS_SHORT[today.weekday()],
        'tomorrow_wd': RU_WEEKDAYS_SHORT[tomorrow.weekday()],
    }

    if cal_view == 'day':
        ctx['prev_ref'] = ref_date - timedelta(days=1)
        ctx['next_ref'] = ref_date + timedelta(days=1)
        ctx['day_entries'] = day_entries(ref_date)
        ctx['cal_title'] = ref_date.strftime('%d.%m.%Y')
    elif cal_view == 'week':
        ws = week_start_monday(ref_date)
        ctx['prev_ref'] = ws - timedelta(days=7)
        ctx['next_ref'] = ws + timedelta(days=7)
        ctx['week_start'] = ws
        ctx['week_days'] = []
        for i in range(7):
            d = ws + timedelta(days=i)
            ctx['week_days'].append({
                'date': d,
                'wd_label': RU_WEEKDAYS_SHORT[d.weekday()],
                'is_weekend': d.weekday() >= 5,
                'entries': day_entries(d),
            })
        ctx['cal_title'] = (
            f'{ws.strftime("%d.%m.%Y")} — '
            f'{(ws + timedelta(days=6)).strftime("%d.%m.%Y")}'
        )
    elif cal_view == 'year':
        y = ref_date.year
        ctx['prev_ref'] = date(y - 1, 1, 1)
        ctx['next_ref'] = date(y + 1, 1, 1)
        year_months = []
        for m in range(1, 13):
            last_d = monthrange(y, m)[1]
            total_slot = 0
            for day in range(1, last_d + 1):
                dd = date(y, m, day)
                total_slot += len(day_entries(dd))
            year_months.append({
                'month': m,
                'label': RU_MONTHS[m].capitalize(),
                'total': total_slot,
            })
        ctx['year_months'] = year_months
        ctx['cal_title'] = str(y)
    elif cal_view == 'month':
        ym = ref_date.replace(day=1)
        ctx['prev_ref'] = add_months(ym, -1)
        ctx['next_ref'] = add_months(ym, 1)
        ctx['month_weeks'] = calendar_month_grid(
            ym.year, ym.month, rec_list, planned_by_date,
        )
        ctx['cal_title'] = ru_month_year(ym)
        ctx['month_ym'] = ym

    ctx['cal_view'] = cal_view
    return render(request, 'accounts/visit_planning.html', ctx)


def _safe_redirect_next(request, next_url: str):
    """Только относительный путь на том же сайте (без open redirect)."""
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('accounts:visit_planning')


@login_required
def planned_visit_create(request):
    """Новый визит для подопечного, уже учтённого в панели планирования."""
    next_url = (request.GET.get('next') or request.POST.get('next') or '').strip()
    panel_qs = ServiceRecipient.objects.filter(
        social_worker__isnull=False,
        visit_planning_panel_registered=True,
    ).select_related('social_worker').order_by('last_name', 'first_name')

    if request.method == 'GET':
        initial = {}
        rid = request.GET.get('recipient', '').strip()
        if rid and rid.isdigit():
            r = get_object_or_404(panel_qs, pk=int(rid))
            initial = {
                'recipient': r.pk,
                'social_worker': r.social_worker_id,
                'recipient_visit_frequency': r.visit_frequency,
                'recipient_visit_days': r.visit_days or '',
            }
        form = PlannedVisitForm(
            initial=initial,
            recipient_queryset=panel_qs,
            planning_panel_short=True,
        )
        return render(request, 'accounts/planned_visit_form.html', {
            'form': form,
            'next_url': next_url,
            'title': 'Запланировать визит',
            'submit_label': 'Сохранить',
            'planned_visit': None,
            'visits_per_week_hint': _planned_visit_vpw_hint(form),
            'recipient_assign_meta': _visit_planning_panel_recipient_meta(),
        })

    form = PlannedVisitForm(
        request.POST,
        recipient_queryset=panel_qs,
        planning_panel_short=True,
    )
    if form.is_valid():
        form.save()
        messages.success(request, 'Визит запланирован.')
        return _safe_redirect_next(request, next_url)
    messages.error(request, 'Проверьте поля формы.')
    return render(request, 'accounts/planned_visit_form.html', {
        'form': form,
        'next_url': next_url,
        'title': 'Запланировать визит',
        'submit_label': 'Сохранить',
        'planned_visit': None,
        'visits_per_week_hint': _planned_visit_vpw_hint(form),
        'recipient_assign_meta': _visit_planning_panel_recipient_meta(),
    })


def _visit_planning_assignable_bundle():
    """Один проход по БД + queryset для формы (тот же порядок сортировки)."""
    order = (
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )
    lst = list(
        ServiceRecipient.objects.filter(
            social_worker__isnull=False,
            visit_planning_panel_registered=False,
        ).select_related('social_worker').order_by(*order),
    )
    meta = {
        str(r.pk): {
            'employee_id': r.employee_id or '',
            'full_name': r.get_full_name(),
            'worker_pk': str(r.social_worker_id) if r.social_worker_id else '',
            'worker_name': (
                r.social_worker.get_full_name() if r.social_worker else ''
            ),
        }
        for r in lst
    }
    if not lst:
        qs = ServiceRecipient.objects.none()
    else:
        qs = ServiceRecipient.objects.filter(
            pk__in=[r.pk for r in lst],
        ).select_related('social_worker').order_by(*order)
    return qs, meta, lst


def _visit_planning_panel_recipient_meta():
    """Подопечные в панели планирования — для подсказок № / ФИО в форме визита."""
    order = (
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )
    return {
        str(r.pk): {
            'employee_id': r.employee_id or '',
            'full_name': r.get_full_name(),
            'worker_pk': str(r.social_worker_id) if r.social_worker_id else '',
            'worker_name': (
                r.social_worker.get_full_name() if r.social_worker else ''
            ),
        }
        for r in ServiceRecipient.objects.filter(
            social_worker__isnull=False,
            visit_planning_panel_registered=True,
        ).select_related('social_worker').order_by(*order)
    }


def _recipient_meta_with_fallback(meta: dict, recipient: ServiceRecipient) -> dict:
    """Для редактирования: текущий подопечный может быть вне панели — добавить в карту."""
    out = dict(meta)
    pk = str(recipient.pk)
    if pk not in out:
        sw = recipient.social_worker
        out[pk] = {
            'employee_id': recipient.employee_id or '',
            'full_name': recipient.get_full_name(),
            'worker_pk': str(sw.pk) if sw else '',
            'worker_name': sw.get_full_name() if sw else '',
        }
    return out


@login_required
def planned_visit_assign(request):
    """Страница «Запланировать визит»: внесение подопечного в панель и первая запись визита."""
    assignable_qs, recipient_assign_meta, assignable_list = (
        _visit_planning_assignable_bundle()
    )
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    ctx_base = {
        'assignable_recipients': assignable_qs,
        'recipient_assign_meta': recipient_assign_meta,
        'next_url': next_q,
    }

    if request.method == 'POST':
        form = PlannedVisitForm(
            request.POST,
            for_panel_assign=True,
            recipient_queryset=assignable_qs,
        )
        if form.is_valid():
            recipient = form.cleaned_data['recipient']
            if recipient.visit_planning_panel_registered:
                messages.warning(
                    request,
                    f'Подопечный {recipient.get_full_name()} уже учтён в панели планирования.',
                )
                if next_q.startswith('/') and not next_q.startswith('//'):
                    return redirect(next_q)
                return redirect('accounts:visit_planning')
            form.save()
            recipient.visit_planning_panel_registered = True
            recipient.save(update_fields=[
                'visit_planning_panel_registered', 'updated_at',
            ])
            messages.success(
                request,
                f'{recipient.get_full_name()} добавлен в панель планирования визитов.',
            )
            if next_q.startswith('/') and not next_q.startswith('//'):
                return redirect(next_q)
            return redirect('accounts:visit_planning')
        messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
        ctx = {**ctx_base, 'assign_form': form,
               'visits_per_week_hint': _planned_visit_vpw_hint(form)}
        return render(request, 'accounts/planned_visit_assign.html', ctx)

    initial = {}
    pre_rid = (request.GET.get('recipient') or '').strip()
    if pre_rid.isdigit():
        r = next(
            (x for x in assignable_list if str(x.pk) == pre_rid),
            None,
        )
        if r:
            initial = {
                'recipient': r.pk,
                'social_worker': r.social_worker_id,
                'recipient_visit_frequency': r.visit_frequency,
                'recipient_visit_days': r.visit_days or '',
            }
    form = PlannedVisitForm(
        initial=initial,
        for_panel_assign=True,
        recipient_queryset=assignable_qs,
    )
    ctx = {**ctx_base, 'assign_form': form,
           'visits_per_week_hint': _planned_visit_vpw_hint(form)}
    return render(request, 'accounts/planned_visit_assign.html', ctx)


@login_required
def visit_planning_remove_from_panel(request, pk):
    """Убрать подопечного из панели планирования (карточка и визиты в БД сохраняются)."""
    recipient = get_object_or_404(ServiceRecipient, pk=pk)
    next_q = (request.POST.get('next') or request.GET.get('next') or '').strip()

    if not recipient.visit_planning_panel_registered:
        messages.warning(
            request,
            'Этот подопечный уже не отображается в панели планирования.',
        )
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:visit_planning')

    if request.method == 'POST':
        name = recipient.get_full_name()
        recipient.visit_planning_panel_registered = False
        recipient.save(update_fields=[
            'visit_planning_panel_registered', 'updated_at',
        ])
        compact_service_recipient_employee_ids()
        messages.success(
            request,
            f'{name} убран из панели планирования визитов.',
        )
        if next_q.startswith('/') and not next_q.startswith('//'):
            return redirect(next_q)
        return redirect('accounts:visit_planning')

    return render(request, 'accounts/visit_planning_remove_confirm.html', {
        'recipient': recipient,
        'next_url': next_q,
    })


@login_required
def planned_visit_edit(request, pk):
    obj = get_object_or_404(
        PlannedVisit.objects.select_related('recipient', 'social_worker'),
        pk=pk,
    )
    next_url = request.GET.get('next', '') or request.POST.get('next', '')
    if request.method == 'POST':
        form = PlannedVisitForm(
            request.POST,
            instance=obj,
            planning_panel_short=True,
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Визит обновлён.')
            return _safe_redirect_next(request, next_url)
        messages.error(request, 'Проверьте поля формы.')
    else:
        form = PlannedVisitForm(instance=obj, planning_panel_short=True)
    recipient_meta = _recipient_meta_with_fallback(
        _visit_planning_panel_recipient_meta(),
        obj.recipient,
    )
    return render(request, 'accounts/planned_visit_form.html', {
        'form': form,
        'next_url': next_url,
        'title': 'Изменить запланированный визит',
        'submit_label': 'Сохранить',
        'planned_visit': obj,
        'visits_per_week_hint': _planned_visit_vpw_hint(form),
        'recipient_assign_meta': recipient_meta,
    })


@login_required
def visit_task_reminder_create(request):
    if request.method != 'POST':
        return redirect('accounts:visit_planning')
    next_url = request.POST.get('next', '')
    form = VisitTaskReminderForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, 'Напоминание о задаче добавлено.')
        return _safe_redirect_next(request, next_url)
    messages.error(request, 'Проверьте поля напоминания.')
    return render(request, 'accounts/visit_task_reminder_form.html', {
        'form': form,
        'next_url': next_url,
    })


@login_required
def visit_task_reminder_delete(request, pk):
    if request.method != 'POST':
        return redirect('accounts:visit_planning')
    obj = get_object_or_404(VisitTaskReminder, pk=pk)
    obj.delete()
    messages.success(request, 'Напоминание удалено.')
    return _safe_redirect_next(request, request.POST.get('next', ''))


@login_required
def recipient_create(request):
    """Создание нового получателя услуг"""
    if request.method == 'POST':
        form = ServiceRecipientForm(request.POST)
        if form.is_valid():
            recipient = form.save()
            messages.success(request, f'Получатель услуг {recipient.get_full_name()} успешно добавлен!')
            return redirect('accounts:recipients_list')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = ServiceRecipientForm()
    
    return render(request, 'accounts/recipient_form.html', {
        'form': form,
        'title': 'Добавить получателя услуг',
        'button_text': 'Добавить',
        'is_edit': False,
    })


@login_required
def recipient_detail(request, pk):
    """Детальная информация о получателе услуг"""
    recipient = get_object_or_404(
        ServiceRecipient.objects.select_related('social_worker', 'location'),
        pk=pk,
    )
    return render(request, 'accounts/recipient_detail.html', {
        'recipient': recipient
    })


@login_required
def recipient_edit(request, pk):
    """Редактирование получателя услуг"""
    recipient = get_object_or_404(ServiceRecipient, pk=pk)
    
    if request.method == 'POST':
        form = ServiceRecipientForm(request.POST, instance=recipient)
        if form.is_valid():
            recipient = form.save()
            messages.success(request, f'Информация о {recipient.get_full_name()} успешно обновлена!')
            return redirect('accounts:recipient_detail', pk=recipient.pk)
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = ServiceRecipientForm(instance=recipient)
    
    return render(request, 'accounts/recipient_form.html', {
        'form': form,
        'recipient': recipient,
        'title': 'Редактировать получателя услуг',
        'button_text': 'Сохранить изменения',
        'is_edit': True,
    })


@login_required
def recipient_delete(request, pk):
    """Удаление получателя услуг"""
    recipient = get_object_or_404(ServiceRecipient, pk=pk)
    
    if request.method == 'POST':
        name = recipient.get_full_name()
        recipient.delete()
        messages.success(request, f'Получатель услуг {name} успешно удален!')
        return redirect('accounts:recipients_list')
    
    return render(request, 'accounts/recipient_confirm_delete.html', {
        'recipient': recipient
    })


# ── Услуги ──────────────────────────────────────────────────────────

def _recipient_matches_location(recipient, location):
    if recipient.location_id == location.pk:
        return True
    name = (location.name or '').strip()
    if not name or recipient.location_id:
        return False
    addr = (recipient.address or '').lower()
    return name.lower() in addr


def _recipients_for_service(worker, location):
    """
    Подопечные работника в данном населённом пункте:
    - по полю location (основной случай);
    - если location не указан у получателя — по вхождению названия пункта в адрес.
    """
    name = (location.name or '').strip()
    q_location = Q(location=location)
    q_address = Q()
    if name:
        q_address = Q(location__isnull=True, address__icontains=name)
    return (
        ServiceRecipient.objects.filter(social_worker=worker)
        .filter(q_location | q_address)
        .select_related('location')
        .distinct()
        .order_by('last_name', 'first_name')
    )


@login_required
def services_panel(request):
    """Панель 'Услуги': список работников и населённых пунктов"""
    workers = list(SocialWorker.objects.order_by('last_name', 'first_name').prefetch_related('recipients'))
    locations = list(ServiceLocation.objects.order_by('name'))
    for loc in locations:
        # Получатели, «привязанные» к пункту: в карточке выбран пункт или в адресе есть название пункта
        # (та же идея, что и в таблице услуг по связке работник — пункт).
        name_part = (loc.name or '').strip()
        rq = Q(location=loc)
        if name_part:
            rq |= Q(location__isnull=True, address__icontains=name_part)
        loc.recipients_living_count = (
            ServiceRecipient.objects.filter(rq).distinct().count()
        )

    worker_ids = [w.pk for w in workers]
    all_for_panel = list(
        ServiceRecipient.objects.filter(social_worker_id__in=worker_ids)
        .select_related('location')
        .order_by('last_name', 'first_name')
    )

    service_links = []
    for w in workers:
        for loc in locations:
            cnt = sum(
                1 for r in all_for_panel
                if r.social_worker_id == w.pk and _recipient_matches_location(r, loc)
            )
            service_links.append({
                'worker': w,
                'location': loc,
                'count': cnt,
            })

    return render(request, 'accounts/services_panel.html', {
        'workers': workers,
        'locations': locations,
        'service_links': service_links,
        'services_detail_url_zero': reverse(
            'accounts:services_detail',
            kwargs={'worker_pk': 0, 'location_pk': 0},
        ),
    })


@login_required
def services_detail(request, worker_pk, location_pk):
    """Таблица получателей по конкретному работнику и населённому пункту"""
    worker = get_object_or_404(SocialWorker, pk=worker_pk)
    location = get_object_or_404(ServiceLocation, pk=location_pk)

    recipients = _recipients_for_service(worker, location)

    return render(request, 'accounts/services_detail.html', {
        'worker': worker,
        'location': location,
        'recipients': recipients,
    })


@login_required
def location_create(request):
    """Добавить населённый пункт"""
    if request.method == 'POST':
        form = ServiceLocationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Населённый пункт добавлен.')
            return redirect('accounts:services_panel')
    else:
        form = ServiceLocationForm()
    return render(request, 'accounts/location_form.html', {
        'form': form,
        'title': 'Добавить населённый пункт',
        'button_text': 'Сохранить',
    })


@login_required
def location_delete(request, pk):
    """Удалить населённый пункт"""
    location = get_object_or_404(ServiceLocation, pk=pk)
    if request.method == 'POST':
        location.delete()
        messages.success(request, 'Населённый пункт удалён.')
        return redirect('accounts:services_panel')
    return render(request, 'accounts/location_confirm_delete.html', {
        'location': location,
    })


# ── Закреплённые лица ────────────────────────────────────────────────

@login_required
def assigned_persons(request):
    """Таблица соц. работников и их закреплённых подопечных"""
    sort = request.GET.get('sort', 'all')
    search = request.GET.get('search', '').strip()

    pairs = ServiceRecipient.objects.filter(
        social_worker__isnull=False
    ).select_related('social_worker').order_by(
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )

    if sort == 'worker' and search:
        pairs = pairs.filter(
            Q(social_worker__last_name__icontains=search) |
            Q(social_worker__first_name__icontains=search) |
            Q(social_worker__middle_name__icontains=search) |
            Q(social_worker__phone__icontains=search)
        )
    elif sort == 'recipient' and search:
        pairs = pairs.filter(
            Q(last_name__icontains=search) |
            Q(first_name__icontains=search) |
            Q(middle_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(address__icontains=search)
        )

    if sort == 'recipient':
        pairs = pairs.order_by('last_name', 'first_name')
    elif sort == 'worker':
        pairs = pairs.order_by(
            'social_worker__last_name', 'social_worker__first_name',
            'last_name', 'first_name',
        )

    rows = []
    for r in pairs:
        rows.append({'worker': r.social_worker, 'recipient': r})

    if sort != 'recipient':
        assigned_worker_ids = pairs.values_list('social_worker_id', flat=True).distinct()
        free_workers = SocialWorker.objects.exclude(pk__in=assigned_worker_ids).order_by('last_name', 'first_name')
        if sort == 'worker' and search:
            free_workers = free_workers.filter(
                Q(last_name__icontains=search) |
                Q(first_name__icontains=search) |
                Q(middle_name__icontains=search) |
                Q(phone__icontains=search)
            )
        for w in free_workers:
            rows.append({'worker': w, 'recipient': None})

    all_workers = SocialWorker.objects.order_by('last_name', 'first_name')
    unassigned_recipients = ServiceRecipient.objects.filter(social_worker__isnull=True).order_by('last_name', 'first_name')

    return render(request, 'accounts/assigned_persons.html', {
        'rows': rows,
        'sort': sort,
        'search': search,
        'all_workers': all_workers,
        'unassigned_recipients': unassigned_recipients,
    })


@login_required
def assign_recipient(request):
    """Закрепить подопечного за соц. работником"""
    if request.method == 'POST':
        worker_id = request.POST.get('worker_id')
        recipient_id = request.POST.get('recipient_id')
        if worker_id and recipient_id:
            recipient = get_object_or_404(ServiceRecipient, pk=recipient_id)
            worker = get_object_or_404(SocialWorker, pk=worker_id)
            recipient.social_worker = worker
            recipient.save()
            messages.success(request, f'{recipient.get_full_name()} закреплён за {worker.get_full_name()}')
    return redirect('accounts:assigned_persons')


@login_required
def unassign_recipient(request, pk):
    """Открепить подопечного от соц. работника"""
    if request.method == 'POST':
        recipient = get_object_or_404(ServiceRecipient, pk=pk)
        old_worker = recipient.social_worker
        recipient.social_worker = None
        recipient.visit_planning_panel_registered = False
        recipient.save()
        messages.success(request, f'{recipient.get_full_name()} откреплён от {old_worker.get_full_name() if old_worker else "работника"}')
    return redirect('accounts:assigned_persons')


# ── Отчёты ──────────────────────────────────────────────────────────

@login_required
def report_select(request):
    """Страница выбора типа отчёта"""
    return render(request, 'accounts/report_select.html', {
        'show_inventory_reports': has_inventory_access(request.user),
    })


@login_required
def report_pdf(request, report_type):
    """Генерация PDF-отчёта"""
    font_name = _register_fonts()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=16,
        spaceAfter=6 * mm,
    )
    cell_style = ParagraphStyle(
        'Cell',
        fontName=font_name,
        fontSize=8,
        leading=10,
    )
    header_style = ParagraphStyle(
        'HeaderCell',
        fontName=font_name,
        fontSize=8,
        leading=10,
        textColor=colors.whitesmoke,
    )

    def P(text, style=cell_style):
        return Paragraph(str(text) if text else '—', style)

    def PH(text):
        return Paragraph(str(text), header_style)

    elements = []
    now = datetime.now().strftime('%d.%m.%Y %H:%M')

    if report_type == 'social_workers':
        tab_sort = _report_tab_sort_param(request)
        workers_ordered_qs = _apply_tab_employee_sort(SocialWorker.objects.all(), tab_sort)
        subtitle_suffix = ''
        filename = 'social_workers_report.pdf'

        if request.method == 'POST':
            scope = request.POST.get('scope', 'all')
            if scope == 'selected':
                raw_ids = request.POST.getlist('worker_ids')
                pks = []
                for x in raw_ids:
                    s = str(x).strip()
                    if s.isdigit():
                        pks.append(int(s))
                pks = list(dict.fromkeys(pks))
                if not pks:
                    messages.warning(
                        request,
                        'Отметьте хотя бы одного социального работника или выберите выгрузку всего списка.',
                    )
                    return redirect('accounts:social_workers_list')
                workers = list(workers_ordered_qs.filter(pk__in=pks))
                if not workers:
                    messages.warning(request, 'Выбранные сотрудники не найдены.')
                    return redirect('accounts:social_workers_list')
                subtitle_suffix = ' (выбранные записи)'
                filename = 'social_workers_selected_report.pdf'
            else:
                workers = list(workers_ordered_qs)
        else:
            workers = list(workers_ordered_qs)

        elements.append(
            Paragraph(f'Отчёт: Социальные работники{subtitle_suffix} — {now}', title_style),
        )

        headers = [
            PH('№'), PH('ФИО'), PH('Год рожд.'),
            PH('Адрес'), PH('Телефон'), PH('Мед. осмотр'),
            PH('Дата приёма на работу'), PH('Примечания'), PH('Статус'),
        ]

        data = [headers]
        for w in workers:
            data.append([
                P(w.employee_id or '—'),
                P(w.get_full_name()),
                P(w.birth_date.strftime('%Y') if w.birth_date else '—'),
                P(w.address or '—'),
                P(w.phone or '—'),
                P(w.get_medical_checkup_display()),
                P(w.hire_date.strftime('%d.%m.%Y') if w.hire_date else '—'),
                P(_export_plain_text(w.notes, max_len=400)),
                P(w.get_status_display()),
            ])

        col_widths = [42, 102, 34, 94, 54, 54, 54, 92, 88]

    elif report_type == 'recipients':
        tab_sort = _report_tab_sort_param(request)
        recipients_ordered_qs = _apply_tab_employee_sort(
            ServiceRecipient.objects.select_related('social_worker', 'location'),
            tab_sort,
        )
        subtitle_suffix = ''
        filename = 'recipients_report.pdf'

        if request.method == 'POST':
            scope = request.POST.get('scope', 'all')
            if scope == 'selected':
                raw_ids = request.POST.getlist('recipient_ids')
                pks = []
                for x in raw_ids:
                    s = str(x).strip()
                    if s.isdigit():
                        pks.append(int(s))
                pks = list(dict.fromkeys(pks))
                if not pks:
                    messages.warning(
                        request,
                        'Отметьте хотя бы одного получателя или выберите выгрузку всего списка.',
                    )
                    return redirect('accounts:recipients_list')
                recipients = list(recipients_ordered_qs.filter(pk__in=pks))
                if not recipients:
                    messages.warning(request, 'Выбранные получатели не найдены.')
                    return redirect('accounts:recipients_list')
                subtitle_suffix = ' (выбранные записи)'
                filename = 'recipients_selected_report.pdf'
            else:
                recipients = list(recipients_ordered_qs)
        else:
            recipients = list(recipients_ordered_qs)

        elements.append(
            Paragraph(f'Отчёт: Получатели услуг{subtitle_suffix} — {now}', title_style),
        )

        headers = [
            PH('№'), PH('ФИО'), PH('Год рожд.'), PH('Телефон'), PH('Адрес'),
            PH('Населённый пункт'), PH('Тип жилья'),
            PH('Гр. инвал.'), PH('Оплата'), PH('Кратность'),
            PH('Категория'), PH('Дата приёма'), PH('Дни посещ.'),
            PH('АПИ'), PH('Примечания'), PH('Соц. работник'),
        ]

        data = [headers]
        for r in recipients:
            data.append([
                P(r.employee_id or '—'),
                P(r.get_full_name()),
                P(r.birth_date.strftime('%Y') if r.birth_date else '—'),
                P(r.phone or '—'),
                P(r.address or '—'),
                P(_recipient_location_export_label(r)),
                P(r.get_housing_type_display()),
                P(r.get_disability_group_display()),
                P(f'{r.payment_percent}%'),
                P(r.get_visit_frequency_display()),
                P(r.get_living_status_display()),
                P(r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—'),
                P(r.visit_days or '—'),
                P(r.fire_detector_count),
                P(_export_plain_text(r.notes, max_len=400)),
                P(r.social_worker.get_full_name() if r.social_worker else '—'),
            ])

        col_widths = [34, 76, 28, 46, 54, 54, 42, 30, 28, 38, 38, 40, 38, 22, 50, 62]

    elif report_type == 'assigned':
        filename = 'assigned_persons_report.pdf'
        row_tuples = None
        pairs = None

        if request.method == 'POST':
            sort = request.POST.get('sort', 'all')
            scope = request.POST.get('scope', 'all')

            if scope == 'selected':
                tokens = request.POST.getlist('row_ids')
                row_tuples = []
                for t in tokens:
                    s = str(t).strip()
                    if s.startswith('r:') and s[2:].isdigit():
                        pk = int(s[2:])
                        rec = ServiceRecipient.objects.filter(
                            pk=pk, social_worker__isnull=False,
                        ).select_related('social_worker').first()
                        if rec:
                            row_tuples.append((rec.social_worker, rec))
                    elif s.startswith('w:') and s[2:].isdigit():
                        pk = int(s[2:])
                        w = SocialWorker.objects.filter(pk=pk).first()
                        if w:
                            row_tuples.append((w, None))
                if not row_tuples:
                    messages.warning(
                        request,
                        'Отметьте хотя бы одну строку в таблице или выберите выгрузку всего списка закреплений.',
                    )
                    return redirect('accounts:assigned_persons')
                subtitle = 'Закреплённые лица (выбранные записи)'
                filename = 'assigned_persons_selected_report.pdf'
            else:
                pairs_qs = ServiceRecipient.objects.filter(
                    social_worker__isnull=False,
                ).select_related('social_worker')
                if sort == 'recipient':
                    pairs_qs = pairs_qs.order_by('last_name', 'first_name')
                else:
                    pairs_qs = pairs_qs.order_by(
                        'social_worker__last_name', 'social_worker__first_name',
                        'last_name', 'first_name',
                    )
                pairs = list(pairs_qs)
                subtitle = 'Закреплённые лица'
        else:
            sort = request.GET.get('sort', 'all')
            search = request.GET.get('search', '').strip()

            pairs_qs = ServiceRecipient.objects.filter(
                social_worker__isnull=False,
            ).select_related('social_worker')

            if sort == 'worker' and search:
                pairs_qs = pairs_qs.filter(
                    Q(social_worker__last_name__icontains=search) |
                    Q(social_worker__first_name__icontains=search) |
                    Q(social_worker__middle_name__icontains=search) |
                    Q(social_worker__phone__icontains=search)
                )
            elif sort == 'recipient' and search:
                pairs_qs = pairs_qs.filter(
                    Q(last_name__icontains=search) |
                    Q(first_name__icontains=search) |
                    Q(middle_name__icontains=search) |
                    Q(phone__icontains=search) |
                    Q(address__icontains=search)
                )

            if sort == 'recipient':
                pairs_qs = pairs_qs.order_by('last_name', 'first_name')
            else:
                pairs_qs = pairs_qs.order_by(
                    'social_worker__last_name', 'social_worker__first_name',
                    'last_name', 'first_name',
                )

            pairs = list(pairs_qs)
            subtitle = 'Закреплённые лица'
            if search:
                subtitle += f' (поиск: {search})'

        elements.append(Paragraph(f'Отчёт: {subtitle} — {now}', title_style))

        if sort == 'recipient':
            headers = [
                PH('№'), PH('ФИО подопечного'), PH('Телефон подопечного'),
                PH('Адрес подопечного'), PH('ФИО соц. работника'), PH('Телефон соц. работника'),
            ]
        else:
            headers = [
                PH('№'), PH('ФИО соц. работника'), PH('Телефон соц. работника'),
                PH('ФИО подопечного'), PH('Телефон подопечного'), PH('Адрес подопечного'),
            ]

        data = [headers]

        def append_assigned_row(index, w, r):
            if sort == 'recipient':
                if r:
                    data.append([
                        P(index), P(r.get_full_name()), P(r.phone or '—'),
                        P(r.address or '—'), P(w.get_full_name()), P(w.phone or '—'),
                    ])
                else:
                    data.append([
                        P(index), P('—'), P('—'), P('—'),
                        P(w.get_full_name()), P(w.phone or '—'),
                    ])
            else:
                if r:
                    data.append([
                        P(index), P(w.get_full_name()), P(w.phone or '—'),
                        P(r.get_full_name()), P(r.phone or '—'), P(r.address or '—'),
                    ])
                else:
                    data.append([
                        P(index), P(w.get_full_name()), P(w.phone or '—'),
                        P('—'), P('—'), P('—'),
                    ])

        if row_tuples is not None:
            for i, (w, r) in enumerate(row_tuples, 1):
                append_assigned_row(i, w, r)
        else:
            for i, r in enumerate(pairs, 1):
                append_assigned_row(i, r.social_worker, r)

        col_widths = [25, 120, 70, 120, 120, 70]
        header_bg = colors.HexColor('#e74c5e') if sort == 'worker' else (
            colors.HexColor('#5a7eea') if sort == 'recipient' else colors.HexColor('#667eea')
        )

    elif report_type == 'services':
        try:
            worker_pk = int(request.GET.get('worker_pk', ''))
            location_pk = int(request.GET.get('location_pk', ''))
        except (TypeError, ValueError):
            messages.warning(request, 'Не удалось сформировать PDF: укажите работника и населённый пункт.')
            return redirect('accounts:services_panel')

        worker = get_object_or_404(SocialWorker, pk=worker_pk)
        location = get_object_or_404(ServiceLocation, pk=location_pk)
        recipients = list(_recipients_for_service(worker, location))

        if not recipients:
            messages.warning(
                request,
                'Нет обслуживаемых граждан для выбранной связки — распечатать таблицу услуг нельзя.',
            )
            return redirect('accounts:services_detail', worker_pk=worker_pk, location_pk=location_pk)

        loc_label = f'{location.get_location_type_display()} {location.name}'.strip()
        elements.append(Paragraph(
            f'Услуги: {worker.get_full_name()} — {loc_label} — {now}',
            title_style,
        ))

        headers = [
            PH('№'), PH('Ф.И.О.'), PH('Год рожд.'),
            PH('Адрес проживания'), PH('Населённый пункт'), PH('Тип жилья'),
            PH('Гр. инвал.'), PH('Оплата'), PH('Кратность'),
            PH('Категория'), PH('Дата приёма'), PH('Дни посещ.'), PH('АПИ'),
        ]
        data = [headers]
        for r in recipients:
            data.append([
                P(r.employee_id or '—'),
                P(r.get_full_name()),
                P(r.birth_date.strftime('%Y') if r.birth_date else '—'),
                P(r.address or '—'),
                P(_recipient_location_export_label(r)),
                P(r.get_housing_type_display()),
                P(r.get_disability_group_display()),
                P(f'{r.payment_percent}%'),
                P(r.get_visit_frequency_display()),
                P(r.get_living_status_display()),
                P(r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—'),
                P(r.visit_days or '—'),
                P(r.fire_detector_count),
            ])

        col_widths = [40, 88, 30, 72, 54, 42, 34, 30, 44, 42, 42, 40, 28]
        safe_loc = ''.join(c for c in (location.name or 'location') if c.isalnum() or c in (' ', '-', '_')).strip() or 'location'
        safe_loc = safe_loc.replace(' ', '_')[:40]
        filename = f'services_w{worker.pk}_{safe_loc}.pdf'

    elif report_type == 'services_all':
        workers = list(SocialWorker.objects.order_by('last_name', 'first_name'))
        locations = list(ServiceLocation.objects.order_by('name'))
        worker_ids = [w.pk for w in workers]
        all_for_panel = list(
            ServiceRecipient.objects.filter(social_worker_id__in=worker_ids)
            .select_related('location', 'social_worker')
            .order_by('last_name', 'first_name')
        )

        links_rows = []
        for w in workers:
            for loc in locations:
                cnt = sum(
                    1 for r in all_for_panel
                    if r.social_worker_id == w.pk and _recipient_matches_location(r, loc)
                )
                links_rows.append((w, loc, cnt))

        elements.append(Paragraph(f'Отчёт: Услуги (все связки работник — населённый пункт) — {now}', title_style))

        headers = [
            PH('№'), PH('Социальный работник'),
            PH('Населённый пункт'), PH('Записей'),
        ]
        data = [headers]
        for i, (w, loc, cnt) in enumerate(links_rows, 1):
            loc_label = f'{loc.get_location_type_display()} {loc.name}'.strip()
            data.append([
                P(i),
                P(w.get_full_name()),
                P(loc_label),
                P(cnt),
            ])

        col_widths = [32, 145, 175, 52]
        filename = 'services_all_report.pdf'

    elif report_type == 'inventory':
        from inventory.models import InventoryUnit
        from inventory.permissions import has_inventory_access

        if not has_inventory_access(request.user):
            messages.error(request, 'Нет доступа к отчёту инвентаризации.')
            return redirect('accounts:report_select')

        inv_sort = request.POST.get('sort') or request.GET.get('sort', 'inv_asc')
        units_base_qs = InventoryUnit.objects.select_related('responsible')
        units_ordered_qs = _inventory_report_order_qs(units_base_qs, inv_sort)
        subtitle_suffix = ''
        filename = 'inventory_report.pdf'

        if request.method == 'POST':
            scope = request.POST.get('scope', 'all')
            if scope == 'selected':
                raw_ids = request.POST.getlist('inventory_unit_ids')
                pks = []
                for x in raw_ids:
                    s = str(x).strip()
                    if s.isdigit():
                        pks.append(int(s))
                pks = list(dict.fromkeys(pks))
                if not pks:
                    messages.warning(
                        request,
                        'Отметьте хотя бы одну единицу учёта или выберите выгрузку всего списка.',
                    )
                    return redirect('inventory:panel')
                pk_set = set(pks)
                units = [u for u in units_ordered_qs if u.pk in pk_set]
                if not units:
                    messages.warning(request, 'Выбранные единицы учёта не найдены.')
                    return redirect('inventory:panel')
                subtitle_suffix = ' (выбранные записи)'
                filename = 'inventory_selected_report.pdf'
            else:
                units = list(units_ordered_qs)
        else:
            units = list(units_ordered_qs)

        elements.append(
            Paragraph(f'Отчёт: Инвентаризация{subtitle_suffix} — {now}', title_style),
        )

        headers = [
            PH('Инв. №'),
            PH('Фото'),
            PH('Название'),
            PH('Стоимость (бел.руб.)'),
            PH('Ответственный'),
        ]

        data = [headers]
        for u in units:
            photo_cell = 'Да' if getattr(u, 'equipment_photo', None) else 'Нет'
            data.append([
                P(u.inventory_number),
                P(photo_cell),
                P(u.name),
                P(str(u.cost)),
                P(_inventory_responsible_export_cell(u.responsible)),
            ])

        col_widths = [52, 36, 148, 52, 118]

    else:
        return redirect('accounts:report_select')

    if report_type == 'assigned':
        header_color = header_bg
    else:
        header_color = colors.HexColor('#667eea')

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dde1e6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fb')]),
    ]))
    elements.append(table)

    info_style = ParagraphStyle(
        'Info',
        fontName=font_name,
        fontSize=7,
        textColor=colors.grey,
        spaceBefore=5 * mm,
    )
    total = len(data) - 1
    elements.append(Paragraph(f'Всего записей: {total}. Сформировано: {now}', info_style))

    doc.build(elements)
    buf.seek(0)

    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


from .views_extra import (  # noqa: E402
    medical_checkup_panel_csv,
    medical_checkup_panel_pdf,
    report_csv,
    safety_briefing_panel_csv,
    safety_briefing_panel_pdf,
    visit_planning_csv,
    visit_planning_pdf,
    workload_export_csv,
    workload_panel,
    workload_panel_csv,
    workload_panel_pdf,
    workload_record_create,
    workload_record_delete,
    workload_record_edit,
    workload_records_list,
)
