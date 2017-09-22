from django.http import HttpResponse, HttpResponseRedirect, Http404, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.core.urlresolvers import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, FormView
from django.forms.formsets import formset_factory
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

from bfrs.models import (Profile, Bushfire, BushfireSnapshot,
        Region, District,
        Tenure, AreaBurnt,
        SNAPSHOT_INITIAL, SNAPSHOT_FINAL,
    )
from bfrs.forms import (ProfileForm, BushfireFilterForm, BushfireUpdateForm,
        AreaBurntFormSet, InjuryFormSet, DamageFormSet, 
    )
from bfrs.utils import (breadcrumbs_li,
        create_areas_burnt, update_areas_burnt_fs, update_damage_fs, update_injury_fs, 
        export_final_csv, export_excel, 
        update_status, serialize_bushfire,
        rdo_email, pvs_email, fpc_email, pica_email, pica_sms, police_email, dfes_email, fssdrs_email,
        invalidate_bushfire, is_external_user, can_maintain_data, refresh_gokart, clear_gokart_session, 
        authorise_report, check_district_changed,
    )
from bfrs.reports import MinisterialReport, export_outstanding_fires 
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

import logging
logger = logging.getLogger(__name__)


def reporting_years():
    """ Returns: [[2016, '2016/2017'], [2017, '2017/2018']] """
    yrs = list(Bushfire.objects.values_list('reporting_year', flat=True).distinct())
    return [[yr, '/'.join([str(yr),str(yr+1)])] for yr in yrs]


class BooleanFilter(django_filters.filters.Filter):
    field_class = forms.BooleanField


class BushfireFilter(django_filters.FilterSet):

    # try/except block hack added here to allow initial migration before the model exists - else migration fails
    try:
        YEAR_CHOICES = [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct()]
        RPT_YEAR_CHOICES = [[i['reporting_year'], i['reporting_year']] for i in Bushfire.objects.all().values('reporting_year').distinct()]

        REGION_CHOICES = []
        for region in Region.objects.distinct('name'):
            REGION_CHOICES.append([region.id, region.name])

        DISTRICT_CHOICES = []
        for district in District.objects.distinct('name'):
            DISTRICT_CHOICES.append([district.id, district.name])

        region = django_filters.ChoiceFilter(choices=REGION_CHOICES, label='Region')
        district = django_filters.ChoiceFilter(choices=DISTRICT_CHOICES, label='District')
        year = django_filters.ChoiceFilter(choices=YEAR_CHOICES, label='Year')
        reporting_year = django_filters.ChoiceFilter(choices=RPT_YEAR_CHOICES, label='Reporting Year')
        report_status = django_filters.ChoiceFilter(choices=Bushfire.REPORT_STATUS_CHOICES, label='Report Status', name='report_status', method='filter_report_status')
        fire_number = django_filters.CharFilter(name='fire_number', label='Search', method='filter_fire_number')
    except:
        pass

    def filter_report_status(self, queryset, name, value):
        if int(value) == Bushfire.STATUS_MISSING_FINAL:
            return queryset.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
        return queryset.filter(report_status=value)

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


    class Meta:
        model = Bushfire
        fields = [
            'region_id',
            'district_id',
            'year',
            'reporting_year',
            'report_status',
            'fire_number',
        ]
        order_by = (
            ('region_id', 'Region'),
            ('district_id', 'District'),
            ('year', 'Year'),
            ('reporting_year', 'Reporting Year'),
            ('report_status', 'Report Status'),
            ('fire_number', 'Search'),
        )

    def __init__(self, *args, **kwargs):
        super(BushfireFilter, self).__init__(*args, **kwargs)

        try:
            # allows dynamic update of the filter set, on page refresh
            self.filters['year'].extra['choices'] = [[None, '---------']] + [[i['year'], str(i['year']) + '/' + str(i['year']+1)] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]
            self.filters['reporting_year'].extra['choices'] = [[None, '---------']] + [[i['reporting_year'], str(i['reporting_year']) + '/' + str(i['reporting_year']+1)] for i in Bushfire.objects.all().values('reporting_year').distinct().order_by('reporting_year')]
            if not can_maintain_data(self.request.user):
                # pop the 'Reviewed' option
                self.filters['report_status'].extra['choices'] = [(u'', '---------'), (1, 'Initial Fire Report'), (2, 'Notifications Submitted'), (3, 'Report Authorised'), (5, 'Invalidated'), (6, 'Outstanding Fires')]
        except:
            pass


