from django import template

register = template.Library()

@register.filter(name='get_item_condition_field')
def get_item_condition_field(form, item_id):
    return form[f'item_{item_id}_condition']

@register.filter(name='get_item_notes_field')
def get_item_notes_field(form, item_id):
    return form[f'item_{item_id}_notes']

@register.filter
def get_form_field(form, field_name):
    """Get form field by name"""
    return form[field_name]