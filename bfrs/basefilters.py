from django_filters import filters
from django.db.models import Q

class QFilter(filters.CharFilter):
    def __init__(self, fields,**kwargs):
        super(QFilter,self).__init__( **kwargs)
        self.fields = fields

    def filter(self, qs, value):
        if not value :
            return qs
        if self.distinct:
            qs = qs.distinct()
        qfilter = None
        for field in self.fields:
            if qfilter:
                qfilter = qfilter | Q(**{"{0}__{1}".format(*field):value})
            else:
                qfilter = Q(**{"{0}__{1}".format(*field):value})
        qs = self.get_method(qs)(qfilter)
        return qs



