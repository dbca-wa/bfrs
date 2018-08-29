import traceback
import collections
import sys

from django.http import HttpResponse, HttpResponseRedirect, Http404, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.core.urlresolvers import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, FormView
from django.forms.formsets import formset_factory
from django.forms.widgets import CheckboxInput
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException
from django.core import serializers
from django import forms
from django.contrib.gis.db import models
from django.forms.models import inlineformset_factory
from django.conf import settings
from django.db.models import Q
from django.contrib.auth.models import User, Group
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone

from bfrs.models import (Profile, Bushfire, BushfireSnapshot,BushfireProperty,
        Region, District,
        Tenure, AreaBurnt,
        SNAPSHOT_INITIAL, SNAPSHOT_FINAL,
    )
from bfrs.forms import (ProfileForm, BushfireFilterForm,MergedBushfireForm,SubmittedBushfireForm,InitialBushfireForm,BushfireSnapshotViewForm,BushfireCreateForm,
        BushfireViewForm,InitialBushfireFSSGForm,AuthorisedBushfireFSSGForm,ReviewedBushfireFSSGForm,SubmittedBushfireFSSGForm,
        AuthorisedBushfireForm,ReviewedBushfireForm,AreaBurntFormSet, InjuryFormSet, DamageFormSet, PDFReportForm,
    )
from bfrs.utils import (breadcrumbs_li,
        update_damage_fs, update_injury_fs, 
        export_final_csv, export_excel, 
        update_status, serialize_bushfire,
        is_external_user, can_maintain_data, refresh_gokart,
        get_missing_mandatory_fields
    )
from bfrs.reports import BushfireReport, MinisterialReport, export_outstanding_fires 
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.forms import ValidationError
from datetime import datetime
import pytz
import json
from django.utils.dateparse import parse_duration

import django_filters
from django_filters import views as filter_views
from django_filters.widgets import BooleanWidget
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from reversion_compare.views import HistoryCompareDetailView

from .utils import invalidate_bushfire

import logging
logger = logging.getLogger(__name__)


class FormRequestMixin(object):
    """
    Add request initial parameter to form
    """
    def get_form_kwargs(self):
        """
        Returns the keyword arguments for instantiating the form.
        """
        kwargs = super(FormRequestMixin, self).get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

class MainUrlMixin(object):
    """
    get last main page url
    """
    def get_main_url(self):
        if self.request and self.request.session.has_key("lastMainUrl"):
            return self.request.session["lastMainUrl"]
        else:
            return reverse('main')

class BooleanFilter(django_filters.filters.BooleanFilter):
    field_class = forms.BooleanField


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

class ExceptionMixin(object):
    template_exception = 'exception.html'
    def dispatch(self, request, *args, **kwargs):
        try:
            return super(ExceptionMixin,self).dispatch(request,*args,**kwargs)
        except :
            exc_type, exc_value, exc_traceback = sys.exc_info()
            context = {}
            if settings.DEBUG:
                context["message"] = "".join(traceback.format_exception(exc_type,exc_value,exc_traceback))
            else:
                context["message"] = "".join(traceback.format_exception_only(exc_type,exc_value))

            traceback.print_exc()

            return TemplateResponse(request, self.template_exception, context=context)

