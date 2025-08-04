from django import template

register = template.Library()

@register.filter
def sum_attr(queryset, attr):
    return sum(getattr(item, attr, 0) for item in queryset)

@register.filter
def get_item(dictionary, key):
    if dictionary and key:
        return dictionary.get(key, '')
    return ''