class ProfileView(LoginRequiredMixin, generic.FormView):
    model = Profile
    form_class = ProfileForm
    template_name = 'registration/profile.html'
    success_url = 'main'

    def get_success_url(self):
        return reverse('main')

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
            return HttpResponseRedirect(self.get_success_url())

        return TemplateResponse(request, self.template_name)


class BushfireView(LoginRequiredMixin, filter_views.FilterView):
#class BushfireView(LoginRequiredMixin, generic.ListView):
    #model = Bushfire
    filterset_class = BushfireFilter
    template_name = 'bfrs/bushfire.html'
    paginate_by = 50

    def get_queryset(self):
        if self.request.GET.has_key('report_status') and int(self.request.GET.get('report_status'))==Bushfire.STATUS_INVALIDATED:
            return super(BushfireView, self).get_queryset()

        return Bushfire.objects.exclude(report_status=Bushfire.STATUS_INVALIDATED)

    def get_success_url(self):
        return reverse('main')

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def get(self, request, *args, **kwargs):
        template_confirm = 'bfrs/confirm.html'
        template_initial = 'bfrs/detail.html'
        template_final = 'bfrs/final.html'
        template_snapshot_history = 'bfrs/snapshot_history.html'

        if self.request.GET.has_key('export_to_csv'):
            report = self.request.GET.get('export_to_csv')
            if eval(report):
                qs = self.get_filterset(self.filterset_class).qs
                return export_final_csv(self.request, qs)

        if self.request.GET.has_key('export_to_excel'):
            report = self.request.GET.get('export_to_excel')
            if eval(report):
                qs = self.get_filterset(self.filterset_class).qs
                return export_excel(self.request, qs)

        if self.request.GET.has_key('export_excel_outstanding_fires'):
            report = self.request.GET.get('export_excel_outstanding_fires')
            if eval(report):
                # Only Reports that are Submitted, but not yet Authorised
                qs = self.get_filterset(self.filterset_class).qs.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
                return export_outstanding_fires(self.request, self.get_filterset(self.filterset_class).data['region'], qs)

        if self.request.GET.has_key('export_excel_ministerial_report'):
            report = self.request.GET.get('export_excel_ministerial_report')
            if eval(report):
                return MinisterialReport().export()

        if self.request.GET.has_key('pdf_ministerial_report'):
            report = self.request.GET.get('pdf_ministerial_report')
            if eval(report):
                return MinisterialReport().pdflatex(request)


        if self.request.GET.has_key('action'):
            action = self.request.GET.get('action')
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            if action == 'snapshot_history':
                context = {
                    'object': bushfire,
                }
                return TemplateResponse(request, template_snapshot_history, context=context)

        if self.request.GET.has_key('confirm_action'):
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            action = self.request.GET.get('confirm_action')

            return TemplateResponse(request, template_confirm, context={'action': action, 'bushfire_id': bushfire.id})

        try:
            return  super(BushfireView, self).get(request, *args, **kwargs)
        finally:
            clear_gokart_session(request)
            

    def post(self, request, *args, **kwargs):
        if self.request.POST.has_key('bushfire_id'):
            bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))

        if self.request.POST.has_key('action'):
            action = self.request.POST.get('action')

            # Delete Review
            if action == 'delete_review' and bushfire.is_reviewed:
                logger.info('Action Delete Review {} - FSSDRS user {}'.format(bushfire.fire_number, request.user.get_full_name()))
                update_status(request, bushfire, action)

            # Delete Final Authorisation
            elif action == 'delete_final_authorisation' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                logger.info('Action Delete Authorisation {} - FSSDRS user {}'.format(bushfire.fire_number, request.user.get_full_name()))
                update_status(request, bushfire, action)

            # Mark Final Report as Reviewed
            elif action == 'mark_reviewed' and bushfire.can_review:
                update_status(request, bushfire, action)

            # Archive
            elif action == 'archive' and bushfire.report_status>=Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.archive = True
            elif action == 'unarchive' and bushfire.archive:
                bushfire.archive = False

            bushfire.save()

        refresh_gokart(request, fire_number=bushfire.fire_number) #, region=None, district=None, action='update')

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super(BushfireView, self).get_context_data(**kwargs)

        initial = {} # initial parameter prevents the form from resetting, if the region and district filters had a value set previously
        profile = self.get_initial() # Additional profile Filters must also be added to the JS in bushfire.html- profile_field_list
        if self.request.GET.has_key('region'):
            initial.update({'region': self.request.GET['region']})
        elif profile['region']:
            initial.update({'region': profile['region'].id})
            self.object_list = self.object_list.filter(region=profile['region'])

        if self.request.GET.has_key('district'):
            initial.update({'district': self.request.GET['district']})
        elif profile['district']:
            initial.update({'district': profile['district'].id})
            self.object_list = self.object_list.filter(district=profile['district'])

        if not self.request.GET.has_key('include_archived'):
            self.object_list = self.object_list.exclude(archive=True)
        else:
            initial.update({'include_archived': self.request.GET.get('include_archived')})

        if self.request.GET.has_key('exclude_missing_final_fire_boundary'):
            self.object_list = self.object_list.filter(final_fire_boundary=True)
        initial.update({'exclude_missing_final_fire_boundary': self.request.GET.get('exclude_missing_final_fire_boundary')})

        bushfire_list = self.object_list.order_by('-modified')
        paginator = Paginator(bushfire_list, self.paginate_by)
        page = self.request.GET.get('page')
        try:
            object_list_paginated = paginator.page(page)
        except PageNotAnInteger:
            object_list_paginated = paginator.page(1)
        except EmptyPage:
            object_list_paginated = paginator.page(paginator.num_pages)

        # update context with form - filter is already in the context
        context['form'] = BushfireFilterForm(initial=initial)
        context['object_list'] = object_list_paginated
        context['sss_url'] = settings.SSS_URL
        context['can_maintain_data'] = can_maintain_data(self.request.user)
        context['is_external_user'] = is_external_user(self.request.user)
        if paginator.num_pages == 1: 
            context['is_paginated'] = False

        referrer = self.request.META.get('HTTP_REFERER')
        if referrer and not ('initial' in referrer or 'final' in referrer or 'create' in referrer):
            refresh_gokart(self.request) #, fire_number="") #, region=None, district=None, action='update')
        return context

