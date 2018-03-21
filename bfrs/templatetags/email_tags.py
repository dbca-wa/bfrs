import datetime
from dateutil import tz

from django.contrib.auth.models import User
from django import template
from bfrs.models import Bushfire
from django.conf import settings

register = template.Library()


@register.inclusion_tag('bfrs/email/bushfire_details.html',takes_context=True)
def bushfire_details(context,*args):
    context["bushfire_fields"]=args
    return context

@register.simple_tag(takes_context=True)
def email_debug(context):
    import ipdb;ipdb.set_trace()

@register.simple_tag
def get_jsonproperty(bushfire,property_name,default_value=None):
    """
    return property value
    """
    if bushfire:
        try:
            return bushfire.properties.get(name=property_name).json_value
        except ObjectDoesNotExist:
            return default_value
    else:
        return default_value


FIELD_MAPPING = {
    "origin_point_geo":"origin_point"
}
@register.filter(is_safe=True)
def field_label(field_name, bushfire=None):
    """
    Return the label of model field
    """
    field_name = FIELD_MAPPING.get(field_name) or field_name
    if bushfire:
        try:
            return bushfire._meta.get_field(field_name).verbose_name
        except:
            return value
    else:
        return value


@register.filter(is_safe=False)
def field_value(field_name, bushfire=None):
    """
    Return the value of model field to dispay in the email
    """
    if bushfire:
        try:
            value = getattr(bushfire, FIELD_MAPPING.get(field_name) or field_name)
            if field_name == "dfes_incident_no":
                return value or "Not available"
            elif value is None:
                return "-"
            elif type(value) == type(True):
                return "Yes" if value else "No"
            elif field_name == "dispatch_pw":
                return "Yes" if value == 1 else "No"
            elif field_name == "origin_point_geo":
                return bushfire.origin_geo
            elif field_name == "region":
                return bushfire.region.name
            elif field_name == "district":
                return bushfire.district.name
            elif isinstance(value,datetime.datetime):
                return value.astimezone(tz.gettz(settings.TIME_ZONE)).strftime('%Y-%m-%d %H:%M')
            else:
                value = str(value).strip()
                return value or "-"
        except:
            return "-"
    else:
        return "-"

@register.filter(is_safe=True)
def field_style(field_name, bushfire=None):
    """
    Return the style to display the value of model field in the email
    """
    if bushfire:
        try:
            value = getattr(bushfire, field_name)
            if field_name == "dfes_incident_no":
                return "" if value else "color:red;"
            else:
                return ""
        except:
            return ""
    else:
        return ""

