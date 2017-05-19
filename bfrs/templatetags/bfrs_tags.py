from django import template
from bfrs.models import Bushfire, current_finyear
from django.contrib.gis.geos import Point, GEOSGeometry
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
    #import ipdb; ipdb.set_trace()
    return obj.is_init_authorised

@register.filter
def date_fmt(dt):
    """
    Usage::

        {% if object.authorised_date|date_fmt %}
        ...
        {% endif %}
    """
    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None

@register.filter
def deg_min_sec(value):
    """
    Usage::

        {{ form.origin_point.value|deg_min_sec }}
    """
    #GEOSGeometry('POINT(-95.3385 29.7245)')

    try:
        point = GEOSGeometry(value)
        x = round(point.get_x(), 2)
        y = round(point.get_y(), 2)
        c=LatLon.LatLon(LatLon.Latitude(x), LatLon.Longitude(y))

        return '(Deg/Min/Sec) {}'.format(str(c.to_string('D% %M% %S% %H')) )
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
        return '(Lat/Lon) {}/{}'.format(x, y)
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

@register.simple_tag(takes_context=True)
def _can_readonly(context):
    """
    Usage::

        {% can_readonly as readonly %}
        {% if readonly %}
        ...
        {% endif %}
    """
    request = context['request']
    import ipdb; ipdb.set_trace()
    return request.user.groups.filter(name='ReadOnly').exists()

@register.filter
def split_capitalize(string):
    """
    Usage::

        {{ msg|split_capitalize}}
    """
    return ' '.join([i.capitalize() for i in string.split('_')])

#@register.filter
#def yesno(boolean):
#    """
#    Usage::
#
#        {{ bool|yesno}}
#    """
#    return 'Yes' if boolean else 'No'
#

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

#@register.filter
#def bool(value):
#    """
#    Usage::
#
#        {{ value|bool}}
#    """
#    if
#    return True if value else False


@register.filter
def is_none(string):
    """
    Usage::

        {{ string|is_none}}
    """
    return '---' if string is None else string

@register.filter(is_safe=False)
def filter_tenures_burnt(qs, arg=None):
    """
    Usage::

        {{ qs|filter_tenures_burnt }}
    """
    #import ipdb; ipdb.set_trace()
    #return qs.exclude(tenure__name__in=['Unallocated Crown Land', 'Other'])
    return qs.exclude(tenure__name__in=arg.split(','))

@register.filter(is_safe=False)
def tenures_burnt(qs, arg=None):
    """
    Usage::

        {{ qs|filter_tenures_burnt }}
    """
    #import ipdb; ipdb.set_trace()
    qs = qs.filter(tenure__name=arg)
    return round(qs[0].area, 0) if qs else 0


