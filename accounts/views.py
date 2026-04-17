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
from django.db.models import Q
from django.http import HttpResponse

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
    ServiceRecipientForm,
    ServiceLocationForm,
    PlannedVisitForm,
    VisitTaskReminderForm,
    SafetyBriefingRecordForm,
)
from .models import (
    SocialWorker,
    ServiceRecipient,
    ServiceLocation,
    PlannedVisit,
    VisitTaskReminder,
    SafetyBriefingRecord,
)
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
    """Главная страница после входа"""
    return render(request, 'accounts/dashboard.html', {
        'user': request.user
    })


@login_required
def profile_view(request):
    """Страница О пользователе"""
    return render(request, 'accounts/profile.html', {
        'user': request.user
    })


# Представления для управления социальными работниками
@login_required
def social_workers_list(request):
    """Список социальных работников"""
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
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
    
    # Сортировка
    workers = workers.order_by('last_name', 'first_name')
    
    # Пагинация
    paginator = Paginator(workers, 10)  # 10 работников на страницу
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'has_active_filters': bool(search_query or status_filter),
        'status_choices': SocialWorker.STATUS_CHOICES,
    }
    
    return render(request, 'accounts/social_workers_list.html', context)


MEDICAL_CHECKUP_VALID_DAYS = 365


@login_required
def medical_checkup_panel(request):
    """Таблица сотрудников: годовая актуальность медосмотра, назначение даты."""
    worker_filter = request.GET.get('worker', '')
    status_filter = request.GET.get('status', '')

    workers = SocialWorker.objects.all()
    if worker_filter and str(worker_filter).isdigit():
        workers = workers.filter(pk=int(worker_filter))
    if status_filter:
        workers = workers.filter(status=status_filter)

    workers = workers.order_by('last_name', 'first_name')
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

    return render(request, 'accounts/medical_checkup_panel.html', {
        'page_obj': page_obj,
        'filter_worker': worker_filter if (worker_filter and str(worker_filter).isdigit()) else '',
        'status_filter': status_filter,
        'has_active_filters': bool(
            (worker_filter and str(worker_filter).isdigit()) or status_filter,
        ),
        'status_choices': SocialWorker.STATUS_CHOICES,
        'today': today,
        'today_iso': today.isoformat(),
        'all_workers': SocialWorker.objects.order_by('last_name', 'first_name'),
        'page_query': query,
        'medical_panel_back': request.get_full_path(),
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
    if request.method != 'POST':
        return redirect('accounts:medical_checkup_panel')
    pk = request.POST.get('worker_pk')
    planned_str = request.POST.get('planned_date', '').strip()
    if not pk or not str(pk).isdigit():
        messages.error(request, 'Выберите сотрудника.')
        return redirect('accounts:medical_checkup_panel')
    try:
        planned_on = date.fromisoformat(planned_str)
    except ValueError:
        messages.error(request, 'Укажите корректную дату назначения.')
        return redirect('accounts:medical_checkup_panel')
    worker = get_object_or_404(SocialWorker, pk=int(pk))
    worker.medical_checkup_planned_date = planned_on
    today = date.today()
    if worker.last_medical_checkup_date:
        valid_until = worker.last_medical_checkup_date + timedelta(days=MEDICAL_CHECKUP_VALID_DAYS)
        if valid_until < today and worker.medical_checkup == 'passed':
            worker.medical_checkup = 'expired'
    worker.save(update_fields=[
        'medical_checkup_planned_date', 'medical_checkup', 'updated_at',
    ])
    messages.success(
        request,
        f'Медосмотр для {worker.get_full_name()} назначен на {planned_on.strftime("%d.%m.%Y")}.',
    )
    next_q = request.POST.get('next', '')
    if next_q.startswith('/') and not next_q.startswith('//'):
        return redirect(next_q)
    return redirect('accounts:medical_checkup_panel')


@login_required
def safety_briefing_panel(request):
    """Панель техники безопасности: инструктажи, статус прохождения, действия."""
    worker_filter = request.GET.get('worker', '')
    title_q = request.GET.get('title', '').strip()

    records = SafetyBriefingRecord.objects.select_related('social_worker').all()
    if worker_filter and str(worker_filter).isdigit():
        records = records.filter(social_worker_id=int(worker_filter))
    if title_q:
        records = records.filter(briefing_title__icontains=title_q)

    records = records.order_by('-briefing_date', 'social_worker__last_name', 'pk')
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
        'has_active_filters': bool(
            (worker_filter and str(worker_filter).isdigit()) or title_q,
        ),
        'all_workers': SocialWorker.objects.order_by('last_name', 'first_name'),
        'briefing_form': SafetyBriefingRecordForm(),
        'page_query': query,
        'panel_back': request.get_full_path(),
    })


