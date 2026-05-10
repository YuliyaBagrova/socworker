# -*- coding: utf-8 -*-
"""
Дополнительные представления (CSV/PDF панелей, учёт нагрузки).
Подключаются в конце accounts.views, чтобы не дублировать огромный файл целиком.
"""
from __future__ import annotations

import csv
import io
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, DecimalField, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, Lower
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import strip_tags
from urllib.parse import urlencode

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from .inv_report_gate import (
    reject_inv_manager_soc_report,
    reject_inv_manager_unless_inventory_report,
)
from .forms import WorkloadRecordForm
from .models import (
    PlannedVisit,
    SafetyBriefingRecord,
    ServiceLocation,
    ServiceRecipient,
    SocialWorker,
    WorkloadRecord,
    WORKLOAD_LOAD_COEF_REFERENCE_HOURS,
    workload_rate_from_load,
)
from .visit_schedule import (
    validate_visit_frequency_and_days,
    visits_per_week_from_frequency,
)
from .workload_address_prefill import resolve_workload_prefill_for_recipient
from .workload_sync import sync_service_recipient_from_workload

MEDICAL_CHECKUP_VALID_DAYS = 365


def _export_plain_text(value, max_len=500):
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
    loc = getattr(recipient, 'location', None)
    if loc:
        return f'{loc.get_location_type_display()} {loc.name}'.strip()
    return '—'


def _inventory_responsible_export_cell(user):
    if getattr(user, 'last_name', None) or getattr(user, 'first_name', None):
        name = f'{user.last_name or ""} {user.first_name or ""}'.strip()
        return f'{name} ({user.username})'
    return user.username


def _register_pdf_font():
    font_name = 'CyrFontExtra'
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


def _recipient_matches_location(recipient, location):
    if recipient.location_id == location.pk:
        return True
    name = (location.name or '').strip()
    if not name or recipient.location_id:
        return False
    addr = (recipient.address or '').lower()
    return name.lower() in addr


def _recipients_for_service(worker, location):
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


def _wl_sort_param(raw) -> str:
    s = (raw or 'surname').strip()
    if s not in ('tab_asc', 'tab_desc', 'surname'):
        return 'surname'
    return s


WORKLOAD_JOURNAL_SORT_CHOICES = frozenset({
    'surname',
    'tab_asc',
    'tab_desc',
    'load_asc',
    'load_desc',
    'rate_asc',
    'rate_desc',
})


def _workload_journal_sort_param(raw) -> str:
    s = (raw or 'surname').strip()
    if s not in WORKLOAD_JOURNAL_SORT_CHOICES:
        return 'surname'
    return s


def _workload_journal_sort_from_request(data) -> str:
    """Параметр панели нагрузки: `wl_sort` (предпочтительно) или устаревший `sort`."""
    if data is None:
        return _workload_journal_sort_param('')
    raw = data.get('wl_sort') or data.get('sort') or ''
    return _workload_journal_sort_param(raw)


def _workload_journal_queryset_ordered(qs, sort_order: str):
    """Порядок строк журнала в БД (ORDER BY).

    Режимы «Фамилия подопечного», «мин./макс. коэффициент», «мин./макс. ставка»: общая сортировка по всей таблице;
    строка ИТОГО по-прежнему после последней строки каждого работника.
    Режим таб. №: сначала соц. работник (ФИО А–Я), затем номер.
    """
    so = _workload_journal_sort_param(sort_order)
    zero_dec = Value(Decimal('0'), output_field=DecimalField(max_digits=8, decimal_places=4))
    tie_ln = Case(
        When(recipient__isnull=False, then=Lower(Coalesce(F('recipient__last_name'), Value('')))),
        default=Lower(Coalesce(F('social_worker__last_name'), Value(''))),
    )
    tie_fn = Case(
        When(recipient__isnull=False, then=Lower(Coalesce(F('recipient__first_name'), Value('')))),
        default=Lower(Coalesce(F('social_worker__first_name'), Value(''))),
    )
    qs = qs.annotate(_wl_tie_ln=tie_ln, _wl_tie_fn=tie_fn)
    base_worker = (
        'social_worker__last_name',
        'social_worker__first_name',
        'social_worker_id',
    )
    if so == 'surname':
        # По всему журналу по тому, что видно в колонке ФИО: подопечный или (если пусто) работник.
        # Не ставим работника первым — иначе фамилии подопечных из разных закреплений не смешиваются А–Я.
        return qs.order_by(
            '_wl_tie_ln',
            '_wl_tie_fn',
            'social_worker_id',
            'pk',
        )
    if so == 'load_asc':
        return qs.annotate(_wl_sort_val=Coalesce(F('load_coefficient'), zero_dec)).order_by(
            '_wl_sort_val',
            '_wl_tie_ln',
            '_wl_tie_fn',
            'social_worker_id',
            'pk',
        )
    if so == 'load_desc':
        return qs.annotate(_wl_sort_val=Coalesce(F('load_coefficient'), zero_dec)).order_by(
            F('_wl_sort_val').desc(),
            '_wl_tie_ln',
            '_wl_tie_fn',
            'social_worker_id',
            'pk',
        )
    if so == 'rate_asc':
        return qs.annotate(_wl_sort_val=Coalesce(F('rate'), zero_dec)).order_by(
            '_wl_sort_val',
            '_wl_tie_ln',
            '_wl_tie_fn',
            'social_worker_id',
            'pk',
        )
    if so == 'rate_desc':
        return qs.annotate(_wl_sort_val=Coalesce(F('rate'), zero_dec)).order_by(
            F('_wl_sort_val').desc(),
            '_wl_tie_ln',
            '_wl_tie_fn',
            'social_worker_id',
            'pk',
        )
    tab_emp = Case(
        When(recipient__isnull=False, then=F('recipient__employee_id')),
        default=F('social_worker__employee_id'),
    )
    qs_tab = qs.annotate(_wl_tab_n=Cast(tab_emp, IntegerField()))
    if so == 'tab_asc':
        return qs_tab.order_by(*base_worker, '_wl_tab_n', '_wl_tie_ln', '_wl_tie_fn', 'pk')
    if so == 'tab_desc':
        return qs_tab.order_by(*base_worker, F('_wl_tab_n').desc(), '_wl_tie_ln', '_wl_tie_fn', 'pk')
    return qs.order_by(*base_worker, '_wl_tie_ln', '_wl_tie_fn', 'pk')