class BushfireInitialSnapshotView(LoginRequiredMixin, generic.DetailView):
    """
    To view the initial static data (after notifications 'Submitted')

    """
    model = Bushfire
    template_name = 'bfrs/detail_summary.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireInitialSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()

        context.update({
            'initial': True,
            'snapshot': self.object.initial_snapshot,
            'damages': self.object.initial_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL) if hasattr(self.object.initial_snapshot, 'damage_snapshot') else None,
            'injuries': self.object.initial_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL) if hasattr(self.object.initial_snapshot, 'injury_snapshot') else None,
            'tenures_burnt': self.object.initial_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL).order_by('id') if hasattr(self.object.initial_snapshot, 'tenures_burnt_snapshot') else None,
        })
        return context


class BushfireFinalSnapshotView(LoginRequiredMixin, generic.DetailView):
    """
    To view the final static data (after report 'Authorised')
    """
    model = Bushfire
    template_name = 'bfrs/detail_summary.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireFinalSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()

        context.update({
            'final': True,
            'snapshot': self.object.final_snapshot,
            'damages': self.object.final_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL) if hasattr(self.object.final_snapshot, 'damage_snapshot') else None,
            'injuries': self.object.final_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL) if hasattr(self.object.final_snapshot, 'injury_snapshot') else None,
            'tenures_burnt': self.object.final_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL).order_by('id') if hasattr(self.object.final_snapshot, 'tenures_burnt_snapshot') else None,
            'can_maintain_data': can_maintain_data(self.request.user),
        })
        return context


