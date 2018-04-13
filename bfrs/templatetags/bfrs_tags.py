from django import template
from bfrs.models import Bushfire, Region, District, current_finyear
from django.contrib.gis.geos import Point, GEOSGeometry
from django.conf import settings
import LatLon

register = template.Library()

@register.assignment_tag(takes_context=True)
def is_init_authorised(context, bushfire_id):
    """
    Usage::

        {% if is_init_authorised %}
        ...
        {% endif %}

        or

        {% for bushfire in object_list %}
            {% is_init_authorised bushfire.id as init_authorised %}
            <tr>
                <td>{{ bushfire.id }}</td>
                <td><a href="{% url 'bushfire:bushfire_initial' bushfire.id %}">{{ bushfire.name }}</td>

                {% if init_authorised %}
                    <td><a href="{% url 'bushfire:bushfire_final' bushfire.id %}">{{ bushfire.name }}</td>
                {% endif %}
            </tr>
        {% endfor %}
    """

    obj = Bushfire.objects.get(id=bushfire_id)
    return obj.is_init_authorised

#@register.filter
#def date_fmt(dt):
#    """
#    NOTE: Does not prreserve the timezone - gives UTC
#    Usage::
#
#        {% if object.authorised_date|date_fmt %}
#        ...
#        {% endif %}
#    """
#    return dt.strftime('%Y-%m-%d %H:%M') if dt else None

@register.filter
def deg_min_sec(value):
    """
    Usage::

        {{ form.origin_point.value|deg_min_sec }}
    """
    #GEOSGeometry('POINT(-95.3385 29.7245)')

    try:
        point = GEOSGeometry(value)
        x = point.get_x()
        y = point.get_y()
        c=LatLon.LatLon(LatLon.Longitude(x), LatLon.Latitude(y))
        latlon = c.to_string('d% %m% %S% %H')
        lon = latlon[0].split(' ')
        lat = latlon[1].split(' ')

        # need to format float number (seconds) to 1 dp
        lon[2] = str(round(eval(lon[2]), 1))
        lat[2] = str(round(eval(lat[2]), 1))

        # Degrees Minutes Seconds Hemisphere
        lat_str = lat[0] + u'\N{DEGREE SIGN} ' + lat[1].zfill(2) + '\' ' + lat[2].zfill(4) + '\" ' + lat[3]
        lon_str = lon[0] + u'\N{DEGREE SIGN} ' + lon[1].zfill(2) + '\' ' + lon[2].zfill(4) + '\" ' + lon[3]

        return 'Lat/Lon ' + lat_str + ', ' + lon_str
    except:
        return None

@register.filter
def latlon(value):
    """
    Usage::

        {{ form.origin_point.value|latlon }}
    """
    #GEOSGeometry('POINT(-95.3385 29.7245)')

    try:
        point = GEOSGeometry(value)
        x = round(point.get_x(), 2)
        y = round(point.get_y(), 2)
        return '(Lon/Lat) {}/{}'.format(x, y)
    except:
        return None

@register.filter
def fin_year(year):
    """
    Usage::

        {{ object.year|fin_year }}
    """
    if not year:
        year = current_finyear()
    return str(year) + '/' + str(int(year)+1)


@register.filter
def can_readonly(user):
    """
    Usage::

        {% if request.user|can_readonly %}
        ...
        {% endif %}
    """
    return user.groups.filter(name='ReadOnly').exists()

@register.simple_tag(takes_context=True)
def get_count(context):
    """
    Usage::
        {% get_count %}
    """
    request = context['request']
    return request.user.groups.filter(name='ReadOnly').count()

@register.filter
def split_capitalize(string):
    """
    Usage::

        {{ msg|split_capitalize}}
    """
    if string=='Area':
        string = 'Must enter final fire area, if area < {}ha'.format(settings.AREA_THRESHOLD)
    return ' '.join([i.capitalize() for i in string.split('_')])

@register.filter(is_safe=False)
def yesno(value, arg=None):
    """
    Overriding the built-in 'yesno' tag

    Given a string mapping values for true, false and (optionally) None,
    returns one of those strings according to the value:

    ==========  ======================  ==================================
    Value       Argument                Outputs
    ==========  ======================  ==================================
    ``True``    ``"yeah,no,maybe"``     ``yeah``
    ``False``   ``"yeah,no,maybe"``     ``no``
    ``None``    ``"yeah,no,maybe"``     ``maybe``
    ``None``    ``"yeah,no"``           ``"no"`` (converts None to False
                                        if no mapping for None is given.
    ==========  ======================  ==================================
    """
    if arg is None:
        arg = ugettext('yes,no,maybe')
    bits = arg.split(',')
    if len(bits) < 2:
        return value  # Invalid arg.
    try:
        yes, no, maybe = bits
    except ValueError:
        # Unpack list of wrong size (no "maybe" value provided).
        yes, no, maybe = bits[0], bits[1], bits[1]

    if value == 'True':
        return yes
    elif value == 'False':
        return no
    elif value == 'None' or value is None:
        return maybe
    elif value:
        return yes
    else:
        return no

@register.filter
def assistance(value):
    """
    Usage::

        {{ value|assistance}}
    """
    try:
        if isinstance(value, (str, unicode)):
            value = eval(value)

        if Bushfire.ASSISTANCE_YES==value:
            return Bushfire.ASSISTANCE_CHOICES[Bushfire.ASSISTANCE_YES-1][1]
        if Bushfire.ASSISTANCE_NO==value:
            return Bushfire.ASSISTANCE_CHOICES[Bushfire.ASSISTANCE_NO-1][1]
        return Bushfire.ASSISTANCE_CHOICES[Bushfire.ASSISTANCE_UNKNOWN-1][1]
    except:
        return None

