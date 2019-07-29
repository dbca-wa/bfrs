from dbca_utils.utils import env
import dj_database_url
import os
import sys


# Project paths
# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.join(BASE_DIR, 'bfrs_project')
# Add PROJECT_DIR to the system path.
sys.path.insert(0, PROJECT_DIR)

# Application definition
DEBUG = env('DEBUG', False)
SECRET_KEY = env('SECRET_KEY', 'PlaceholderSecretKey')
CSRF_COOKIE_SECURE = env('CSRF_COOKIE_SECURE', False)
SESSION_COOKIE_SECURE = env('SESSION_COOKIE_SECURE', False)
if not DEBUG:
    ALLOWED_HOSTS = env('ALLOWED_DOMAINS', ['localhost'])
else:
    ALLOWED_HOSTS = ['*']
INTERNAL_IPS = ['127.0.0.1', '::1']
ROOT_URLCONF = 'bfrs_project.urls'
WSGI_APPLICATION = 'bfrs_project.wsgi.application'
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'reversion',
    'reversion_compare',
    'tastypie',
    'smart_selects',
    'django_extensions',
    'crispy_forms',
    'django_filters',
    'bfrs',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'reversion.middleware.RevisionMiddleware',
    'dbca_utils.middleware.SSOLoginMiddleware',
]
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'debug': DEBUG,
            'context_processors': [
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.template.context_processors.request',
                'django.template.context_processors.csrf',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]
LATEX_GRAPHIC_FOLDER = os.path.join(BASE_DIR, "templates", "latex", "images")
P1CAD_ENDPOINT = env('P1CAD_ENDPOINT', None)
P1CAD_USER = env('P1CAD_USER', None)
P1CAD_PASSWORD = env('P1CAD_PASSWORD', None)
P1CAD_SSL_VERIFY = True if env('P1CAD_SSL_VERIFY', True) else False
P1CAD_NOTIFY_EMAIL = env('P1CAD_NOTIFY_EMAIL') or None
KMI_URL = env('KMI_URL', 'https://kmi.dbca.wa.gov.au/geoserver')
AREA_THRESHOLD = env('AREA_THRESHOLD', 2)
SSS_URL = env('SSS_URL', 'https://sss.dpaw.wa.gov.au')
SSS_CERTIFICATE_VERIFY = env('SSS_CERTIFICATE_VERIFY', True)
PBS_URL = env('PBS_URL', 'https://pbs.dpaw.wa.gov.au/')
URL_SSO = env('URL_SSO', 'https://oim.dpaw.wa.gov.au/api/users/')
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 20  # 20 MB
CRISPY_TEMPLATE_PACK = 'bootstrap3'
HISTORICAL_CAUSE_CSV_FILE = env('HISTORICAL_CAUSE_CSV_FILE', '')
ADD_REVERSION_ADMIN = True
LOGIN_URL = '/login/'
LOGOUT_URL = '/logout/'
LOGIN_REDIRECT_URL = '/'
SERIALIZATION_MODULES = {
    "geojson": "django.contrib.gis.serializers.geojson",
}
ENV_TYPE = env('ENV_TYPE', 'DEV')
CC_TO_LOGIN_USER = env('CC_TO_LOGIN_USER', False)

# Authentication and group settings.
USER_SSO = env('USER_SSO', 'sso_user@dbca.wa.gov.au')
PASS_SSO = env('PASS_SSO', 'password')
FSSDRS_USERS = env('FSSDRS_USERS', [])
FSSDRS_GROUP = env('FSSDRS_GROUP', 'Fire Information Management')
FINAL_AUTHORISE_GROUP_USERS = env('FINAL_AUTHORISE_GROUP_USERS', [])
FINAL_AUTHORISE_GROUP = env('FINAL_AUTHORISE_GROUP', 'Fire Final Authorise Group')