def _workload_wl_context(year: int, month: int, worker_s: str, journal_sort: str | None = None) -> dict:
    return {
        'wl_year': year,
        'wl_month': month,
        'wl_worker': worker_s or '',
        'wl_sort': _workload_journal_sort_param(journal_sort),
    }


def _workload_panel_url(
    year: int,
    month: int,
    worker_id: str = '',
    journal_sort: str | None = None,
) -> str:
    params = {'year': str(year), 'month': str(month)}
    if worker_id:
        params['worker'] = str(worker_id)
    if journal_sort is not None and str(journal_sort).strip():
        params['wl_sort'] = _workload_journal_sort_param(journal_sort)
    return reverse('accounts:workload_panel') + '?' + urlencode(params)


def _workload_recipients_by_worker_map() -> dict:
    """JSON: подопечные с пунктом и типом жилья по «Адрес» (и при отсутствии — по полям карточки)."""
    all_locations = list(ServiceLocation.objects.all())
    out: dict[str, list[dict]] = {}
    for r in (
        ServiceRecipient.objects.filter(social_worker__isnull=False)
        .select_related('location', 'social_worker')
        .order_by('last_name', 'first_name')
    ):
        k = str(r.social_worker_id)
        loc_id, housing_type, label = resolve_workload_prefill_for_recipient(r, all_locations)
        vpw_n = visits_per_week_from_frequency(r.visit_frequency or '')
        try:
            vpw = float(vpw_n) if vpw_n is not None else 0.0
        except (TypeError, ValueError):
            vpw = 0.0
        out.setdefault(k, []).append(
            {
                'id': r.pk,
                'name': r.get_full_name(),
                'location_id': loc_id,
                'location_label': label,
                'housing_type': housing_type,
                'visits_per_week': vpw,
            }
        )
    return out


def _workload_social_worker_employee_ids() -> dict[str, str]:
    """pk работника → табельный номер (для формы учёта нагрузки)."""
    return {
        str(w.pk): (w.employee_id or '').strip()
        for w in SocialWorker.objects.only('pk', 'employee_id').order_by('pk')
    }


WORKLOAD_JOURNAL_SORT = 'surname'


def _build_workload_groups(year: int, month: int, worker_pk: str | None, sort_order: str = WORKLOAD_JOURNAL_SORT):
    """Строки журнала в порядке сортировки панели; после последней строки каждого работника — ИТОГО.

    Фамилия подопечного, мин./макс. коэффициент и ставка: общий порядок по всей таблице; итог после последней строки работника.
    """
    qs = WorkloadRecord.objects.filter(
        period_year=year,
        period_month=month,
    ).select_related('social_worker', 'recipient', 'location')
    if worker_pk and str(worker_pk).isdigit():
        qs = qs.filter(social_worker_id=int(worker_pk))
    so = _workload_journal_sort_param(sort_order)
    qs = _workload_journal_queryset_ordered(qs, so)
    records = list(qs)
    if not records:
        return []

    totals: dict[int, dict] = {}
    for r in records:
        tid = r.social_worker_id
        if tid not in totals:
            totals[tid] = {'minutes': 0, 'load_sum': Decimal('0')}
        totals[tid]['minutes'] += int(r.worked_minutes_month or 0)
        totals[tid]['load_sum'] += r.load_coefficient or Decimal('0')

    last_idx: dict[int, int] = {}
    for i, r in enumerate(records):
        last_idx[r.social_worker_id] = i

    items: list[dict] = []
    num = 0
    for i, r in enumerate(records):
        num += 1
        items.append({'kind': 'data', 'num': num, 'record': r})
        if last_idx[r.social_worker_id] == i:
            sw = r.social_worker
            t = totals[sw.pk]
            total_minutes = t['minutes']
            total_hours = (Decimal(total_minutes) / Decimal('60')).quantize(Decimal('0.01'))
            load_sum = t['load_sum'].quantize(Decimal('0.01'))
            rate = workload_rate_from_load(load_sum)
            items.append({
                'kind': 'subtotal',
                'worker': sw,
                'total_minutes': total_minutes,
                'total_hours': total_hours,
                'load_sum': load_sum,
                'rate': rate,
            })
    return items