@login_required
def safety_briefing_add(request):
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    form = SafetyBriefingRecordForm(request.POST)
    next_url = request.POST.get('next', '')
    if form.is_valid():
        form.save()
        messages.success(request, 'Запись об инструктаже добавлена.')
        if next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect('accounts:safety_briefing_panel')
    messages.error(request, 'Исправьте ошибки в форме.')
    records = SafetyBriefingRecord.objects.select_related('social_worker').order_by(
        '-briefing_date', 'social_worker__last_name', 'pk',
    )
    page_obj = Paginator(records, 20).get_page(1)
    return render(request, 'accounts/safety_briefing_panel.html', {
        'page_obj': page_obj,
        'filter_worker': '',
        'filter_title': '',
        'has_active_filters': False,
        'all_workers': SocialWorker.objects.order_by('last_name', 'first_name'),
        'briefing_form': form,
        'page_query': '',
        'panel_back': reverse('accounts:safety_briefing_panel'),
    })


@login_required
def safety_briefing_delete(request, pk):
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    obj = get_object_or_404(SafetyBriefingRecord, pk=pk)
    obj.delete()
    messages.success(request, 'Запись об инструктаже удалена.')
    next_url = request.POST.get('next', '')
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect('accounts:safety_briefing_panel')


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
            pass
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
    disability_filter = request.GET.get('disability', '')
    living_filter = request.GET.get('living', '')
    
    recipients = ServiceRecipient.objects.select_related('social_worker').all()
    
    if search_query:
        recipients = recipients.filter(
            Q(employee_id__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(middle_name__icontains=search_query) |
            Q(address__icontains=search_query)
        )
    
    if disability_filter:
        recipients = recipients.filter(disability_group=disability_filter)
    
    if living_filter:
        recipients = recipients.filter(living_status=living_filter)
    
    recipients = recipients.order_by('last_name', 'first_name')
    
    paginator = Paginator(recipients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'disability_filter': disability_filter,
        'living_filter': living_filter,
        'has_active_filters': bool(search_query or disability_filter or living_filter),
        'disability_choices': ServiceRecipient.DISABILITY_GROUP_CHOICES,
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

    planned = PlannedVisit.objects.filter(
        visit_date__gte=today,
        visit_date__lte=remind_end,
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

    recipients = ServiceRecipient.objects.filter(
        social_worker__isnull=False,
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

    recipients = recipients.order_by(
        'social_worker__last_name', 'social_worker__first_name',
        'last_name', 'first_name',
    )
    rec_list = list(recipients)
    rec_ids = [r.pk for r in rec_list]
    planned_by_date = defaultdict(list)
    if rec_ids:
        for pv in PlannedVisit.objects.filter(recipient_id__in=rec_ids).select_related(
            'recipient', 'social_worker',
        ):
            planned_by_date[pv.visit_date].append(pv)

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
        rows.append({
            'recipient': r,
            'worker': r.social_worker,
            'visits_per_week': n,
            'schedule_label': r.get_visit_frequency_display(),
            'visit_days_text': (r.visit_days or '').strip() or '—',
            'day_flags': day_flags,
            'schedule_ok': mismatch is None,
            'schedule_warn': mismatch,
        })

    today = date.today()
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

    all_workers = SocialWorker.objects.order_by('last_name', 'first_name')

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
        'planned_visit_form': PlannedVisitForm(),
        'task_reminder_form': VisitTaskReminderForm(),
        'active_task_reminders': active_task_reminders,
        'task_reminder_count': len(active_task_reminders),
        'planning_back_url': planning_back_url,
        'planning_next_quoted': quote(request.get_full_path(), safe=''),
        'all_workers': all_workers,
        'recipient_options': recipient_options,
        'filter_worker': wid or '',
        'filter_recipient': rid if (rid and str(rid).isdigit()) else '',
        'filter_living': living or '',
        'filter_wstatus': wstatus or '',
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
    """Создание запланированного визита (модалка или отдельная страница при ошибке)."""
    if request.method != 'POST':
        return redirect('accounts:visit_planning')
    next_url = request.POST.get('next', '')
    form = PlannedVisitForm(request.POST)
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
    })


@login_required
def planned_visit_edit(request, pk):
    obj = get_object_or_404(
        PlannedVisit.objects.select_related('recipient', 'social_worker'),
        pk=pk,
    )
    next_url = request.GET.get('next', '') or request.POST.get('next', '')
    if request.method == 'POST':
        if 'delete' in request.POST:
            obj.delete()
            messages.success(request, 'Запланированный визит удалён.')
            return _safe_redirect_next(request, next_url)
        form = PlannedVisitForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Визит обновлён.')
            return _safe_redirect_next(request, next_url)
        messages.error(request, 'Проверьте поля формы.')
    else:
        form = PlannedVisitForm(instance=obj)
    return render(request, 'accounts/planned_visit_form.html', {
        'form': form,
        'next_url': next_url,
        'title': 'Изменить запланированный визит',
        'submit_label': 'Сохранить',
        'planned_visit': obj,
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
        recipient.save()
        messages.success(request, f'{recipient.get_full_name()} откреплён от {old_worker.get_full_name() if old_worker else "работника"}')
    return redirect('accounts:assigned_persons')


# ── Отчёты ──────────────────────────────────────────────────────────

@login_required
def report_select(request):
    """Страница выбора типа отчёта"""
    return render(request, 'accounts/report_select.html')


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
        workers_qs = SocialWorker.objects.all()
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
                workers = list(
                    workers_qs.filter(pk__in=pks).order_by('last_name', 'first_name')
                )
                if not workers:
                    messages.warning(request, 'Выбранные сотрудники не найдены.')
                    return redirect('accounts:social_workers_list')
                subtitle_suffix = ' (выбранные записи)'
                filename = 'social_workers_selected_report.pdf'
            else:
                workers = list(workers_qs.order_by('last_name', 'first_name'))
        else:
            workers = list(workers_qs.order_by('last_name', 'first_name'))

        elements.append(
            Paragraph(f'Отчёт: Социальные работники{subtitle_suffix} — {now}', title_style),
        )

        headers = [
            PH('№'), PH('ФИО'), PH('Год рожд.'),
            PH('Адрес'), PH('Телефон'), PH('Мед. осмотр'),
            PH('Посл. осм.'), PH('Назн.'),
            PH('Статус'),
            PH('Дата приёма'),
        ]

        data = [headers]
        for i, w in enumerate(workers, 1):
            data.append([
                P(i),
                P(w.get_full_name()),
                P(w.birth_date.strftime('%Y') if w.birth_date else '—'),
                P(w.address or '—'),
                P(w.phone or '—'),
                P(w.get_medical_checkup_display()),
                P(w.last_medical_checkup_date.strftime('%d.%m.%Y') if w.last_medical_checkup_date else '—'),
                P(w.medical_checkup_planned_date.strftime('%d.%m.%Y') if w.medical_checkup_planned_date else '—'),
                P(w.get_status_display()),
                P(w.hire_date.strftime('%d.%m.%Y') if w.hire_date else '—'),
            ])

        col_widths = [26, 108, 38, 100, 58, 56, 48, 48, 52, 52, 52]

    elif report_type == 'recipients':
        recipients_qs = ServiceRecipient.objects.select_related('social_worker').all()
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
                recipients = list(
                    recipients_qs.filter(pk__in=pks).order_by('last_name', 'first_name')
                )
                if not recipients:
                    messages.warning(request, 'Выбранные получатели не найдены.')
                    return redirect('accounts:recipients_list')
                subtitle_suffix = ' (выбранные записи)'
                filename = 'recipients_selected_report.pdf'
            else:
                recipients = list(recipients_qs.order_by('last_name', 'first_name'))
        else:
            recipients = list(recipients_qs.order_by('last_name', 'first_name'))

        elements.append(
            Paragraph(f'Отчёт: Получатели услуг{subtitle_suffix} — {now}', title_style),
        )

        headers = [
            PH('№'), PH('ФИО'), PH('Год рожд.'), PH('Адрес'),
            PH('Гр. инвал.'), PH('Оплата %'), PH('Кратность'),
            PH('Категория'), PH('Дата приёма'), PH('Дни посещ.'),
            PH('АПИ'), PH('Примечания'), PH('Соц. работник'),
        ]

        data = [headers]
        for i, r in enumerate(recipients, 1):
            data.append([
                P(i),
                P(r.get_full_name()),
                P(r.birth_date.strftime('%Y') if r.birth_date else '—'),
                P(r.address or '—'),
                P(r.get_disability_group_display()),
                P(f'{r.payment_percent}%'),
                P(r.get_visit_frequency_display()),
                P(r.get_living_status_display()),
                P(r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—'),
                P(r.visit_days or '—'),
                P(r.fire_detector_count),
                P(r.notes or '—'),
                P(r.social_worker.get_full_name() if r.social_worker else '—'),
            ])

        col_widths = [20, 76, 32, 68, 38, 32, 48, 40, 46, 40, 22, 52, 62]

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
            PH('Адрес'), PH('Гр. инвал.'), PH('Оплата %'), PH('Кратность'),
            PH('Прожив.'), PH('Дата приёма'), PH('Дни посещ.'), PH('АПИ'),
        ]
        data = [headers]
        for i, r in enumerate(recipients, 1):
            data.append([
                P(i),
                P(r.get_full_name()),
                P(r.birth_date.strftime('%Y') if r.birth_date else '—'),
                P(r.address or '—'),
                P(r.get_disability_group_display()),
                P(f'{r.payment_percent}%'),
                P(r.get_visit_frequency_display()),
                P(r.get_living_status_display()),
                P(r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—'),
                P(r.visit_days or '—'),
                P(r.fire_detector_count),
            ])

        col_widths = [25, 92, 34, 78, 40, 34, 50, 44, 42, 42, 26]
        safe_loc = ''.join(c for c in (location.name or 'location') if c.isalnum() or c in (' ', '-', '_')).strip() or 'location'
        safe_loc = safe_loc.replace(' ', '_')[:40]
        filename = f'services_w{worker.pk}_{safe_loc}.pdf'

    elif report_type == 'services_all':
        workers = list(SocialWorker.objects.order_by('last_name', 'first_name'))
        locations = list(ServiceLocation.objects.order_by('name'))
        worker_ids = [w.pk for w in workers]
        all_for_panel = list(
            ServiceRecipient.objects.filter(social_worker_id__in=worker_ids)
            .select_related('location')
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
            PH('Населённый пункт'), PH('Подопечных'),
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
    workload_summary,
)