# Email settings
EMAIL_HOST = env('EMAIL_HOST', 'email.host')
EMAIL_PORT = env('EMAIL_PORT', 25)
FROM_EMAIL = env('FROM_EMAIL', 'from_email')
PICA_EMAIL = env('PICA_EMAIL', None)
PVS_EMAIL = env('PVS_EMAIL', None)
FPC_EMAIL = env('FPC_EMAIL', None)
POLICE_EMAIL = env('POLICE_EMAIL', None)
DFES_EMAIL = env('DFES_EMAIL', None)
FSSDRS_EMAIL = env('FSSDRS_EMAIL', None)
EMAIL_TO_SMS_FROMADDRESS = env('EMAIL_TO_SMS_FROMADDRESS', None)
SMS_POSTFIX = env('SMS_POSTFIX', 'sms_postfix')
MEDIA_ALERT_SMS_TOADDRESS_MAP = env('MEDIA_ALERT_SMS_TOADDRESS_MAP', None)
ALLOW_EMAIL_NOTIFICATION = env('ALLOW_EMAIL_NOTIFICATION', False)
EMAIL_EXCLUSIONS = env('EMAIL_EXCLUSIONS', [])
CC_EMAIL = env('CC_EMAIL', None)
BCC_EMAIL = env('BCC_EMAIL', None)
SUPPORT_EMAIL = env('SUPPORT_EMAIL', None)
MERGE_BUSHFIRE_EMAIL = env('MERGE_BUSHFIRE_EMAIL', None)
FIRE_BOMBING_REQUEST_EMAIL = env("FIRE_BOMBING_REQUEST_EMAIL", None)
FIRE_BOMBING_REQUEST_CC_EMAIL = env("FIRE_BOMBING_REQUEST_CC_EMAIL", None)
INTERNAL_EMAIL = env('INTERNAL_EMAIL', ['dbca.wa.gov.au','dpaw.wa.gov.au'])
HARVEST_EMAIL_HOST = env('HARVEST_EMAIL_HOST', None)
HARVEST_EMAIL_USER = env('HARVEST_EMAIL_USER', None)
HARVEST_EMAIL_PASSWORD = env('HARVEST_EMAIL_PASSWORD', None)
HARVEST_EMAIL_FOLDER = env('HARVEST_EMAIL_FOLDER', 'INBOX')

# Outstanding Fires Report
GOLDFIELDS_EMAIL = env('GOLDFIELDS_EMAIL') or None
KIMBERLEY_EMAIL = env('KIMBERLEY_EMAIL') or None
MIDWEST_EMAIL = env('MIDWEST_EMAIL') or None
PILBARA_EMAIL = env('PILBARA_EMAIL') or None
SOUTH_COAST_EMAIL = env('SOUTH_COAST_EMAIL') or None
SOUTH_WEST_EMAIL = env('SOUTH_WEST_EMAIL') or None
SWAN_EMAIL = env('SWAN_EMAIL') or None
WARREN_EMAIL = env('WARREN_EMAIL') or None
WHEATBELT_EMAIL = env('WHEATBELT_EMAIL') or None
OUTSTANDING_FIRES_EMAIL = [
    {"Goldfields": GOLDFIELDS_EMAIL},
    {"Kimberley": KIMBERLEY_EMAIL},
    {"Midwest": MIDWEST_EMAIL},
    {"Pilbara": PILBARA_EMAIL},
    {"South Coast": SOUTH_COAST_EMAIL},
    {"South West": SOUTH_WEST_EMAIL},
    {"Swan": SWAN_EMAIL},
    {"Warren": WARREN_EMAIL},
    {"Wheatbelt": WHEATBELT_EMAIL},
]

#Others
AUTHORISE_MESSAGE = env("AUTHORISE_MESSAGE","Once the fire is closed DFES COMCEN need to be informed IMMEDIATELY by phone and email on XXXXXX and xxxx@dfes.wa.gov.au")

# Database configuration
DATABASES = {
    # Defined in the DATABASE_URL env variable.
    'default': dj_database_url.config(),
}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Australia/Perth'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files and media uploads settings.
# Ensure that the media directory exists:
if not os.path.exists(os.path.join(BASE_DIR, 'media')):
    os.mkdir(os.path.join(BASE_DIR, 'media'))
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'


# Logging settings - log to stdout/stderr
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {'format': '%(asctime)s %(name)-12s %(message)s'},
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'console'
        },
        'bfrs': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'console'
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'propagate': True,
        },
        'bfrs': {
            'handlers': ['console'],
            'level': 'INFO'
        },
    }
}
