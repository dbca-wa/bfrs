# from django.conf.urls import url
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.contrib import admin
from bfrs import views
from bfrs.api import v1_api

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.conf import settings

from .views import ChainedModelChoicesView

from .signals import webserver_ready

def sss_selection_view(request):
    return HttpResponseRedirect(settings.SSS_URL)


def home_view_selection_view(request):
    # if request.user.is_authenticated():
    if request.user.is_authenticated:
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
    # Authentication URLs
    # url(r'^', include('django.contrib.auth.urls')),
    path('', include('django.contrib.auth.urls')),
    path('logout/', auth_views.LogoutView.as_view(next_page='/login/'), name='logout'),
    #url(r'^logout/$', auth_views.logout, {'next_page': '/login/'}, name='logout'),
    # url(r'^main/$', login_required(views.BushfireView.as_view()), name='main'),
    path('main/', login_required(views.BushfireView.as_view()), name='main'),
    # url(r'^admin/$', admin_view_selection_view),
    path('admin/', admin_view_selection_view),
    #url(r'^bfrs/', include('bfrs.urls', namespace='bushfire')),
    # url(r'^bfrs/', include(('bfrs.urls', 'bfrs'), namespace='bushfire')),
    path('bfrs/', include(('bfrs.urls', 'bfrs'), namespace='bushfire')),
    #url(r'^admin/', include(admin.site.urls)),
    path('admin/', admin.site.urls),
    # url(r'^about/', TemplateView.as_view(template_name='about.html'), name='about'),
    # url(r'^api/', include(v1_api.urls)),
    # url(r'^profile/$', views.ProfileView.as_view(), name='profile'),
    # url(r'^sss/$', sss_selection_view, name="sss_home"),
    # url(r'^chaining/', include('smart_selects.urls')),
    # url(r'^options/js/(?P<chained_model_app>[a-zA-Z0-9\_\-]+)/(?P<chained_model_name>[a-zA-Z0-9\_\-]+)/(?P<model_app>[a-zA-Z0-9\_\-]+)/(?P<model_name>[a-zA-Z0-9\_\-]+)', ChainedModelChoicesView.as_view(),name="chained_model_choices"),
    # url(r'^$', home_view_selection_view, name='home'),
    # path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('api/', include(v1_api.urls)),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('sss/', sss_selection_view, name="sss_home"),
    path('chaining/', include('smart_selects.urls')),
    re_path(r'^options/js/(?P<chained_model_app>[a-zA-Z0-9\_\-]+)/(?P<chained_model_name>[a-zA-Z0-9\_\-]+)/(?P<model_app>[a-zA-Z0-9\_\-]+)/(?P<model_name>[a-zA-Z0-9\_\-]+)', ChainedModelChoicesView.as_view(), name="chained_model_choices"),
    path('', home_view_selection_view, name='home'),
]

webserver_ready.send(sender="urls")
