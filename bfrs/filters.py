from datetime import date,timedelta

import django_filters

from django.db.models import Q
from django.utils import timezone
from django import forms

from .models import (Bushfire,Document)
import basefilters

class BooleanFilter(django_filters.filters.BooleanFilter):
    field_class = forms.BooleanField

class NullBooleanFilter(django_filters.filters.BooleanFilter):
    field_class = forms.NullBooleanField

BUSHFIRE_SORT_MAPPING={
    "modified":["modified","fire_number"],
    "-modified":["-modified","fire_number"],
    "-dfes_incident_no":["-dfes_incident_no","fire_number"],
    "dfes_incident_no":["dfes_incident_no","fire_number"],
    "name":["name","fire_number"],
    "-name":["-name","fire_number"],
    "job_code":["job_code","fire_number"],
    "-job_code":["-job_code","fire_number"],
}


class BushfireFilter(django_filters.FilterSet):

    # try/except block hack added here to allow initial migration before the model exists - else migration fails
    try:
        region = django_filters.Filter(name="region",label='Region',lookup_expr="exact")
        district = django_filters.Filter(name="district",label='District',lookup_expr="exact")
        year = django_filters.Filter(name="year",label='Year',lookup_expr="exact")
        reporting_year = django_filters.Filter(name="reporting_year",label='Reporting Year',lookup_expr="exact")
        report_status = django_filters.Filter(label='Report Status', name='report_status', method='filter_report_status')
        fire_number = django_filters.CharFilter(name='fire_number', label='Search', method='filter_fire_number')
        include_archived = BooleanFilter(name='include_archived',label='Include archived', method='filter_include_archived')
        exclude_missing_final_fire_boundary = BooleanFilter(name='exclude_missing_final_fire_boundary',label='Exclude missing final fire boundary', method='filter_exclude_missing_final_fire_boundary')

        order_by = django_filters.Filter(name="order_by",label="Order by",method="filter_order_by")
    except:
        pass

    def filter_report_status(self, queryset, name, value):
        status = int(value)
        if status == Bushfire.STATUS_MISSING_FINAL:
            queryset = queryset.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
        elif status == 900:
            #pending to review
            queryset = queryset.filter(report_status=Bushfire.STATUS_FINAL_AUTHORISED,final_fire_boundary=True,fire_not_found=False,area__gt=0)
        elif status == -1:
            queryset = queryset.exclude(report_status=Bushfire.STATUS_INVALIDATED)
        else:
            queryset = queryset.filter(report_status=status)

        return queryset

    def filter_fire_number(self, queryset, filter_name, value):
        """ 
        Filter for Global Search Box in main page
        Searches on:
            1. fire_number
            2. name (fire name)
            3. dfes_incident_no

        Works because 'fire_number' present in self.data (from <input> field in base.html) 
        NOTE: filter_name in arg is a required dummy arg, not used.
        """
        return queryset.filter(Q(fire_number__icontains=value) | Q(name__icontains=value) | Q(dfes_incident_no__icontains=value))


    def filter_include_archived(self, queryset, filter_name, value):
        if not value:
            queryset = queryset.exclude(archive=True)

        return queryset
    
    def filter_exclude_missing_final_fire_boundary(self, queryset, filter_name, value):
        if value:
            queryset = queryset.filter(final_fire_boundary=True)
        return queryset

    def filter_order_by(self,queryset,filter_name,value):
        if value:
            if value[0] == "+":
                value = value[1:]
            if value in BUSHFIRE_SORT_MAPPING:
                queryset = queryset.order_by(*BUSHFIRE_SORT_MAPPING[value])
            else:
                queryset = queryset.order_by(value)

        return queryset

    class Meta:
        model = Bushfire
        fields = [
            'region',
            'district',
            'year',
            'reporting_year',
            'report_status',
            'fire_number',
            'include_archived',
            'exclude_missing_final_fire_boundary',
            'order_by'
        ]


DOCUMENT_SORT_MAPPING={
    "document_tag":["tag__name","custom_tag","document"],
    "-document_tag":["-tag__name","-custom_tag","-document"],
    "category":["category__name","tag__name","custom_tag","document"],
    "-category":["-category__name","-tag__name","-custom_tag","-document"],
    "creator":["creator__username","category__name","tag__name","custom_tag","document"],
    "-creator":["-creator__username","-category__name","-tag__name","-custom_tag","-document"],
    "created":["created","category__name","tag__name","custom_tag","document"],
    "-created":["-created","-category__name","-tag__name","-custom_tag","-document"],
    "document_created":["document_created","category__name","tag__name","custom_tag","document"],
    "-document_created":["-document_created","-category__name","-tag__name","-custom_tag","-document"],
}
DOCUMENT_MODIFIED_CHOICES = (
    ("","Any date"),
    ("today","Today"),
    ("last_7_days","Past 7 days"),
    ("current_month","This month"),
    ("current_year","This year"),
)
class BushfireDocumentFilter(django_filters.FilterSet):

    # try/except block hack added here to allow initial migration before the model exists - else migration fails
    try:
        category = django_filters.Filter(name="category",label='category',lookup_expr="exact")
        upload_bushfire = django_filters.Filter(name="upload_bushfire",label='Upload Bushfire',lookup_expr="exact")
        bushfire = django_filters.Filter(name="bushfire",label='Bushfire',lookup_expr="exact")
        archived = NullBooleanFilter(name='archived',label='archived', lookup_expr="exact")
        order_by = django_filters.Filter(name="order_by",label="Order by",method="filter_order_by")
        last_modified = django_filters.Filter(name="modified",label="Modified",method="filter_last_modified")
        search = basefilters.QFilter(fields=(("tag__name","icontains"),("custom_tag","icontains"),("creator__username","icontains")))
    except:
        pass

    def filter_last_modified(self,queryset,filter_name,value):
        if not value:
            return queryset
        if value == "today":
            d = date.today()
            queryset = queryset.filter(modified__gte=d)
        elif value == "last_7_days":
            d = date.today() - timedelta(days=6)
            queryset = queryset.filter(modified__gte=d)
        elif value == "current_month":
            d = date.today()
            d = date(d.year,d.month,1)
            queryset = queryset.filter(modified__gte=d)
        elif value == "current_year":
            d = date.today()
            d = date(d.year,1,1)
            queryset = queryset.filter(modified__gte=d)

        return queryset

    def filter_order_by(self,queryset,filter_name,value):
        if not value:
            value = "-created"

        if value[0] == "+":
            value = value[1:]
        if value in DOCUMENT_SORT_MAPPING:
            queryset = queryset.order_by(*DOCUMENT_SORT_MAPPING[value])
        else:
            queryset = queryset.order_by(value)

        return queryset

    class Meta:
        model = Document
        fields = [
            'category',
            'upload_bushfire',
            'archived',
            'order_by'
        ]

