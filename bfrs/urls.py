from django.conf.urls import include, url
from bfrs.models import Bushfire
from bfrs import views

urlpatterns = [
    url(r'create/$', views.BushfireCreateView.as_view(), name='bushfire_create'),
    url(r'initial/(?P<pk>\d+)/$', views.BushfireInitUpdateView.as_view(), name='bushfire_initial'),
    url(r'final/(?P<pk>\d+)/$', views.BushfireFinalUpdateView.as_view(), name='bushfire_final'),
    #url(r'review/(?P<pk>\d+)/$', views.BushfireReviewUpdateView.as_view(), name='bushfire_review'),
    url(r'^export/$', views.BushfireView.as_view(), name='export'),

]

