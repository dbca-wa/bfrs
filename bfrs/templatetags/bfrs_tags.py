from django import template
from bfrs.models import Bushfire

register = template.Library()

@register.assignment_tag(takes_context=True)
def has_init_authorised(context, bushfire_id):
    obj = Bushfire.objects.get(id=bushfire_id)
    return obj.has_init_authorised







