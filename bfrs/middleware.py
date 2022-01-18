from django import http, VERSION
from django.conf import settings
from django.contrib.auth import login, logout, get_user_model
from django.db.models import signals
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import curry

class SSOLoginMiddleware(MiddlewareMixin):

    def process_request(self, request):
        User = get_user_model()
        if (request.path.startswith('/logout') or request.path.startswith('/ledger/logout')) \
                    and 'HTTP_X_LOGOUT_URL' in request.META and request.META['HTTP_X_LOGOUT_URL']:
            logout(request)
            return http.HttpResponseRedirect(request.META['HTTP_X_LOGOUT_URL'])

        if VERSION < (2, 0):
            user_auth = request.user.is_authenticated()
        else:
            user_auth = request.user.is_authenticated

        if not user_auth and 'HTTP_REMOTE_USER' in request.META and request.META['HTTP_REMOTE_USER']:
            attributemap = {
                'username': 'HTTP_REMOTE_USER',
                'last_name': 'HTTP_X_LAST_NAME',
                'first_name': 'HTTP_X_FIRST_NAME',
                'email': 'HTTP_X_EMAIL',
            }

            for key, value in attributemap.items():
                if value in request.META:
                    attributemap[key] = request.META[value]

            attributemap['username'] = attributemap['username'].replace("@",".")
            if hasattr(settings, 'ALLOWED_EMAIL_SUFFIXES') and settings.ALLOWED_EMAIL_SUFFIXES:
                allowed = settings.ALLOWED_EMAIL_SUFFIXES
                if isinstance(settings.ALLOWED_EMAIL_SUFFIXES, basestring):
                    allowed = [settings.ALLOWED_EMAIL_SUFFIXES]
                if not any([attributemap['email'].lower().endswith(x) for x in allowed]):
                    return http.HttpResponseForbidden()

            if attributemap['email'] and User.objects.filter(email__iexact=attributemap['email']).exists():
                user = User.objects.filter(email__iexact=attributemap['email'])[0]
            elif (User.__name__ != 'EmailUser') and User.objects.filter(username__iexact=attributemap['username']).exists():
                user = User.objects.filter(username__iexact=attributemap['username'])[0]
            else:
                user = User()
            user.__dict__.update(attributemap)
            user.save()
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
