"""
Синхронизация строки учёта нагрузки с карточкой подопечного (ServiceRecipient).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from .models import ServiceLocation, ServiceRecipient, SocialWorker
from .visit_schedule import validate_visit_frequency_and_days


def map_visits_per_week_to_frequency(vpw: Decimal) -> str:
    """Соответствие кратности «раз в неделю» полю visit_frequency подопечного."""
    v = float(vpw or 0)
    if v >= 6:
        return 'daily'
    if v <= 0:
        return '1'
    i = int(round(v))
    i = min(5, max(1, i))
    return str(i)


def worker_has_assignment_at_location(social_worker: SocialWorker, location: ServiceLocation | None) -> bool:
    """Есть ли у сотрудника подопечные с этим населённым пунктом (закрепление в базе)."""
    if location is None:
        return True
    return ServiceRecipient.objects.filter(
        social_worker_id=social_worker.pk,
        location_id=location.pk,
    ).exists()


def sync_service_recipient_from_workload(wr) -> list[str]:
    """
    Обновляет подопечного из сохранённой строки нагрузки: кратность, дата приёма, пункт, работник.
    Возвращает предупреждения, если кратность не удалось согласовать с полем «дни посещений».
    """
    warnings: list[str] = []
    if not wr.recipient_id:
        return warnings

    r = ServiceRecipient.objects.get(pk=wr.recipient_id)
    new_freq = map_visits_per_week_to_frequency(wr.visits_per_week or Decimal('0'))
    freq_msg = validate_visit_frequency_and_days(new_freq, r.visit_days)
    if freq_msg is None:
        r.visit_frequency = new_freq
    else:
        warnings.append(
            'Кратность посещений в карточке подопечного не изменена: ' + freq_msg
        )

    if r.admission_date is None:
        r.admission_date = date(wr.period_year, wr.period_month, 1)

    r.social_worker_id = wr.social_worker_id
    if wr.location_id:
        r.location_id = wr.location_id

    try:
        r.full_clean()
        r.save()
    except ValidationError as e:
        for field, errs in e.error_dict.items():
            for err in errs:
                warnings.append(f'Карточка подопечного: {field}: {err}')
    return warnings
