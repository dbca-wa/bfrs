from django.conf.urls import include, url
from bfrs.models import Bushfire
from bfrs import views

urlpatterns = [
    url(r'create/$', views.BushfireUpdateView.as_view(), name='bushfire_create'),
    url(r'initial/(?P<pk>\d+)/$', views.BushfireUpdateView.as_view(), name='bushfire_initial'),
    url(r'initial/snapshot/(?P<pk>\d+)/$', views.BushfireInitialSnapshotView.as_view(), name='initial_snapshot'),
    url(r'final/(?P<pk>\d+)/$', views.BushfireUpdateView.as_view(), name='bushfire_final'),
    url(r'final/snapshot/(?P<pk>\d+)/$', views.BushfireFinalSnapshotView.as_view(), name='final_snapshot'),
#    url(r'^export/$', views.BushfireView.as_view(), name='export'),

    url(r'^history/(?P<pk>\d+)/$', views.BushfireHistoryCompareView.as_view(), name='bushfire_history'),
    url(r'report/$', views.ReportView.as_view(), name='bushfire_report'),

]

