from django import template
from bfrs.models import Bushfire

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
def fin_year(year):
    """
    Usage::

        {{ object.year|fin_year }}
    """
    return str(year) + '/' + str(year+1) if year else None


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
#@register.filter
#def bool(boolean):
#    """
#    Usage::
#
#        {{ bool|yesno}}
#    """
#    return True if boolean else False


@register.filter
def is_none(string):
    """
    Usage::

        {{ string|is_none}}
    """
    return '---' if string is None else string


