from django import template

from ..belarus_phone import belarus_phone_tel_href

register = template.Library()


@register.filter(name='phone_tel_href')
def phone_tel_href(value):
    """Ссылка tel:+375… без пробелов."""
    return belarus_phone_tel_href(value)
