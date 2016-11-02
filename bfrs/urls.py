from django.conf.urls import include, url
from bfrs.models import Bushfire
from bfrs import views

#urlpatterns = patterns('',
urlpatterns = [
    #url(r'^$', views.BushfireView.as_view(), name='index'),
    url(r'create/$', views.BushfireCreateView.as_view(), name='bushfire_create'),
    url(r'initial/(?P<pk>\d+)/$', views.BushfireInitUpdateView.as_view(), name='bushfire_initial'),
    url(r'final/(?P<pk>\d+)/$', views.BushfireUpdateView.as_view(), name='bushfire_final'),

    url(r'create2/$', views.BushfireCreateTest2View.as_view(), name='bushfire_create2'),
    url(r'create_test/$', views.BushfireCreateTestView.as_view(), name='bushfire_create_test'),
]
#)

