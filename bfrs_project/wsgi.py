"""
WSGI config for bfrs_project project.
It exposes the WSGI callable as a module-level variable named ``application``.
"""
import dotenv
from django.core.wsgi import get_wsgi_application
import os

# These lines are required for interoperability between local and container environments.
dot_env = os.path.join(str(os.getcwd()), '.env')
if os.path.exists(dot_env):
    dotenv.read_dotenv(dot_env)  # This line must precede dj_static imports.


from dj_static import Cling

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bfrs_project.settings')
application = Cling(get_wsgi_application())