class ProfileView(ExceptionMixin,MainUrlMixin,LoginRequiredMixin, generic.FormView):
    model = Profile
    form_class = ProfileForm
    template_name = 'registration/profile.html'
    success_url = 'main'

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests, instantiating a form instance with the passed
        POST variables and then checked for validity.
        """

        form = ProfileForm(request.POST, instance=request.user.profile)
        if form.is_valid():
            if 'cancel' not in self.request.POST:
                form.save()
            return HttpResponseRedirect(self.get_main_url())

        return TemplateResponse(request, self.template_name)


class BushfireView(ExceptionMixin,MainUrlMixin,LoginRequiredMixin, filter_views.FilterView):
#class BushfireView(LoginRequiredMixin, generic.ListView):
    #model = Bushfire
    filterset_class = BushfireFilter
    template_name = 'bfrs/bushfire.html'
    select_primary_bushfire_template = 'bfrs/select_primary_bushfire.html'
    link_bushfire_confirm_template = 'bfrs/link_bushfire_confirm.html'
    paginate_by = 50
    actions = collections.OrderedDict([("select_action","------------"),("merge_reports","Link/Merge"),("invalidate_duplicated_reports","Link/Duplication")])

    def get_filterset_kwargs(self, filterset_class):
        kwargs = super(BushfireView,self).get_filterset_kwargs(filterset_class)
        if (self.request.method == "POST"):
            #get the filter data from post
            kwargs["data"] = self.request.POST
        data = dict(kwargs["data"].iteritems()) if kwargs["data"] else {}
        kwargs["data"] = data
        filters = "&".join(["{}={}".format(k,v) for k,v in data.iteritems() if k in BushfireFilter.Meta.fields])
        if filters:
            self._filters = "?{}&".format(filters)
        else:
            self._filters = "?"

        filters_without_order = "&".join(["{}={}".format(k,v) for k,v in data.iteritems() if k in BushfireFilter.Meta.fields if k != "order_by"])
        if filters_without_order:
            self._filters_without_order = "?{}&".format(filters_without_order)
        else:
            self._filters_without_order = "?"

        profile = self.get_initial() # Additional profile Filters must also be added to the JS in bushfire.html- profile_field_list
        if not data.has_key('region'):
            data['region'] = profile['region'].id if profile['region'] else None
            data['district'] = profile['district'].id if profile['district'] else None

        if "include_archived" not in data:
            data["include_archived"] = False

        if "order_by" not in data:
            data["order_by"] = '-modified'

        #save the current url as the lastMainUrl which can be used when redirect or return from other pages
        self.request.session["lastMainUrl"] = self.request.get_full_path()

        return kwargs

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def get(self, request, *args, **kwargs):
        template_confirm = 'bfrs/confirm.html'
        template_snapshot_history = 'bfrs/snapshot_history.html'
        action = self.request.GET.get('action') if self.request.GET.has_key('action') else None
        if action == 'export_to_csv':
            qs = self.get_filterset(self.filterset_class).qs
            return export_final_csv(self.request, qs)
        elif action == 'export_to_excel':
            qs = self.get_filterset(self.filterset_class).qs
            return export_excel(self.request, qs)
        elif action == 'export_excel_outstanding_fires':
            # Only Reports that are Submitted, but not yet Authorised
            qs = self.get_filterset(self.filterset_class).qs.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
            return export_outstanding_fires(self.request, self.get_filterset(self.filterset_class).data['region'], qs)
        elif action == 'export_excel_ministerial_report':
            #return MinisterialReport().export()
            return BushfireReport().export()
        elif action == 'snapshot_history':
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            context = {
                'object': bushfire,
            }
            return TemplateResponse(request, template_snapshot_history, context=context)
        elif action is not None:
            #confirm actions
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            return TemplateResponse(request, template_confirm, context={'action': action, 'bushfire_id': bushfire.id})
        else:
            return  super(BushfireView, self).get(request, *args, **kwargs)
            

    def post(self, request, *args, **kwargs):
        action = self.request.POST.get('action')
        if not action :
            raise Exception("Action is missing.")

        self.action = action
        # Delete Review
        # Delete Final Authorisation
        # Mark Final Report as Reviewed
        if action == "confirm":
            confirm_action = self.request.POST.get("confirm_action")
            if not confirm_action:
                raise Exception("Confirm action is missing.")
            elif confirm_action in ('delete_review','delete_final_authorisation','mark_reviewed'):
                bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))
                update_status(request, bushfire, confirm_action)
                refresh_gokart(request, fire_number=bushfire.fire_number) #, region=None, district=None, action='update')
            # Archive / Unarchive
            elif confirm_action in ('archive','unarchive'):
                bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))
                update_status(request, bushfire, confirm_action)
            else:
                raise Exception("Unknown confirm action({})".format(confirm_action))

        elif action in self.actions:
            selected_ids = self.request.POST.getlist("selected_ids")
            if selected_ids:
                selected_ids = [int(identity) for identity in selected_ids] 

            self.selected_ids = selected_ids
            errors = []

            if action == 'select_action':
                errors = ["Please select an action to perform"]
                self.errors = errors
                return  super(BushfireView, self).get(request, *args, **kwargs)

            elif not selected_ids:
                errors = ["Please choose busfires before performing action ({})".format(self.actions.get(action))]
                self.errors = errors
                return  super(BushfireView, self).get(request, *args, **kwargs)

            elif action in ["merge_reports","invalidate_duplicated_reports"]:
                step = self.request.POST.get("step") or "select_primary_bushfire"
                bushfires = Bushfire.objects.filter(id__in = selected_ids)
                if bushfires.count() != len(selected_ids):
                    #some bushfire don't exist
                    errors += ["The bushfire({}) doesn't exist".format(identity) for identity in selected_ids if not any([r.id == identity for r in bushfires])]
                else:
                    if len(bushfires) < 2:
                        errors.append("Please choose at least two bushfires for action '{}'".format(self.actions.get(action)))
                    errors += ["The bushfire({0}) with status ({1}) is not eligible for action ({2}).".format(bf.fire_number,bf.report_status_name,self.actions.get(action)) for bf in bushfires if bf.report_status >= Bushfire.STATUS_INVALIDATED ]

                if errors:
                    #failed
                    self.errors = errors
                    return  super(BushfireView, self).get(request, *args, **kwargs)

                primary_bushfire_id = self.request.POST.get("primary_bushfire_id") or None
                primary_bushfire = None
                if primary_bushfire_id:
                    primary_bushfire_id = int(primary_bushfire_id)
                    try:
                        primary_bushfire = next(bf for bf in bushfires if bf.id == primary_bushfire_id)
                    except StopIteration:
                        #chosen bushfire is not in the bushfire list
                        primary_bushfire_id = None
                        errors.append("Chosen primary bushfire is in the bushfire lists")

                forms = [BushfireViewForm(instance=bf) for bf in bushfires]
                context = {
                    "errors":errors,
                    "action":action,
                    "action_name":self.actions.get(action),
                    "primary_bushfire_id": primary_bushfire_id,
                    "title":"Merging bushfire reports" if action == "merge_reports" else "Invalidate duplicated bushfire reports",
                    "bushfires":bushfires,
                    "forms":forms
                }
                if step == "select_primary_bushfire":
                    return TemplateResponse(request, self.select_primary_bushfire_template, context=context)
                elif step == "selected_primary_bushfire":
                    if not primary_bushfire_id:
                        #do not chosen any bushfire as primary bushfire
                        errors.append("Please choose a primary bushfire for '{}'".format(self.actions.get(action)))

                    context["target_status"] = "MERGED" if action == "merge_reports" else "DUPLICATED"

                    if errors:
                        return TemplateResponse(request, self.select_primary_bushfire_template, context=context)
                    
                    #temperary change the report status to the target status after the link action
                    #for bushfire in bushfires:
                    #    if bushfire.id != primary_bushfire_id:
                    #        bushfire.report_status = Bushfire.STATUS_MERGED if action == "merge_reports" else Bushfire.STATUS_DUPLICATED
                    """
                    if primary_bushfire.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
                        #chosen primary bushfire is final authorised, change it to submitted
                        primary_bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
                    """

                    return TemplateResponse(request, self.link_bushfire_confirm_template, context=context)

                elif step == "confirm":
                    update_status(request, (primary_bushfire,bushfires.exclude(id=primary_bushfire_id)), action,self.actions.get(action))
                else:
                    raise Exception("Unknown step({1}) for action({0})".format(action,step))
            else:
                raise Exception("Action({})is under developing".format(self.actions.get(action)))
        else:
            raise Exception("Unknown action({})" .format(action))

        return HttpResponseRedirect(self.get_main_url())

    def get_context_data(self, **kwargs):
        context = super(BushfireView, self).get_context_data(**kwargs)
        # update context with form - filter is already in the context
        context["errors"] = self.errors if hasattr(self,"errors") else None
        context['form'] = BushfireFilterForm(initial=context["filter"].data)
        context['order_by'] = context["filter"].data["order_by"]
        context['filters'] = "{}{}".format(reverse('main'),self._filters)
        context['filters_without_order'] = "{}{}".format(reverse('main'),self._filters_without_order)
        context['sss_url'] = settings.SSS_URL
        context['can_maintain_data'] = can_maintain_data(self.request.user)
        context['is_external_user'] = is_external_user(self.request.user)
        context['selected_ids'] = self.selected_ids if hasattr(self,"selected_ids") else None
        context['actions'] = self.actions
        if hasattr(self,"action"):
            context['action'] = self.action
        #if context["paginator"].num_pages == 1: 
        #    context['is_paginated'] = False
    
        referrer = self.request.META.get('HTTP_REFERER')
        if referrer and not ('initial' in referrer or 'final' in referrer or 'create' in referrer):
            #refresh_gokart(self.request) #, fire_number="") #, region=None, district=None, action='update')
            pass
        return context

class BushfireInitialSnapshotView(ExceptionMixin,FormRequestMixin,MainUrlMixin,LoginRequiredMixin, generic.DetailView):
    """
    To view the initial static data (after notifications 'Submitted')

    """
    model = Bushfire
    template_name = 'bfrs/bushfire_detail.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireInitialSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()

        context.update({
            'initial': True,
            'form': BushfireSnapshotViewForm(instance=self.object.initial_snapshot),
            'damages': self.object.initial_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL) if hasattr(self.object.initial_snapshot, 'damage_snapshot') else None,
            'injuries': self.object.initial_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL) if hasattr(self.object.initial_snapshot, 'injury_snapshot') else None,
            'tenures_burnt': self.object.initial_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL).order_by('id') if hasattr(self.object.initial_snapshot, 'tenures_burnt_snapshot') else None,
            'link_actions':[(self.get_main_url(),'Return','btn-info')],
        })
        return context

class BushfireFinalSnapshotView(ExceptionMixin,FormRequestMixin,MainUrlMixin,LoginRequiredMixin, generic.DetailView):
    """
    To view the final static data (after report 'Authorised')
    """
    model = Bushfire
    template_name = 'bfrs/bushfire_detail.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireFinalSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()

        link_actions = [(self.get_main_url(),'Return','btn-info')] 
        if can_maintain_data(self.request.user):
            link_actions.insert(0,(reverse('bushfire:bushfire_final',kwargs={"pk":self.object.id}) ,'Edit Authorised','btn-success'))
        context.update({
            'final': True,
            'form': BushfireSnapshotViewForm(instance=self.object.final_snapshot),
            'damages': self.object.final_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL) if hasattr(self.object.final_snapshot, 'damage_snapshot') else None,
            'injuries': self.object.final_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL) if hasattr(self.object.final_snapshot, 'injury_snapshot') else None,
            'tenures_burnt': self.object.final_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL).order_by('id') if hasattr(self.object.final_snapshot, 'tenures_burnt_snapshot') else None,
            'can_maintain_data': can_maintain_data(self.request.user),
            'link_actions':link_actions,
        })
        return context


@method_decorator(csrf_exempt, name='dispatch')
class BushfireUpdateView(ExceptionMixin,FormRequestMixin,MainUrlMixin,LoginRequiredMixin, UpdateView):
    """ Class will Create a new Bushfire and Update an existing Bushfire object"""

    model = Bushfire
    template_name = 'bfrs/bushfire_detail.html'
    template_error = 'bfrs/error.html'
    template_exception = 'exception.html'
    template_confirm = 'bfrs/confirm.html'
    template_mandatory_fields = 'bfrs/mandatory_fields.html'

    def get_form_class(self):
        obj = self.get_object()
        cls = BushfireViewForm
        if is_external_user(self.request.user):
            cls = BushfireViewForm
        elif obj is None or obj.report_status is None:
            cls = BushfireCreateForm
        elif obj.report_status == Bushfire.STATUS_MERGED :
            cls = MergedBushfireForm
        elif obj.report_status >= Bushfire.STATUS_INVALIDATED :
            cls = BushfireViewForm
        elif 'initial' in self.request.get_full_path():
            cls = BushfireViewForm if obj.is_init_authorised else (InitialBushfireFSSGForm if can_maintain_data(self.request.user) else InitialBushfireForm)
        elif 'final' in self.request.get_full_path():
            if obj.report_status == Bushfire.STATUS_INITIAL_AUTHORISED:
                cls = SubmittedBushfireFSSGForm if can_maintain_data(self.request.user) else SubmittedBushfireForm
            elif not can_maintain_data(self.request.user):
                cls = BushfireViewForm
            elif obj.report_status == Bushfire.STATUS_FINAL_AUTHORISED:
                cls = AuthorisedBushfireFSSGForm if can_maintain_data(self.request.user) else AuthorisedBushfireForm
            else:
                cls = ReviewedBushfireFSSGForm if can_maintain_data(self.request.user) else ReviewedBushfireForm

        return cls

    def get_initial(self):
        """
        Initial value for BufirefireUpdateForm
        """
        initial = {}
        if self.get_object():
            return initial

        # creating object ...
        if self.request.POST.has_key('sss_create'):
            initial['sss_data'] = self.request.POST.get('sss_create')

        return initial

    def get(self, request, *args, **kwargs):
        if not self.get_object() and is_external_user(self.request.user):
            # external user cannot create bushfire
            return TemplateResponse(request, self.template_error, context={'is_external_user': True, 'status':401}, status=401)

        return super(BushfireUpdateView, self).get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """ Overriding this method to allow UpdateView to both Create new object and Update an existing object"""
        obj = getattr(self,"object") if hasattr(self,"object") else None
        if not obj:
            if self.kwargs.get(self.pk_url_kwarg):
                obj = super(BushfireUpdateView, self).get_object(queryset)
            elif self.request.POST.has_key('bushfire_id') and self.request.POST.get('bushfire_id'):
                obj = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))
            if obj:
                setattr(self,"object",obj)
        return obj

    def post(self, request, *args, **kwargs):
        if is_external_user(request.user):
            return TemplateResponse(request, self.template_error, context={'is_external_user': True, 'status':401}, status=401)

        if self.request.POST.has_key('sss_create'):
            #posted from sss, display the bushfire create page
            return self.render_to_response(self.get_context_data())

        #posted from html page
        self.object = self.get_object() # needed for update

        action = self.request.POST.get('action')
        if not action:
            #no action, 
            #will not happen in the nomal scenario
            raise Exception("Request action is missing")

        self.action = action

        if action == "confirm":
            #confirm action
            confirm_action = self.request.POST.get("confirm_action")
            if not confirm_action:
                #confirm_action is missing
                #will not happen in the nomal scenario
                raise Exception("Confirm action is missing")

            if confirm_action == "invalidate":
                if self.request.POST.has_key('district') and not self.request.POST.get('district'):
                    #district is missing, throw exception
                    raise Exception("District is missing.")
                elif not self.object:
                    #bushfire report is missing.
                    raise Exception("Bushfire id is missing or does not exist.")
                district = District.objects.get(id=self.request.POST['district']) # get the district from the form
                if self.object.report_status!=Bushfire.STATUS_INVALIDATED:
                    self.object.invalid_details = request.POST.get('invalid_details')
                    self.object.district = district
                    self.object.region = district.region
                    invalidate_bushfire(self.object, self.request.user)
                    return HttpResponseRedirect(reverse("home"))
                else:
                    raise Exception("Bushfire has already been invalidated.")
            else:
                update_status(self.request, self.object, confirm_action)
                refresh_gokart(self.request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)
                return HttpResponseRedirect(self.get_main_url())

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        expected_status = None
        if action == "create" or (action == "submit" and self.object is None):
            pass
        elif action in ["save_draft","submit"]:
            expected_status = self.object.STATUS_INITIAL
        elif action in ["save_merged","submit"]:
            expected_status = self.object.STATUS_MERGED
        elif action in ["save_submitted","authorise"]:
            expected_status = self.object.STATUS_INITIAL_AUTHORISED
        elif action == "save_final":
            expected_status = self.object.STATUS_FINAL_AUTHORISED
        elif action == "save_reviewed":
            expected_status = self.object.STATUS_REVIEWED
        else:
            raise Exception("Unsupported action({})".format(action))
        if expected_status and self.object.report_status != expected_status:
            #report's status was changed after showing the page and before saving
            raise Exception("The status of the report({}) was changed from '{}' to '{}'".format(self.object.fire_number,self.object.REPORT_STATUS_MAP.get(expected_status),self.object.report_status_name))

        #get the original district to check whether the district is changed or not
        origin_district = self.object.district if self.object else None
        origin_fire_number = self.object.fire_number if self.object else None
        new_district = None
        if form.is_valid():
            new_district = form.instance.district
            if origin_district is None or form.instance.district == origin_district:
                #district is not changed
                return self.form_valid(request, form,action)
            else:
                #district has been changed
                form.instance.region = origin_district.region # this will allow invalidate_bushfire() to invalidate and create the links as necessary if user confirms in the confirm page
                form.instance.district = origin_district
                form.instance.fire_number = origin_fire_number
                self.object = form.save()
                message = 'District has changed (from {} to {}). This action will invalidate the existing bushfire and create  a new bushfire with the new district, and a new fire number.'.format(
                    origin_district.name,
                    form["district"].name
                )
                context={
                    'action': 'invalidate',
                    'district': new_district.id,
                    'message': message,
                }
                return TemplateResponse(request, self.template_confirm, context=context)
        else:
            context = self.get_context_data()
            return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, request, form, action,area_burnt_formset=None, injury_formset=None, damage_formset=None):
        #save the report first
        self.object = form.save()

        refresh_gokart(self.request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)
        
        if action in ["submit","authorise","save_final","save_reviewed"]:
            #show confirm page
            context = self.get_context_data()
            missing_fields = get_missing_mandatory_fields(self.object,action)
            if missing_fields:
                if action in ["save_final","save_reviewed"]:
                    #delete authorise, because some mandatory fields are empty,this will trigger to create a report snatpshot
                    update_status(request, self.object, 'delete_authorisation_(missing_fields_-_FSSDRS)')
                #have missing fields,show error pages
                context['mandatory_fields'] = missing_fields
                context['action'] = action
                return TemplateResponse(request, self.template_mandatory_fields, context=context)
            elif action == "submit":
                #skip confirm step when submit a initial report
                update_status(self.request, self.object, action)
                refresh_gokart(self.request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)
                return HttpResponseRedirect(self.get_main_url())
            elif action in ["submit","authorise"]:
                context["confirm_action"] = action
                context["form"] = BushfireViewForm(instance=self.object)
                context["submit_actions"]=[("confirm","Yes, I'm sure",'btn-success')]
                if action == "submit":
                    context["link_actions"]=[(reverse("bushfire:bushfire_initial",kwargs={"pk":self.object.pk}),"Cancel","btn-danger")]
                else:
                    context["link_actions"]=[(reverse("bushfire:bushfire_final",kwargs={"pk":self.object.pk}),"Cancel","btn-danger")]
                #show confirm page
                return TemplateResponse(request, self.template_name, context=context)
            elif action in ["save_final","save_reviewed"]:
                #create a snapshot
                serialize_bushfire('final', action, self.object)

        return HttpResponseRedirect(self.get_main_url())

    def get_context_data(self, **kwargs):
        bushfire = self.get_object()
        self.object = bushfire
        context = super(BushfireUpdateView, self).get_context_data(**kwargs)

        submit_actions = None
        context.update({
            'initial':'initial' in self.request.get_full_path(),
            'create':False if bushfire else True,
            'can_maintain_data': can_maintain_data(self.request.user),
            'link_actions':[(self.get_main_url(),'Cancel','btn-danger')],
            'submit_actions':context['form'].submit_actions,
        })

        return context


class BushfireHistoryCompareView(HistoryCompareDetailView):
    """
    View for reversion_compare
    """
    model = Bushfire
    template_name = 'bfrs/history.html'


class ReportView(ExceptionMixin,FormView):
    """
    View for reversion_compare
    """
    model = Bushfire
    template_name = 'bfrs/report.html'
    form_class = PDFReportForm
    success_url = '/'

    def get_initial(self):
        initial = {}
        initial['author'] = self.request.user.get_full_name()
        #initial['branch'] = 'Fire Management Services Branch'
        #initial['division'] = 'Regional and Fire Management Services Division'
        #initial['title'] = 'BUSHFIRE SUPPRESSION'
        return initial

    def form_invalid(self, form):
        context = self.get_context_data()
        context.update({'form': form})
        return self.render_to_response(context)

    def form_valid(self, form):
        valid = super(ReportView, self).form_valid(form)
        if valid.status_code == 302:
            #messages.success(self.request, 'Running Ministerial Report ...')
            return MinisterialReport().pdflatex(self.request, form.cleaned_data)
        return super(ReportView, self).form_valid(form)


