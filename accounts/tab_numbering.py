# -*- coding: utf-8 -*-
"""После удаления записей пересчитывает колонку «№» (табельный номер) / инв. номер без пропусков (1,2,3…)."""
import re

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ServiceRecipient, SocialWorker
from inventory.models import InventoryUnit


def _leading_int(value) -> int:
    if value is None:
        return 0
    s = str(value).strip()
    if not s:
        return 0
    m = re.match(r'^(-?\d+)', s)
    if not m:
        return 0
    try:
        v = int(m.group(1))
        return v if v >= 0 else 0
    except ValueError:
        return 0


def compact_social_worker_employee_ids() -> None:
    """№ работников: 1, 2, 3… (порядок — по прежнему числу в номере, затем pk)."""
    rows = list(SocialWorker.objects.all())
    if not rows:
        return
    rows.sort(key=lambda w: (_leading_int(w.employee_id), w.pk))
    temp_fmt = '_wr_{}'
    with transaction.atomic():
        for w in rows:
            SocialWorker.objects.filter(pk=w.pk).update(employee_id=temp_fmt.format(w.pk))
        for i, w in enumerate(rows, start=1):
            SocialWorker.objects.filter(pk=w.pk).update(employee_id=str(i))


def compact_service_recipient_employee_ids() -> None:
    """№ подопечных: 1, 2, 3… (как у соцработников, без префикса R-)."""
    rows = list(ServiceRecipient.objects.all())
    if not rows:
        return

    def sort_key(r):
        raw = (r.employee_id or '').strip()
        m = re.match(r'^R-(\d+)$', raw, re.IGNORECASE)
        if m:
            return (0, int(m.group(1)), r.pk)
        n = _leading_int(raw)
        if n:
            return (0, n, r.pk)
        return (1, raw.lower(), r.pk)

    rows.sort(key=sort_key)
    temp_fmt = '_rr_{}'
    with transaction.atomic():
        for r in rows:
            ServiceRecipient.objects.filter(pk=r.pk).update(employee_id=temp_fmt.format(r.pk))
        for i, r in enumerate(rows, start=1):
            ServiceRecipient.objects.filter(pk=r.pk).update(employee_id=str(i))


def compact_inventory_unit_numbers() -> None:
    """Инв. номера единиц учёта: 1, 2, 3… с одинаковой длиной (например 01…99)."""
    rows = list(InventoryUnit.objects.all())
    if not rows:
        return
    rows.sort(key=lambda u: (_leading_int(u.inventory_number), u.pk))
    width = max(1, len(str(len(rows))))
    temp_fmt = '__inv_re_{}__'
    with transaction.atomic():
        for u in rows:
            InventoryUnit.objects.filter(pk=u.pk).update(inventory_number=temp_fmt.format(u.pk))
        for i, u in enumerate(rows, start=1):
            InventoryUnit.objects.filter(pk=u.pk).update(inventory_number=str(i).zfill(width))


@receiver(
    post_delete,
    sender=SocialWorker,
    dispatch_uid='accounts.tab_numbering.post_delete_social_worker',
)
def _after_social_worker_delete_renumber(sender, **kwargs):
    compact_social_worker_employee_ids()


@receiver(
    post_delete,
    sender=ServiceRecipient,
    dispatch_uid='accounts.tab_numbering.post_delete_service_recipient',
)
def _after_recipient_delete_renumber(sender, **kwargs):
    compact_service_recipient_employee_ids()


@receiver(
    post_delete,
    sender=InventoryUnit,
    dispatch_uid='accounts.tab_numbering.post_delete_inventory_unit',
)
def _after_inventory_unit_delete_renumber(sender, **kwargs):
    compact_inventory_unit_numbers()
