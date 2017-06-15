from django.conf.urls import include, url
from bfrs.models import Bushfire
from bfrs import views

urlpatterns = [
    url(r'create/$', views.BushfireUpdateView.as_view(), name='bushfire_create'),
    url(r'initial/(?P<pk>\d+)/$', views.BushfireUpdateView.as_view(), name='bushfire_initial'),
    url(r'final/(?P<pk>\d+)/$', views.BushfireUpdateView.as_view(), name='bushfire_final'),
    url(r'^export/$', views.BushfireView.as_view(), name='export'),

]

