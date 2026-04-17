"""Номера РБ: хранение в виде +375 (XX) XXX-XX-XX."""
import re

from django.core.exceptions import ValidationError

BY_PHONE_PLACEHOLDER = '+375 (XX) XXX-XX-XX'
BY_PHONE_EXAMPLE = '+375 (29) 123-45-67'
BY_PHONE_HELP = (
    'Только белорусский номер: 9 цифр после кода страны 375, формат отображения '
    + BY_PHONE_PLACEHOLDER
)


def belarus_phone_digits(value) -> str:
    if value is None:
        return ''
    return re.sub(r'\D', '', str(value).strip())


def format_belarus_phone(digits_12: str) -> str:
    """Форматирует 12 цифр, начинающихся с 375."""
    d = digits_12
    return f'+375 ({d[3:5]}) {d[5:8]}-{d[8:10]}-{d[10:12]}'


def normalize_belarus_phone(value) -> str:
    """
    Пустая строка — ок.
    Иначе ровно 12 цифр 375 + 9, возвращает канонический вид с пробелами и скобками.
    """
    if value is None or not str(value).strip():
        return ''
    d = belarus_phone_digits(value)
    if len(d) == 9:
        d = '375' + d
    if len(d) != 12 or not d.startswith('375'):
        raise ValidationError(BY_PHONE_HELP, code='invalid_by_phone')
    return format_belarus_phone(d)


def validate_belarus_phone_optional(value):
    """Для полей модели: пусто или валидный номер РБ."""
    if value is None or not str(value).strip():
        return
    normalize_belarus_phone(value)


def belarus_phone_tel_href(value) -> str:
    """Для href=\"tel:...\" — только цифры с +."""
    d = belarus_phone_digits(value or '')
    if len(d) == 9:
        d = '375' + d
    if len(d) == 12 and d.startswith('375'):
        return '+' + d
    return ''