@register.filter
def ignition(value):
    """
    Usage::

        {{ value|ignition}}
    """
    try:
        if isinstance(value, (str, unicode)):
            value = eval(value)

        if Bushfire.IGNITION_POINT_PRIVATE==value:
            return Bushfire.IGNITION_POINT_CHOICES[Bushfire.IGNITION_POINT_PRIVATE-1][1]
        return Bushfire.IGNITION_POINT_CHOICES[Bushfire.IGNITION_POINT_CROWN-1][1]
    except:
        return None

@register.filter
def cause_state(value):
    """
    Usage::

        {{ value|cause_state}}
    """
    try:
        if isinstance(value, (str, unicode)):
            value = eval(value)

        if Bushfire.CAUSE_STATE_POSSIBLE==value:
            return Bushfire.CAUSE_STATE_CHOICES[Bushfire.CAUSE_STATE_POSSIBLE-1][1]
        return Bushfire.CAUSE_STATE_CHOICES[Bushfire.CAUSE_STATE_KNOWN-1][1]
    except:
        return None

@register.filter
def is_none(string):
    """
    Usage::

        {{ string|is_none}}
    """
    return '---' if string is None else string

@register.filter
def to_null(string):
    """
    Usage::

        {{ string|to_null}}
    """
    return 'null' if string is None else string


@register.filter(is_safe=False)
def filter_tenures_burnt(qs, arg=None):
    """
    Usage::

        {{ qs|filter_tenures_burnt:"string" }}
    """
    #return qs.exclude(tenure__name__in=['Unallocated Crown Land', 'Other'])
    return qs.exclude(tenure__name__in=arg.split(',')) if qs else None

@register.filter(is_safe=False)
def tenures_burnt(qs, arg=None):
    """
    Usage::

        {{ qs|filter_tenures_burnt:"string" }}
    """
    qs = qs.filter(tenure__name=arg) if qs else None
    return round(qs[0].area, 2) if qs else 0

@register.filter(is_safe=False)
def qs_order_by(qs, arg=None):
    """
    Usage:
        {{ qs|qs_order_by:"id" }}
    """
    #import ipdb; ipdb.set_trace()
    return qs.order_by('id') if qs else []

@register.filter()
def to_int(value):
    return int(value)

@register.filter()
def to_float(value):
    #import ipdb; ipdb.set_trace()
    return round(float(value), 1) if value else ''

@register.filter()
def check_errors(error_list):
    return any(error_list) if error_list else False

def get_order_by(filters):
    sort_by = filters.get("order_by")
    if not sort_by:
        return (None,None)

    if sort_by[0] == "+":
        direction = "+"
        sort_column = sort_by[1:]
    elif sort_by[0] == "-":
        direction = "-"
        sort_column = sort_by[1:]
    else:
        direction = "+"
        sort_column = sort_by
    return (sort_column,direction)

@register.filter()
def sort_class(column,filters):
    sort_column,direction = get_order_by(filters)

    if sort_column is None:
        return ""
    elif column == sort_column:
        if direction == "+":
            return "headerSortDown"
        else:
            return "headerSortUp"
    else:
        return ""

@register.filter()
def toggle_sort(column,filters):
    sort_column,direction = get_order_by(filters)

    if sort_column is None:
        return "order_by={}".format(column)
    elif column == sort_column:
        if direction == "+":
            return "order_by=-{}".format(column)
        else:
            return "order_by={}".format(column)
    else:
        return "order_by={}".format(column)

@register.simple_tag(takes_context=True)
def _clear_session(context):
    """
    Usage::
        {% clear_session %}
    """
    request = context['request']
    if request.session.has_key('refreshGokart'): request.session.pop('refreshGokart')
    if request.session.has_key('region'): request.session.pop('region')
    if request.session.has_key('district'): request.session.pop('district')
    if request.session.has_key('id'): request.session.pop('id')
    if request.session.has_key('action'): request.session.pop('action')
    request.session.modified = True
    #return request

@register.simple_tag(takes_context=True)
def clear_session(context):
    """
    Usage::
        {% clear_session %}
    """
    request = context['request']
    if request.session.has_key('refreshGokart'):
        request.session.pop('refreshGokart')
        #request.session.pop('region')
        #request.session.pop('district')
        #request.session.pop('id')
        #request.session.pop('action')
        request.session.modified = True
        return 'true'
    return 'false'

@register.filter(is_safe=False)
def enum_name(id, arg=None):
    """
    Usage::

        {{ value|enum_name:"string" }}
    """
    if id and arg.lower() == 'region':
        return Region.objects.get(id=id).name
    elif id and arg.lower() == 'district':
        district = District.objects.get(id=id)
        return district.region.name + ' - ' + district.name
    return 'arg={} or id={} Unknown'.format(arg, id)

@register.simple_tag
def settings_value(name):
    """
    Usage:
        {% settings_value "LANGUAGE_CODE" %}
    """
    return getattr(settings, name, "")

@register.simple_tag
def page_background():
    """
    Usage:
        Set a image as html page's background to indicate the runtime environment (dev or uat)
    """
    if settings.ENV_TYPE == "PROD":
        return ""
    elif settings.ENV_TYPE == "LOCAL":
        return "background-image:url('/static/img/local.png')"
    elif settings.ENV_TYPE == "DEV":
        return "background-image:url('/static/img/dev.png')"
    elif settings.ENV_TYPE == "UAT":
        return "background-image:url('/static/img/uat.png')"
    else:
        return "background-image:url('/static/img/dev.png')"

@register.filter
def test(name):
    import ipdb; ipdb.set_trace()
    pass
