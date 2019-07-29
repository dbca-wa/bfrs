from django.conf.urls import include, url
from django.views.generic import TemplateView
from django.contrib import admin
import debug_toolbar
from bfrs import views
from bfrs.api import v1_api

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.conf import settings

from .signals import webserver_ready

def sss_selection_view(request):
    return HttpResponseRedirect(settings.SSS_URL)


def home_view_selection_view(request):
    if request.user.is_authenticated():
        return redirect('main')
    else:
        return redirect('login')


def admin_view_selection_view(request):
    if request.user.is_superuser:
        return admin.site.index(request)
    elif request.user.is_authenticated():
        return redirect('main')
    else:
        return redirect('login')


urlpatterns = [
#    url(r'^login/$', 'django.contrib.auth.views.login', name='login',
#        kwargs={'template_name': 'login.html'}),
#    url(r'^logout/$', 'django.contrib.auth.views.logout', name='logout',
#        kwargs={'template_name': 'logged_out.html'}),

    # Authentication URLs
    url(r'^logout/$', auth_views.logout, {'next_page': '/login/'}, name='logout'),
    #url(r'^login/$', auth_views.login),
    url('^', include('django.contrib.auth.urls')),

    url(r'^$', home_view_selection_view, name='home'),
    url(r'^main/$', login_required(views.BushfireView.as_view()), name='main'),
    url(r'^admin/$', admin_view_selection_view),
    #url(r'^$', views.BushfireView.as_view(), name='home'),
    url(r'^bfrs/', include('bfrs.urls', namespace='bushfire')),
    url(r'^admin/', include(admin.site.urls)),
    url(r'^about/', TemplateView.as_view(template_name='about.html'), name='about'),
    #url(r'profile/(?P<username>[a-zA-Z0-9]+)$', views.profile),
    #url(r'profile/$', views.profile),
    url(r'^api/', include(v1_api.urls)),
    url(r'profile/$', views.ProfileView.as_view(), name='profile'),
    url(r'^sss/$', sss_selection_view, name="sss_home"),

    # api
    #url(r'^api/', include(v1_api.urls, namespace='api')),

    url(r'^chaining/', include('smart_selects.urls')),
    url(r'^__debug__/', include(debug_toolbar.urls)),
]


webserver_ready.send(sender="urls")
