from django.conf.urls import include, url
from django.views.generic import TemplateView
from django.contrib import admin
import debug_toolbar

urlpatterns = [
#    url(r'^login/$', 'django.contrib.auth.views.login', name='login',
#        kwargs={'template_name': 'login.html'}),
#    url(r'^logout/$', 'django.contrib.auth.views.logout', name='logout',
#        kwargs={'template_name': 'logged_out.html'}),

    url(r'^bfrs/', include('bfrs.urls', namespace='bushfire')),
    url(r'^admin/', include(admin.site.urls)),
    url(r'^chaining/', include('smart_selects.urls')),

    url(r'^__debug__/', include(debug_toolbar.urls)),
]

