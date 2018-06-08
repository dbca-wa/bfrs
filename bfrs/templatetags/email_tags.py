import datetime
import LatLon
from dateutil import tz

from django.contrib.auth.models import User
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

from bfrs.models import Bushfire
from bfrs import utils

register = template.Library()


@register.inclusion_tag('bfrs/email/bushfire_details.html',takes_context=True)
def bushfire_details(context,bushfire,*fields):
    context["bushfire_fields"]=fields
    context["cur_bushfire"] = bushfire

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


@register.simple_tag()
def field_value(field_name, bushfire=None, request=None, url_type="auto",is_upper=None):
    """
    Return the value of model field to dispay in the email
    """
    if bushfire:
        try:
            if field_name == "origin_point_geo":
                return bushfire.origin_geo
            elif field_name == "region":
                if is_upper == True:
                    return bushfire.region.name.upper()
                else:
                    return bushfire.region.name
            elif field_name == "district":
                if is_upper == True:
                    return bushfire.district.name.upper()
                else:
                    return bushfire.district.name
            elif field_name == "fire_number":
                if request:
                    return mark_safe("<a href='{}'>{}</a>".format(utils.get_bushfire_url(request,bushfire,url_type),bushfire.fire_number))
                else:
                    return bushfire.fire_number
            elif field_name == "url_link":
                if request:
                    return mark_safe("<a href='{0}'>{0}</a>".format(utils.get_bushfire_url(request,bushfire,url_type)))
                else:
                    return ""
            elif field_name == "url":
                if request:
                    return utils.get_bushfire_url(request,bushfire,url_type)
                else:
                    return ""
            elif field_name == "report_status":
                return bushfire.report_status_name
            elif field_name == "latitude_degree":
                return LatLon.Latitude(bushfire.origin_point.get_y()).degree
            elif field_name == "latitude_minute":
                return LatLon.Latitude(bushfire.origin_point.get_y()).minute
            elif field_name == "latitude_second":
                return LatLon.Latitude(bushfire.origin_point.get_y()).second
            elif field_name == "longitude_degree":
                return LatLon.Longitude(bushfire.origin_point.get_x()).degree
            elif field_name == "longitude_minute":
                return LatLon.Longitude(bushfire.origin_point.get_x()).minute
            elif field_name == "longitude_second":
                return LatLon.Longitude(bushfire.origin_point.get_x()).second
                

            value = getattr(bushfire, FIELD_MAPPING.get(field_name) or field_name)
            if field_name == "dfes_incident_no":
                return value or "Not available"
            elif value is None:
                return "-"
            elif type(value) == type(True):
                return "Yes" if value else "No"
            elif field_name == "dispatch_pw":
                return "Yes" if value == 1 else "No"
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