def _pdf_table_response(title: str, filename: str, headers: list[str], rows: list[list[str]]):
    font_name = _register_pdf_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'T',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=14,
        spaceAfter=6 * mm,
    )
    cell_style = ParagraphStyle('C', fontName=font_name, fontSize=7, leading=9)
    header_style = ParagraphStyle(
        'H',
        fontName=font_name,
        fontSize=7,
        leading=9,
        textColor=colors.whitesmoke,
    )

    def P(t, style=cell_style):
        return Paragraph(str(t).replace('\n', '<br/>'), style)

    def PH(t):
        return Paragraph(str(t), header_style)

    data = [[PH(h) for h in headers]]
    for row in rows:
        data.append([P(c) for c in row])

    ncols = len(headers)
    col_width = (landscape(A4)[0] - 24 * mm) / max(ncols, 1)
    col_widths = [col_width] * ncols

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dde1e6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fb')]),
    ]))
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    story = [
        Paragraph(f'{title} — {now}', title_style),
        table,
        Paragraph(f'Строк: {len(rows)}. Сформировано: {now}', ParagraphStyle(
            'I', fontName=font_name, fontSize=7, textColor=colors.grey, spaceBefore=4 * mm,
        )),
    ]
    doc.build(story)
    buf.seek(0)
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _csv_response(filename: str, header: list[str], rows: list[list]):
    buf = io.StringIO()
    buf.write('\ufeff')
    w = csv.writer(buf, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    for row in rows:
        w.writerow(row)
    response = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ── Отчёты CSV (зеркало report_pdf) ───────────────────────────────────────


@login_required
def report_csv(request, report_type):
    """CSV-выгрузка отчётов (те же типы, что и для PDF)."""
    rej = reject_inv_manager_unless_inventory_report(request, report_type)
    if rej:
        return rej
    from .views import (
        _apply_tab_employee_sort,
        _inventory_report_order_qs,
        _recipients_filtered_qs,
        _report_tab_sort_param,
        _social_workers_filtered_qs,
        _inventory_units_filtered_qs,
    )

    if report_type == 'social_workers':
        tab_sort = _report_tab_sort_param(request)
        workers_ordered_qs = _apply_tab_employee_sort(
            _social_workers_filtered_qs(request), tab_sort,
        )
        filename = 'social_workers_report.csv'

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
                filename = 'social_workers_selected_report.csv'
            else:
                workers = list(workers_ordered_qs)
        else:
            workers = list(workers_ordered_qs)

        header = [
            '№', 'ФИО', 'Год рожд.', 'Адрес', 'Телефон', 'Мед. осмотр',
            'Дата приёма на работу', 'Примечания', 'Статус',
        ]
        rows = []
        for w in workers:
            rows.append([
                w.employee_id or '—',
                w.get_full_name(),
                w.birth_date.strftime('%Y') if w.birth_date else '—',
                w.address or '—',
                w.phone or '—',
                w.get_medical_checkup_display(),
                w.hire_date.strftime('%d.%m.%Y') if w.hire_date else '—',
                _export_plain_text(w.notes, max_len=2000),
                w.get_status_display(),
            ])
        return _csv_response(filename, header, rows)

    if report_type == 'recipients':
        tab_sort = _report_tab_sort_param(request)
        recipients_ordered_qs = _apply_tab_employee_sort(
            _recipients_filtered_qs(request),
            tab_sort,
        )
        filename = 'recipients_report.csv'

        if request.method == 'POST':
            scope = request.POST.get('scope', 'all')
            if scope == 'selected':
                raw_ids = request.POST.getlist('recipient_ids')
                pks = [int(x) for x in raw_ids if str(x).strip().isdigit()]
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
                filename = 'recipients_selected_report.csv'
            else:
                recipients = list(recipients_ordered_qs)
        else:
            recipients = list(recipients_ordered_qs)

        header = [
            '№', 'ФИО', 'Год рожд.', 'Телефон', 'Адрес',
            'Населённый пункт', 'Тип жилья',
            'Гр. инвал.', 'Оплата', 'Кратность',
            'Категория', 'Дата приёма', 'Дни посещ.', 'АПИ', 'Примечания', 'Соц. работник',
        ]
        rows = []
        for r in recipients:
            rows.append([
                r.employee_id or '—',
                r.get_full_name(),
                r.birth_date.strftime('%Y') if r.birth_date else '—',
                r.phone or '—',
                r.address or '—',
                _recipient_location_export_label(r),
                r.get_housing_type_display(),
                r.get_disability_group_display(),
                f'{r.payment_percent}%',
                r.get_visit_frequency_display(),
                r.get_living_status_display(),
                r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—',
                r.visit_days or '—',
                r.fire_detector_count,
                _export_plain_text(r.notes, max_len=2000),
                r.social_worker.get_full_name() if r.social_worker else '—',
            ])
        return _csv_response(filename, header, rows)

    if report_type == 'assigned':
        filename = 'assigned_persons_report.csv'
        row_tuples = None
        pairs = None
        sort = 'all'

        if request.method == 'POST':
            sort = request.POST.get('sort', 'all')
            scope = request.POST.get('scope', 'all')
            search = request.POST.get('search', '').strip()
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
                filename = 'assigned_persons_selected_report.csv'
            else:
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

        if sort == 'recipient':
            header = [
                '№', 'ФИО подопечного', 'Телефон подопечного',
                'Адрес подопечного', 'ФИО соц. работника', 'Телефон соц. работника',
            ]
        else:
            header = [
                '№', 'ФИО соц. работника', 'Телефон соц. работника',
                'ФИО подопечного', 'Телефон подопечного', 'Адрес подопечного',
            ]
        rows = []

        def append_row(index, w, r):
            if sort == 'recipient':
                if r:
                    rows.append([
                        index, r.get_full_name(), r.phone or '—',
                        r.address or '—', w.get_full_name(), w.phone or '—',
                    ])
                else:
                    rows.append([
                        index, '—', '—', '—', w.get_full_name(), w.phone or '—',
                    ])
            else:
                if r:
                    rows.append([
                        index, w.get_full_name(), w.phone or '—',
                        r.get_full_name(), r.phone or '—', r.address or '—',
                    ])
                else:
                    rows.append([
                        index, w.get_full_name(), w.phone or '—', '—', '—', '—',
                    ])

        if row_tuples is not None:
            for i, (w, r) in enumerate(row_tuples, 1):
                append_row(i, w, r)
        else:
            for i, r in enumerate(pairs, 1):
                append_row(i, r.social_worker, r)

        return _csv_response(filename, header, rows)

    if report_type == 'services':
        try:
            worker_pk = int(request.GET.get('worker_pk', ''))
            location_pk = int(request.GET.get('location_pk', ''))
        except (TypeError, ValueError):
            messages.warning(request, 'Укажите работника и населённый пункт.')
            return redirect('accounts:services_panel')
        worker = get_object_or_404(SocialWorker, pk=worker_pk)
        location = get_object_or_404(ServiceLocation, pk=location_pk)
        recipients = list(_recipients_for_service(worker, location))
        if not recipients:
            messages.warning(request, 'Нет данных для выбранной связки.')
            return redirect('accounts:services_detail', worker_pk=worker_pk, location_pk=location_pk)
        header = [
            '№', 'Ф.И.О.', 'Год рожд.', 'Адрес проживания',
            'Населённый пункт', 'Тип жилья',
            'Гр. инвал.', 'Оплата', 'Кратность',
            'Категория', 'Дата приёма', 'Дни посещ.', 'АПИ',
        ]
        rows = []
        for r in recipients:
            rows.append([
                r.employee_id or '—',
                r.get_full_name(),
                r.birth_date.strftime('%Y') if r.birth_date else '—',
                r.address or '—',
                _recipient_location_export_label(r),
                r.get_housing_type_display(),
                r.get_disability_group_display(),
                f'{r.payment_percent}%',
                r.get_visit_frequency_display(),
                r.get_living_status_display(),
                r.admission_date.strftime('%d.%m.%Y') if r.admission_date else '—',
                r.visit_days or '—',
                r.fire_detector_count,
            ])
        safe_loc = ''.join(
            c for c in (location.name or 'location') if c.isalnum() or c in (' ', '-', '_')
        ).strip() or 'location'
        safe_loc = safe_loc.replace(' ', '_')[:40]
        filename = f'services_w{worker_pk}_{safe_loc}.csv'
        return _csv_response(filename, header, rows)

    if report_type == 'services_all':
        workers = list(SocialWorker.objects.order_by('last_name', 'first_name'))
        locations = list(ServiceLocation.objects.order_by('name'))
        worker_ids = [w.pk for w in workers]
        all_for_panel = list(
            ServiceRecipient.objects.filter(social_worker_id__in=worker_ids)
            .select_related('location', 'social_worker')
            .order_by('last_name', 'first_name')
        )
        header = ['№', 'Социальный работник', 'Населённый пункт', 'Записей']
        rows = []
        i = 0
        for w in workers:
            for loc in locations:
                cnt = sum(
                    1 for r in all_for_panel
                    if r.social_worker_id == w.pk and _recipient_matches_location(r, loc)
                )
                i += 1
                loc_label = f'{loc.get_location_type_display()} {loc.name}'.strip()
                rows.append([i, w.get_full_name(), loc_label, cnt])
        return _csv_response('services_all_report.csv', header, rows)

    if report_type == 'inventory':
        from inventory.permissions import has_inventory_access

        if not has_inventory_access(request.user):
            messages.error(request, 'Нет доступа к отчёту инвентаризации.')
            return redirect('accounts:report_select')

        inv_sort = request.POST.get('sort') or request.GET.get('sort', 'inv_asc')
        units_base_qs = _inventory_units_filtered_qs(request)
        units_ordered_qs = _inventory_report_order_qs(units_base_qs, inv_sort)
        filename = 'inventory_report.csv'

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
                filename = 'inventory_selected_report.csv'
            else:
                units = list(units_ordered_qs)
        else:
            units = list(units_ordered_qs)

        header = [
            'Инв. №',
            'Фото',
            'Название',
            'Стоимость (бел.руб.)',
            'Ответственный',
        ]
        rows = []
        for u in units:
            rows.append([
                u.inventory_number,
                'Да' if getattr(u, 'equipment_photo', None) else 'Нет',
                u.name,
                str(u.cost),
                _inventory_responsible_export_cell(u.responsible),
            ])
        return _csv_response(filename, header, rows)

    return redirect('accounts:report_select')


# ── Медосмотр PDF/CSV ─────────────────────────────────────────────────────


def _medical_workers_queryset(worker, status, sort_order='surname'):
    from .views import _apply_tab_employee_sort

    qs = SocialWorker.objects.filter(medical_panel_registered=True)
    if worker and str(worker).isdigit():
        qs = qs.filter(pk=int(worker))
    if status:
        qs = qs.filter(status=status)
    return _apply_tab_employee_sort(qs, _wl_sort_param(sort_order))


def _medical_worker_row(w: SocialWorker, today: date):
    """Столбцы как в таблице панели медосмотра (без чекбокса и действий)."""
    raw_notes = (w.medical_notes or '').replace('\r', ' ').replace('\n', ' ').strip()
    notes_short = raw_notes[:120] + ('…' if len(raw_notes) > 120 else '')
    last = w.last_medical_checkup_date
    if last:
        valid_until = last + timedelta(days=MEDICAL_CHECKUP_VALID_DAYS)
        goden = valid_until.strftime('%d.%m.%Y')
        if valid_until < today:
            days_ov = (today - valid_until).days
            goden = f'{goden} (просрочено +{days_ov} дн.)'
            akt12 = f'Нет (+{days_ov} дн.)'
        else:
            akt12 = 'Да'
        last_s = last.strftime('%d.%m.%Y')
    else:
        goden = '—'
        akt12 = 'Нет данных'
        last_s = '—'
    return [
        w.employee_id or '—',
        w.get_full_name(),
        last_s,
        goden,
        akt12,
        w.medical_checkup_planned_date.strftime('%d.%m.%Y') if w.medical_checkup_planned_date else '—',
        w.get_medical_checkup_display(),
        notes_short or '—',
    ]


@login_required
def medical_checkup_panel_pdf(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:medical_checkup_panel')
    scope = request.POST.get('scope', 'all')
    worker = request.POST.get('worker', '')
    status = request.POST.get('status', '')
    sort_order = request.POST.get('sort', 'surname')
    qs = _medical_workers_queryset(worker, status, sort_order)
    today = date.today()

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('medical_worker_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте сотрудников или выберите полный список.')
            return redirect('accounts:medical_checkup_panel')
        workers = list(qs.filter(pk__in=pks))
    else:
        workers = list(qs)

    headers = [
        '№', 'ФИО', 'Дата последнего осмотра',
        'Годен до', 'Актуально 12 мес.', 'Назначен на', 'Поле в системе', 'Примечания',
    ]
    rows = [_medical_worker_row(w, today) for w in workers]
    return _pdf_table_response(
        'Прохождение медосмотра',
        'medical_checkup_panel.pdf',
        headers,
        rows,
    )


@login_required
def medical_checkup_panel_csv(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:medical_checkup_panel')
    scope = request.POST.get('scope', 'all')
    worker = request.POST.get('worker', '')
    status = request.POST.get('status', '')
    sort_order = request.POST.get('sort', 'surname')
    qs = _medical_workers_queryset(worker, status, sort_order)
    today = date.today()

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('medical_worker_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте сотрудников или выберите полный список.')
            return redirect('accounts:medical_checkup_panel')
        workers = list(qs.filter(pk__in=pks))
    else:
        workers = list(qs)

    header = [
        '№', 'ФИО', 'Дата последнего осмотра',
        'Годен до', 'Актуально 12 мес.', 'Назначен на', 'Поле в системе', 'Примечания',
    ]
    rows = [_medical_worker_row(w, today) for w in workers]
    return _csv_response('medical_checkup_panel.csv', header, rows)


# ── ТБ PDF/CSV ────────────────────────────────────────────────────────────


def _safety_records_filtered(worker, title_q, sort_order='surname'):
    from .views import _apply_social_worker_related_tab_sort

    qs = SafetyBriefingRecord.objects.select_related('social_worker').all()
    if worker and str(worker).isdigit():
        qs = qs.filter(social_worker_id=int(worker))
    if title_q:
        qs = qs.filter(briefing_title__icontains=title_q)
    return _apply_social_worker_related_tab_sort(
        qs, _wl_sort_param(sort_order), 'social_worker', ('-briefing_date', 'pk'),
    )


@login_required
def safety_briefing_panel_pdf(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    scope = request.POST.get('scope', 'all')
    worker = request.POST.get('worker', '')
    title_q = request.POST.get('title', '').strip()
    sort_order = request.POST.get('sort', 'surname')
    qs = _safety_records_filtered(worker, title_q, sort_order)

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('briefing_record_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте записи или выберите полный список.')
            return redirect('accounts:safety_briefing_panel')
        records = list(qs.filter(pk__in=pks))
    else:
        records = list(qs)

    # Как колонки панели ТБ + дата инструктажа после названия
    headers = [
        '№', 'ФИО', 'Название инструктажа', 'Дата инструктажа', 'Прохождение', 'Примечание',
    ]
    rows = []
    for rec in records:
        rows.append([
            rec.social_worker.employee_id or '—',
            rec.social_worker.get_full_name(),
            rec.briefing_title,
            rec.briefing_date.strftime('%d.%m.%Y'),
            'Прошёл' if rec.passed else 'Не пройден',
            (rec.notes or '—').replace('\r', ' ').replace('\n', ' ')[:500],
        ])
    return _pdf_table_response('Техника безопасности', 'safety_briefing_panel.pdf', headers, rows)


@login_required
def safety_briefing_panel_csv(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:safety_briefing_panel')
    scope = request.POST.get('scope', 'all')
    worker = request.POST.get('worker', '')
    title_q = request.POST.get('title', '').strip()
    sort_order = request.POST.get('sort', 'surname')
    qs = _safety_records_filtered(worker, title_q, sort_order)

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('briefing_record_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте записи или выберите полный список.')
            return redirect('accounts:safety_briefing_panel')
        records = list(qs.filter(pk__in=pks))
    else:
        records = list(qs)

    header = [
        '№', 'ФИО', 'Название инструктажа', 'Дата инструктажа', 'Прохождение', 'Примечание',
    ]
    rows = []
    for rec in records:
        rows.append([
            rec.social_worker.employee_id or '—',
            rec.social_worker.get_full_name(),
            rec.briefing_title,
            rec.briefing_date.strftime('%d.%m.%Y'),
            'Прошёл' if rec.passed else 'Не пройден',
            rec.notes or '—',
        ])
    return _csv_response('safety_briefing_panel.csv', header, rows)


# ── Планирование визитов PDF/CSV ──────────────────────────────────────────


def _visit_planning_recipients(data):
    from .views import _apply_tab_employee_sort

    sort_order = data.get('sort', 'surname')
    if sort_order not in ('tab_asc', 'tab_desc', 'surname'):
        sort_order = 'surname'
    recipients = ServiceRecipient.objects.filter(
        social_worker__isnull=False,
        visit_planning_panel_registered=True,
    ).select_related('social_worker')
    wid = data.get('worker')
    if wid and str(wid).isdigit():
        recipients = recipients.filter(social_worker_id=int(wid))
    living = data.get('living')
    if living:
        recipients = recipients.filter(living_status=living)
    wstatus = data.get('wstatus')
    if wstatus:
        recipients = recipients.filter(social_worker__status=wstatus)
    rid = data.get('recipient')
    if rid and str(rid).isdigit():
        recipients = recipients.filter(pk=int(rid))
    return list(_apply_tab_employee_sort(recipients, sort_order))


def _visit_planning_upcoming_by_recipient(rec_list):
    """Запланированные визиты с сегодняшнего дня: recipient_id -> список PlannedVisit."""
    if not rec_list:
        return {}
    ids = [r.pk for r in rec_list]
    today = date.today()
    by_rec = defaultdict(list)
    for pv in PlannedVisit.objects.filter(
        recipient_id__in=ids,
        visit_date__gte=today,
    ).order_by('visit_date', 'visit_time', 'pk'):
        by_rec[pv.recipient_id].append(pv)
    return by_rec


def _visit_planning_upcoming_export_cell(by_rec, recipient_id):
    pvs = by_rec.get(recipient_id, ())
    if not pvs:
        return '—'
    parts = []
    for pv in pvs:
        s = pv.visit_date.strftime('%d.%m.%Y')
        if pv.visit_time:
            s += ' ' + pv.visit_time.strftime('%H:%M')
        parts.append(s)
    return '; '.join(parts)


def _visit_planning_consistency_cell(r: ServiceRecipient) -> str:
    """Как колонка «Согласованность» в таблице планирования визитов."""
    mismatch = validate_visit_frequency_and_days(r.visit_frequency, r.visit_days)
    if mismatch is None:
        return 'Да'
    return f'Несовпадение: {_export_plain_text(mismatch, 220)}'


@login_required
def visit_planning_pdf(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:visit_planning')
    scope = request.POST.get('scope', 'all')
    rec_list = _visit_planning_recipients(request.POST)

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('recipient_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте подопечных или выберите полный список.')
            return redirect('accounts:visit_planning')
        id_set = set(pks)
        rec_list = [r for r in rec_list if r.pk in id_set]

    upcoming_map = _visit_planning_upcoming_by_recipient(rec_list)
    headers = [
        '№', 'Подопечный', 'Соц. работник', 'Кратность', 'Дни посещений', 'Виз./нед.',
        'Запланированные визиты', 'Согласованность',
    ]
    rows = []
    for r in rec_list:
        n = visits_per_week_from_frequency(r.visit_frequency)
        rows.append([
            r.employee_id or '—',
            r.get_full_name(),
            r.social_worker.get_full_name() if r.social_worker else '—',
            r.get_visit_frequency_display(),
            (r.visit_days or '').strip() or '—',
            str(n),
            _visit_planning_upcoming_export_cell(upcoming_map, r.pk),
            _visit_planning_consistency_cell(r),
        ])
    return _pdf_table_response('Планирование визитов', 'visit_planning.pdf', headers, rows)


@login_required
def visit_planning_csv(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method != 'POST':
        return redirect('accounts:visit_planning')
    scope = request.POST.get('scope', 'all')
    rec_list = _visit_planning_recipients(request.POST)

    if scope == 'selected':
        pks = [int(x) for x in request.POST.getlist('recipient_ids') if str(x).strip().isdigit()]
        pks = list(dict.fromkeys(pks))
        if not pks:
            messages.warning(request, 'Отметьте подопечных или выберите полный список.')
            return redirect('accounts:visit_planning')
        id_set = set(pks)
        rec_list = [r for r in rec_list if r.pk in id_set]

    upcoming_map = _visit_planning_upcoming_by_recipient(rec_list)
    header = [
        '№', 'Подопечный', 'Соц. работник', 'Кратность', 'Дни посещений', 'Виз./нед.',
        'Запланированные визиты', 'Согласованность',
    ]
    rows = []
    for r in rec_list:
        n = visits_per_week_from_frequency(r.visit_frequency)
        rows.append([
            r.employee_id or '—',
            r.get_full_name(),
            r.social_worker.get_full_name() if r.social_worker else '—',
            r.get_visit_frequency_display(),
            (r.visit_days or '').strip() or '—',
            str(n),
            _visit_planning_upcoming_export_cell(upcoming_map, r.pk),
            _visit_planning_consistency_cell(r),
        ])
    return _csv_response('visit_planning.csv', header, rows)


# ── Нагрузка: панель и журнал ─────────────────────────────────────────────


@login_required
def workload_panel(request):
    today = date.today()
    try:
        year = int(request.GET.get('year') or today.year)
        month = int(request.GET.get('month') or today.month)
    except (TypeError, ValueError):
        year, month = today.year, today.month
    month = max(1, min(12, month))
    year = max(2000, min(2100, year))

    worker_filter = request.GET.get('worker', '').strip()
    wl_sort = _workload_journal_sort_from_request(request.GET)
    workload_groups = _build_workload_groups(year, month, worker_filter or None, wl_sort)
    from .views import _apply_tab_employee_sort

    workers = _apply_tab_employee_sort(SocialWorker.objects.all(), WORKLOAD_JOURNAL_SORT)

    ctx = {
        'year': year,
        'month': month,
        'worker_filter': worker_filter,
        'wl_worker': worker_filter,
        'workload_groups': workload_groups,
        'workers': workers,
        'norm_hours_default': WORKLOAD_LOAD_COEF_REFERENCE_HOURS,
        **_workload_wl_context(year, month, worker_filter, wl_sort),
    }
    return render(request, 'accounts/workload_panel.html', ctx)


def _workload_records_qs(year_f, month_f, worker_f):
    qs = WorkloadRecord.objects.select_related(
        'social_worker', 'recipient', 'location',
    ).order_by('-period_year', '-period_month', 'social_worker__last_name', 'pk')
    if year_f and str(year_f).isdigit():
        qs = qs.filter(period_year=int(year_f))
    if month_f and str(month_f).isdigit():
        qs = qs.filter(period_month=int(month_f))
    if worker_f and str(worker_f).isdigit():
        qs = qs.filter(social_worker_id=int(worker_f))
    return qs


@login_required
def workload_records_list(request):
    """Раньше — плоский журнал; теперь тот же учёт на главной панели. Сохраняем URL для закладок."""
    params = {}
    y = request.GET.get('year', '').strip()
    m = request.GET.get('month', '').strip()
    w = request.GET.get('worker', '').strip()
    if y.isdigit():
        params['year'] = y
    if m.isdigit():
        params['month'] = m
    if w.isdigit():
        params['worker'] = w
    s = (request.GET.get('wl_sort') or request.GET.get('sort') or '').strip()
    if s:
        params['wl_sort'] = _workload_journal_sort_param(s)
    base = reverse('accounts:workload_panel')
    if params:
        base = base + '?' + urlencode(params)
    return redirect(base)


@login_required
def workload_record_create(request):
    today = date.today()
    initial = {}
    y = request.GET.get('year')
    m = request.GET.get('month')
    wk = request.GET.get('worker', '').strip()
    if y and str(y).isdigit():
        initial['period_year'] = int(y)
    if m and str(m).isdigit():
        initial['period_month'] = max(1, min(12, int(m)))
    if not initial.get('period_year'):
        initial['period_year'] = today.year
    if not initial.get('period_month'):
        initial['period_month'] = today.month
    if wk.isdigit():
        initial['social_worker'] = int(wk)

    if request.method == 'POST':
        form = WorkloadRecordForm(request.POST)
        if form.is_valid():
            obj = form.save()
            for msg in sync_service_recipient_from_workload(obj):
                messages.warning(request, msg)
            messages.success(request, 'Запись учёта сохранена.')
            sort_ret = (
                request.POST.get('return_sort')
                or request.GET.get('wl_sort')
                or request.GET.get('sort')
            )
            return redirect(_workload_panel_url(
                obj.period_year,
                obj.period_month,
                str(obj.social_worker_id),
                sort_ret,
            ))
    else:
        form = WorkloadRecordForm(initial=initial)

    py = initial.get('period_year', today.year)
    pm = initial.get('period_month', today.month)
    ctx = {
        'form': form,
        'is_edit': False,
        'record': None,
        'workload_recipients_by_worker': _workload_recipients_by_worker_map(),
        'workload_worker_employee_ids': _workload_social_worker_employee_ids(),
        'workload_default_year': py,
        'workload_default_month': pm,
        'wl_edit_recipient_id': None,
        'wl_edit_recipient_name': '',
        **_workload_wl_context(py, pm, wk or '', _workload_journal_sort_from_request(request.GET)),
    }
    return render(request, 'accounts/workload_record_form.html', ctx)


@login_required
def workload_record_edit(request, pk):
    record = get_object_or_404(
        WorkloadRecord.objects.select_related('social_worker', 'recipient', 'location'),
        pk=pk,
    )
    today = date.today()
    if request.method == 'POST':
        form = WorkloadRecordForm(request.POST, instance=record)
        if form.is_valid():
            obj = form.save()
            for msg in sync_service_recipient_from_workload(obj):
                messages.warning(request, msg)
            messages.success(request, 'Изменения сохранены.')
            sort_ret = (
                request.POST.get('return_sort')
                or request.GET.get('wl_sort')
                or request.GET.get('sort')
            )
            return redirect(_workload_panel_url(
                obj.period_year,
                obj.period_month,
                str(obj.social_worker_id),
                sort_ret,
            ))
    else:
        form = WorkloadRecordForm(instance=record)

    ctx = {
        'form': form,
        'is_edit': True,
        'record': record,
        'workload_recipients_by_worker': _workload_recipients_by_worker_map(),
        'workload_worker_employee_ids': _workload_social_worker_employee_ids(),
        'workload_default_year': record.period_year,
        'workload_default_month': record.period_month,
        'wl_edit_recipient_id': record.recipient_id,
        'wl_edit_recipient_name': record.recipient.get_full_name() if record.recipient_id else '',
        **_workload_wl_context(
            record.period_year,
            record.period_month,
            '',
            _workload_journal_sort_from_request(request.GET),
        ),
    }
    return render(request, 'accounts/workload_record_form.html', ctx)


@login_required
def workload_record_delete(request, pk):
    record = get_object_or_404(WorkloadRecord, pk=pk)
    if request.method == 'POST':
        py, pm = record.period_year, record.period_month
        sort_ret = (
            request.POST.get('return_sort')
            or request.GET.get('wl_sort')
            or request.GET.get('sort')
        )
        record.delete()
        messages.success(request, 'Запись удалена.')
        return redirect(_workload_panel_url(py, pm, '', sort_ret))
    ctx = {
        'record': record,
        **_workload_wl_context(
            record.period_year,
            record.period_month,
            '',
            _workload_journal_sort_from_request(request.GET),
        ),
    }
    return render(request, 'accounts/workload_record_confirm_delete.html', ctx)


@login_required
def workload_export_csv(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    year = request.GET.get('year', '').strip()
    month = request.GET.get('month', '').strip()
    worker = request.GET.get('worker', '').strip()
    qs = _workload_records_qs(year or None, month or None, worker)
    qs = qs.order_by('period_year', 'period_month', 'social_worker__last_name', 'pk')

    header = [
        'Год',
        'Месяц',
        'Работник',
        'Подопечный',
        'Населённый пункт',
        'Тип жилья',
        'Кратность (раз в неделю)',
        'Кратность (раз в месяц)',
        'Всего отработано за месяц (мин)',
        'Всего отработано за месяц (ч)',
        'Коэффициент нагрузки',
        'Ставка',
        'Примечание',
    ]
    rows = []
    for r in qs:
        rows.append([
            r.period_year,
            r.period_month,
            r.social_worker.get_full_name(),
            r.recipient.get_full_name() if r.recipient else '—',
            r.location.name if r.location else '—',
            r.get_housing_type_display(),
            str(r.visits_per_week),
            str(r.visits_per_month),
            r.worked_minutes_month,
            str(r.worked_hours_month),
            str(r.load_coefficient),
            str(r.rate),
            (r.notes or '').replace('\n', ' ')[:200],
        ])
    return _csv_response('workload_journal.csv', header, rows)


def _workload_pdf_csv_rows(
    year: int,
    month: int,
    worker_pk: str,
    scope: str,
    raw_ids: list[str],
    sort_order: str = WORKLOAD_JOURNAL_SORT,
):
    qs = WorkloadRecord.objects.filter(
        period_year=year,
        period_month=month,
    ).select_related('social_worker', 'recipient', 'location')
    if worker_pk and str(worker_pk).isdigit():
        qs = qs.filter(social_worker_id=int(worker_pk))
    qs = _workload_journal_queryset_ordered(qs, sort_order)
    records = list(qs)
    if scope == 'selected':
        id_set = {int(x) for x in raw_ids if str(x).strip().isdigit()}
        records = [r for r in records if r.pk in id_set]
    rows = []
    for r in records:
        name = r.recipient.get_full_name() if r.recipient else r.social_worker.get_full_name()
        loc = f'{r.location.get_location_type_display()} {r.location.name}'.strip() if r.location else '—'
        rows.append([
            name,
            loc,
            r.get_housing_type_display(),
            str(r.visits_per_week),
            str(r.visits_per_month),
            str(r.visit_duration_minutes),
            str(r.worked_minutes_month),
            str(r.worked_hours_month),
            str(r.work_time_norm_hours),
            str(r.load_coefficient),
            str(r.rate),
        ])
    return rows


@login_required
def workload_panel_pdf(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method not in ('GET', 'POST'):
        return redirect('accounts:workload_panel')
    data = request.POST if request.method == 'POST' else request.GET
    try:
        year = int(data.get('year') or 0)
        month = int(data.get('month') or 0)
    except (TypeError, ValueError):
        messages.error(request, 'Некорректный период.')
        return redirect('accounts:workload_panel')
    if request.method == 'GET':
        scope = 'all'
        worker_pk = data.get('worker', '').strip()
        raw_ids = []
    else:
        scope = request.POST.get('scope', 'all')
        worker_pk = request.POST.get('worker', '').strip()
        raw_ids = request.POST.getlist('workload_record_ids')
    sort_order = _workload_journal_sort_from_request(data)

    rows = _workload_pdf_csv_rows(year, month, worker_pk, scope, raw_ids, sort_order)
    if scope == 'selected' and not rows:
        messages.warning(request, 'Не выбраны строки для выгрузки.')
        return redirect('accounts:workload_panel')

    headers = [
        'ФИО соцработника / подопечного',
        'Населённый пункт',
        'Тип жилья',
        'Кратность (раз в неделю)',
        'Кратность (раз в месяц)',
        'Время 1 посещения (мин)',
        'Всего отработано за месяц (мин)',
        'Всего отработано за месяц (ч)',
        'Норма рабочего времени (ч)',
        'Коэффициент нагрузки',
        'Ставка',
    ]
    return _pdf_table_response(
        f'Учёт нагрузки {month:02d}.{year}',
        f'workload_{year}_{month:02d}.pdf',
        headers,
        rows,
    )


@login_required
def workload_panel_csv(request):
    rej = reject_inv_manager_soc_report(request)
    if rej:
        return rej
    if request.method not in ('GET', 'POST'):
        return redirect('accounts:workload_panel')
    data = request.POST if request.method == 'POST' else request.GET
    try:
        year = int(data.get('year') or 0)
        month = int(data.get('month') or 0)
    except (TypeError, ValueError):
        messages.error(request, 'Некорректный период.')
        return redirect('accounts:workload_panel')
    if request.method == 'GET':
        scope = 'all'
        worker_pk = data.get('worker', '').strip()
        raw_ids = []
    else:
        scope = request.POST.get('scope', 'all')
        worker_pk = request.POST.get('worker', '').strip()
        raw_ids = request.POST.getlist('workload_record_ids')
    sort_order = _workload_journal_sort_from_request(data)

    rows = _workload_pdf_csv_rows(year, month, worker_pk, scope, raw_ids, sort_order)
    if scope == 'selected' and not rows:
        messages.warning(request, 'Не выбраны строки для выгрузки.')
        return redirect('accounts:workload_panel')

    header = [
        'ФИО соцработника / подопечного',
        'Населённый пункт',
        'Тип жилья',
        'Кратность (раз в неделю)',
        'Кратность (раз в месяц)',
        'Время 1 посещения (мин)',
        'Всего отработано за месяц (мин)',
        'Всего отработано за месяц (ч)',
        'Норма рабочего времени (ч)',
        'Коэффициент нагрузки',
        'Ставка',
    ]
    return _csv_response(f'workload_{year}_{month:02d}.csv', header, rows)
