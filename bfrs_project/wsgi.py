"""
WSGI config for bfrs_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.10/howto/deployment/wsgi/
"""
import confy
confy.read_environment_file('.env')

import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bfrs_project.settings")
application = get_wsgi_application()

#from __future__ import absolute_import, unicode_literals, print_function, division
#
#import os
#import confy
#from django.core.wsgi import get_wsgi_application
#from dj_static import Cling, MediaCling
#
#confy.read_environment_file('.env')
#os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bfrs_project.settings")
#application = Cling(MediaCling(get_wsgi_application()))