@method_decorator(csrf_exempt, name='dispatch')
class BushfireUpdateView(LoginRequiredMixin, UpdateView):
    """ Class will Create a new Bushfire and Update an existing Bushfire object"""

    model = Bushfire
    form_class = BushfireUpdateForm
    template_name = 'bfrs/detail.html'
    template_summary = 'bfrs/detail_summary.html'

    def get_template_names(self):
        obj = self.get_object()
        if is_external_user(self.request.user):
            return [self.template_summary]
        elif 'initial' in self.request.get_full_path() and obj.is_init_authorised:
            return [self.template_summary]
        elif 'final' in self.request.get_full_path() and obj.is_final_authorised and not can_maintain_data(self.request.user):
            return [self.template_summary]
        return super(BushfireUpdateView, self).get_template_names()

    def get_success_url(self):
        return reverse("home")

    def get_initial(self):

        initial = {}
        if not self.get_object():
            # if creating object ...
            profile, created = Profile.objects.get_or_create(user=self.request.user)
            initial['region'] = profile.region
            initial['district'] = profile.district

        if self.request.POST.has_key('sss_create'):
            sss = json.loads(self.request.POST.get('sss_create'))

            if sss.has_key('sss_id') and sss['sss_id']:
                initial['sss_id'] = sss['sss_id']

            if sss.has_key('area') and sss['area'].has_key('total_area') and sss['area'].get('total_area'):
                initial_area = round(float(sss['area']['total_area']), 2)
                initial['initial_area'] = initial_area if initial_area > 0 else 0.01

            # NOTE initial area (and area) includes 'Other Area', but recording separately to allow for updates - since this is not always provided, if area is not updated
            if sss.has_key('area') and sss['area'].has_key('other_area') and sss['area'].get('other_area'):
                other_area = round(float(sss['area']['other_area']), 2)
                initial['other_area'] = other_area if other_area > 0 else 0.01

            if sss.has_key('origin_point') and isinstance(sss['origin_point'], list):
                initial['origin_point_str'] = Point(sss['origin_point']).get_coords()
                initial['origin_point'] = Point(sss['origin_point'])

            if sss.has_key('origin_point_mga'):
                initial['origin_point_mga'] = sss['origin_point_mga']

            if sss.has_key('fire_boundary') and isinstance(sss['fire_boundary'], list):
                initial['fire_boundary'] = MultiPolygon([Polygon(*p) for p in sss['fire_boundary']])

            if sss.has_key('fb_validation_req'):
                initial['fb_validation_req'] = sss['fb_validation_req']

            if sss.has_key('fire_position') and sss.get('fire_position'):
                initial['fire_position'] = sss['fire_position']

            if sss.has_key('tenure_ignition_point') and sss['tenure_ignition_point'] and \
                sss['tenure_ignition_point'].has_key('category') and sss['tenure_ignition_point']['category']:
                try:
                    initial['tenure'] = Tenure.objects.get(name__istartswith=sss['tenure_ignition_point']['category'])
                except:
                    initial['tenure'] = Tenure.objects.get(name='Other')
            else:
                initial['tenure'] = Tenure.objects.get(name='Other')

            if sss.has_key('region_id') and sss.has_key('district_id') and sss.get('district_id'):
                initial['region'] = Region.objects.get(id=sss['region_id'])
                initial['district'] = District.objects.get(id=sss['district_id'])

            # Must pop this at the end - not needed, and can be very large
            if sss.has_key('fire_boundary'):
                sss.pop('fire_boundary')
            initial['sss_data'] = json.dumps(sss)

        return initial

    def get(self, request, *args, **kwargs):
        if not self.get_object() and is_external_user(self.request.user):
            # external user cannot create bushfire
            return TemplateResponse(request, 'bfrs/error.html', context={'is_external_user': True, 'status':401}, status=401)

        return super(BushfireUpdateView, self).get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """ Overriding this method to allow UpdateView to both Create new object and Update an existing object"""
        if self.kwargs.get(self.pk_url_kwarg):
            return super(BushfireUpdateView, self).get_object(queryset)
        elif self.request.POST.has_key('bushfire_id') and self.request.POST.get('bushfire_id'):
            return Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))
        return None

    def post(self, request, *args, **kwargs):
        if self.request.POST.has_key('sss_create'):
            return self.render_to_response(self.get_context_data())

        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        if self.request.POST.has_key('action'): # and 'create' not in self.request.get_full_path():
            # the 'initial_submit' already cleaned and saved the form, no need to save again
            # we are here because the redirected page confirmed this action
            action = self.request.POST.get('action')
            if action == 'Submit' or action == 'Authorise':
                update_status(self.request, self.object, action)
                refresh_gokart(self.request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)
                return HttpResponseRedirect(self.get_success_url())

        # update district, if it has changed (invalidates the current report and creates another with a new fire number)
        response = check_district_changed(self.request, self.object, form)
        if response:
            return response

        injury_formset          = InjuryFormSet(self.request.POST, prefix='injury_fs')
        damage_formset          = DamageFormSet(self.request.POST, prefix='damage_fs')
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')

        if form.is_valid():
            if form.cleaned_data['fire_not_found']:
                return self.form_valid(request, form)
            if injury_formset.is_valid(form.cleaned_data['injury_unknown']) and damage_formset.is_valid(form.cleaned_data['damage_unknown']): # No need to check area_burnt_formset since the fs is readonly
                return self.form_valid(request, form, area_burnt_formset, injury_formset, damage_formset)
            else:
                return self.form_invalid(request, form, area_burnt_formset, injury_formset, damage_formset)
        else:
            return self.form_invalid(request, form, area_burnt_formset, injury_formset, damage_formset)


    def form_invalid(self, request, form, area_burnt_formset, injury_formset, damage_formset):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'area_burnt_formset': area_burnt_formset})
        context.update({'injury_formset': injury_formset})
        context.update({'damage_formset': damage_formset})
        return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, request, form, area_burnt_formset=None, injury_formset=None, damage_formset=None):
        template_summary = 'bfrs/detail_summary.html'
        template_error = 'bfrs/error.html'

        if is_external_user(request.user):
            return TemplateResponse(request, template_error, context={'is_external_user': True, 'status':401}, status=401)

        self.object = form.save(commit=False)
        if not hasattr(self.object, 'creator'):
            self.object.creator = request.user
        self.object.modifier = request.user

        # reset fields
        if self.object.cause and not self.object.cause.name.startswith('Other'):
            self.object.other_cause = None
        if self.object.cause and not self.object.cause.name.startswith('Escape P&W'):
            self.object.prescribed_burn_id = None
        if self.object.tenure and not self.object.tenure.name.startswith('Other'):
            self.object.other_tenure = None
        if self.object.dispatch_pw:
            self.object.dispatch_pw = int(self.object.dispatch_pw)
        self.object.save()

        if not self.get_object():
            areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        injury_updated = update_injury_fs(self.object, injury_formset)
        damage_updated = update_damage_fs(self.object, damage_formset)

        # append/update 'Other' areas_burnt
        if self.request.POST.has_key('private_area') and self.request.POST.has_key('other_crown_area'): # and self.object.final_fire_boundary:
            if self.request.POST.get('private_area'):
                private_tenure = self.request.POST.get('private_tenure')
                private_area = self.request.POST.get('private_area')
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name=private_tenure), defaults={"area": private_area})

            if self.request.POST.get('other_crown_area'):
                other_crown_tenure = self.request.POST.get('other_crown_tenure')
                other_crown_area = self.request.POST.get('other_crown_area')
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name=other_crown_tenure), defaults={"area": other_crown_area})
        elif self.object.area_limit:
            # if user selects there own final area, set the area to the tenure of ignition point (Tenure, Other Crown, (Other) Private Property)
            self.object.tenures_burnt.all().delete()
            if self.object.other_tenure == Bushfire.IGNITION_POINT_PRIVATE:
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name='Private Property'), defaults={"area": self.object.area})
            elif self.object.other_tenure == Bushfire.IGNITION_POINT_CROWN:
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name='Other Crown'), defaults={"area": self.object.area})
            elif not self.object.other_tenure:
                self.object.tenures_burnt.update_or_create(tenure=self.object.tenure, defaults={"area": self.object.area})

        refresh_gokart(self.request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)

        # This section to Submit/Authorise report, placed here to allow any changes to be cleaned and saved first - effectively the 'Submit' btn is a 'save and submit'
        if self.request.POST.has_key('submit_initial') or self.request.POST.has_key('authorise_final') or \
           (self.request.POST.has_key('_save') and self.request.POST.get('_save') and self.object.is_final_authorised):
            response = authorise_report(self.request, self.object)
            if response:
                return response

        if self.object.report_status >=  Bushfire.STATUS_FINAL_AUTHORISED:
            # if bushfire has been authorised, update snapshot and archive old snapshot
            # That is, if FSSDRS group update the final report after it has been authorised, we archive the existing data
            try:
                serialize_bushfire('final', action, self.object)
            except NameError:
                # update is occuring after report has already been authorised (action is undefined) - ie. it is being Reviewed by FSSDRS
                serialize_bushfire('final', 'Review', self.object)

        self.object.save()

        if self.request.POST.has_key('_save_and_submit'):
            response = authorise_report(self.request, self.object)
            if response:
                return response

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireUpdateView, self).get_context_data(**kwargs)
        except:
            context = {}

        bushfire = self.get_object()
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        area_burnt_formset = None
        if self.request.POST.has_key('sss_create'):
            sss = json.loads( self.request.POST['sss_create'] )
            if sss.has_key('area') and sss['area'].has_key('total_area') and sss['area']['total_area'] > 0:
                area_burnt_formset = create_areas_burnt(None, sss['area']['layers'])

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=bushfire, prefix='area_burnt_fs')

        injury_formset = InjuryFormSet(instance=bushfire, prefix='injury_fs')
        damage_formset = DamageFormSet(instance=bushfire, prefix='damage_fs')

        # Determine if form template should be rean-only or editable (is_authorised=True --> read-only)
        if is_external_user(self.request.user) or self.request.POST.get('authorise_final') or self.request.POST.has_key('submit_initial'):
            # Display both reports readonly
            is_authorised = True
            is_init_authorised = True
            static = True
        else:
            # which url was clicked - initial or final
            if bushfire:
                if 'final' in self.request.get_full_path():
                    # rpt s/b editable for FSSDRS even after final authorisation
                    is_authorised = bushfire.is_final_authorised and not can_maintain_data(self.request.user)
                    is_init_authorised = True
                else:
                    is_authorised = True if bushfire.is_init_authorised else False
                    is_init_authorised = bushfire.is_init_authorised
            else:
                # create new bushfire
                is_authorised = False
                is_init_authorised = False

        if self.request.POST.has_key('sss_create'):
            # don't validate the form when initially displaying
            form.is_bound = False

        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'injury_formset': injury_formset,
                        'damage_formset': damage_formset,
                        'is_authorised': is_authorised, # If True, will make Report section of template read-only
                        'is_init_authorised': is_init_authorised, # If True, will make Notifications section of template read-only
                        'snapshot': bushfire,
                        'create': True if 'create' in self.request.get_full_path() else False,
                        'initial': True if 'initial' in self.request.get_full_path() else False,
                        'final': True if 'final' in self.request.get_full_path() else False,
                        'static': True if self.template_summary in self.get_template_names() else False,
                        'can_maintain_data': can_maintain_data(self.request.user),
                        'is_external_user': is_external_user(self.request.user),
                        'area_threshold': settings.AREA_THRESHOLD,
                        'sss_data': json.loads(self.request.POST.get('sss_create')) if self.request.POST.has_key('sss_create') else None, # needed since no object created yet
                        'sss_url': settings.SSS_URL,
			'test': [{'damage_type': 'Other Property', 'number': '1'}],
            })
        return context


class BushfireHistoryCompareView(HistoryCompareDetailView):
    """
    View for reversion_compare
    """
    model = Bushfire
    template_name = 'bfrs/history.html'



