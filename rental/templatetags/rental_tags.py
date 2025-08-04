from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def multiply(value, arg):
    """
    Multiplies the value by the argument.
    Usage: {{ value|multiply:arg }}
    """
    try:
        return Decimal(value) * Decimal(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def divide(value, arg):
    """
    Divides the value by the argument.
    Usage: {{ value|divide:arg }}
    """
    try:
        if Decimal(arg) == 0:
            return ''
        return Decimal(value) / Decimal(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def subtract(value, arg):
    """
    Subtracts the argument from the value.
    Usage: {{ value|subtract:arg }}
    """
    try:
        return Decimal(value) - Decimal(arg)
    except (ValueError, TypeError):
        return ''