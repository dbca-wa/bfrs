from django import template
import os

register = template.Library()


@register.simple_tag(takes_context=True)
def base_dir(context):
    """ Hack for getting the base_dir for uWSGI config. settings.BASE_DIR returns '' in latex templates when using uWSGI """
    return '{}'.format(os.getcwd())
