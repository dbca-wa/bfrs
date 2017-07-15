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
        AreaBurntFormSet, InjuryFormSet, DamageFormSet, FireBehaviourFormSet,
    )
from bfrs.utils import (breadcrumbs_li,
        create_areas_burnt, update_areas_burnt, update_areas_burnt_fs, update_damage_fs, update_injury_fs, update_fire_behaviour_fs,
        export_final_csv, export_excel,
        update_status, serialize_bushfire,
        rdo_email, pvs_email, fpc_email, pica_email, pica_sms, police_email, dfes_email, fssdrs_email,
        invalidate_bushfire, is_external_user, can_maintain_data, refresh_gokart,
        authorise_report,
    )
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
from reversion_compare.views import HistoryCompareDetailView

import logging
logger = logging.getLogger(__name__)


class BooleanFilter(django_filters.filters.Filter):
    field_class = forms.BooleanField


class BushfireFilter(django_filters.FilterSet):

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

    def filter_report_status(self, queryset, name, value):
        if int(value) == Bushfire.STATUS_MISSING_FINAL:
            return queryset.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
        return queryset.filter(report_status=value)

    def filter_fire_number(self, queryset, name, value):
        """ Works because 'fire_number' present in self.data (from <input> field in base.html) """
        return queryset.filter(Q(fire_number__icontains=value) | Q(name=value))


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

        # allows dynamic update of the filter set, on page refresh
        self.filters['year'].extra['choices'] = [[None, '---------']] + [[i['year'], str(i['year']) + '/' + str(i['year']+1)] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]
        self.filters['reporting_year'].extra['choices'] = [[None, '---------']] + [[i['reporting_year'], str(i['reporting_year']) + '/' + str(i['reporting_year']+1)] for i in Bushfire.objects.all().values('reporting_year').distinct().order_by('reporting_year')]
        if not can_maintain_data(self.request.user):
            # pop the 'Reviewed' option
            self.filters['report_status'].extra['choices'] = [(u'', '---------'), (1, 'Initial'), (2, 'Initial Authorised'), (3, 'Final Authorised'), (5, 'Invalidated'), (6, 'Missing Final')]


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


from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
class BushfireView(LoginRequiredMixin, filter_views.FilterView):
#class BushfireView(LoginRequiredMixin, generic.ListView):
    #model = Bushfire
    filterset_class = BushfireFilter
    template_name = 'bfrs/bushfire.html'
    paginate_by = 5

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
        response = super(BushfireView, self).get(request, *args, **kwargs)
        template_confirm = 'bfrs/confirm.html'
        #template_mandatory = 'bfrs/mandatory_fields.html'
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

        #import ipdb; ipdb.set_trace()
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
#            if action == 'mark_reviewed':
#                context = self.get_context_data()
#                context['action'] = action
#                context['is_authorised'] = True
#                context['snapshot'] = bushfire
#                context['object'] = bushfire
#                context['review'] = True
#
#                fields = AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND if bushfire.fire_not_found else AUTH_MANDATORY_FIELDS
#                context['mandatory_fields'] = check_mandatory_fields(bushfire, fields, AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_FORMSETS)
#
#                if context['mandatory_fields']:
#                    return TemplateResponse(request, template_mandatory, context=context)
#
#                return TemplateResponse(request, template_final, context=context) # --> redirects to review the final report for confirmation


            return TemplateResponse(request, template_confirm, context={'action': action, 'bushfire_id': bushfire.id})

        return response

    def post(self, request, *args, **kwargs):
        #import ipdb; ipdb.set_trace()

        if self.request.POST.has_key('bushfire_id'):
            bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))

        if self.request.POST.has_key('action'):
            action = self.request.POST.get('action')

            if action == 'mark_reviewed' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                update_status(self.request, bushfire, action)
                return HttpResponseRedirect(self.get_success_url())

            # Delete Final Authorisation
            elif action == 'delete_final_authorisation' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.authorised_by = None
                bushfire.authorised_date = None
                #bushfire.final_snapshot = None
                bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
                serialize_bushfire(action, action, bushfire)

#            # Delete Reviewed
#            elif action == 'delete_reviewed' and bushfire.report_status==Bushfire.STATUS_REVIEWED:
#                bushfire.reviewed_by = None
#                bushfire.reviewed_date = None
#                bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
#                serialize_bushfire(action, action, bushfire)

            # Archive
            elif action == 'archive' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.archive = True
            elif action == 'unarchive' and bushfire.archive:
                bushfire.archive = False

            bushfire.save()

#        request.session['refreshGokart'] = True
#        request.session['region'] = 'null'
#        request.session['district'] = 'null'
#        request.session['id'] = self.object.fire_number
#        request.session['action'] = "update"
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
            initial.update({'include_archived': self.request.GET['include_archived']})

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

#        self.request.session['refreshGokart'] = True
#        self.request.session['region'] = 'null'
#        self.request.session['district'] = 'null'
#        self.request.session['id'] = ""
#        self.request.session['action'] = "update"
        refresh_gokart(self.request) #, fire_number="") #, region=None, district=None, action='update')

        return context

class BushfireInitialSnapshotView(LoginRequiredMixin, generic.DetailView):

    model = Bushfire
    template_name = 'bfrs/detail_summary.html'

#    def post(self, request, *args, **kwargs):
#        import ipdb; ipdb.set_trace()
#        self.object = self.get_object()
#
#        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super(BushfireInitialSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()
        #import ipdb; ipdb.set_trace()

        context.update({
            'initial': True,
            'snapshot': self.object.initial_snapshot.bushfire,
            'damages': self.object.initial_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL),
            'injuries': self.object.initial_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL),
            'fire_behaviour': self.object.initial_snapshot.fire_behaviour_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL),
            'tenures_burnt': self.object.initial_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_FINAL).order_by('id'),
        })
        return context


class BushfireFinalSnapshotView(LoginRequiredMixin, generic.DetailView):

    model = Bushfire
    template_name = 'bfrs/detail_summary.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireFinalSnapshotView, self).get_context_data(**kwargs)
        self.object = self.get_object()
        #import ipdb; ipdb.set_trace()

        context.update({
            'final': True,
            'snapshot': self.object.final_snapshot.bushfire,
            'damages': self.object.final_snapshot.damage_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL),
            'injuries': self.object.final_snapshot.injury_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL),
            'fire_behaviour': self.object.final_snapshot.fire_behaviour_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL),
            'tenures_burnt': self.object.final_snapshot.tenures_burnt_snapshot.exclude(snapshot_type=SNAPSHOT_INITIAL).order_by('id'),
        })
        return context


@method_decorator(csrf_exempt, name='dispatch')
class BushfireUpdateView(LoginRequiredMixin, UpdateView):
    """ Class will Create a new Bushfire and Update an existing Bushfire object"""

    model = Bushfire
    form_class = BushfireUpdateForm
    template_name = 'bfrs/detail.html'
    template_summary = 'bfrs/detail_summary.html'
    #template_name = 'bfrs/basic.html'

    def get_template_names(self):
        #import ipdb; ipdb.set_trace()
        obj = self.get_object()
        if is_external_user(self.request.user):
            return [self.template_summary]
        elif 'initial' in self.request.get_full_path() and obj.is_init_authorised:
            return [self.template_summary]
        elif 'final' in self.request.get_full_path() and obj.is_final_authorised:
            return [self.template_summary]
        return super(BushfireUpdateView, self).get_template_names()

    def get_success_url(self):
        return reverse("home")

    def get_initial(self):

        initial = {}
        if self.get_object(): #hasattr(self, 'object') and self.object:
            # if updating object ...
            initial['hours'] = self.object.time_to_control_hours_part if self.object.time_to_control_hours_part > 0 else ''
            initial['days']  = self.object.time_to_control_days_part if self.object.time_to_control_days_part > 0 else ''
        else:
            # if creating object ...
            profile, created = Profile.objects.get_or_create(user=self.request.user)
            initial['region'] = profile.region
            initial['district'] = profile.district


        if self.request.POST.has_key('sss_create'):
            sss = json.loads(self.request.POST.get('sss_create'))
            initial['sss_data'] = self.request.POST.get('sss_create')

            if sss.has_key('area') and sss['area'].has_key('total_area') and sss['area'].get('total_area'):
                initial['initial_area'] = round(float(sss['area']['total_area']), 2)

            if sss.has_key('origin_point') and isinstance(sss['origin_point'], list):
                initial['origin_point_str'] = Point(sss['origin_point']).get_coords()
                initial['origin_point'] = Point(sss['origin_point'])

            if sss.has_key('fire_boundary') and isinstance(sss['fire_boundary'], list):
                initial['fire_boundary'] = MultiPolygon([Polygon(*p) for p in sss['fire_boundary']])

            if sss.has_key('fire_position') and sss.get('fire_position'):
                initial['fire_position'] = sss['fire_position']

            if sss.has_key('tenure_ignition_point') and sss['tenure_ignition_point'] and \
                sss['tenure_ignition_point'].has_key('category') and sss['tenure_ignition_point']['category']:
                try:
                    initial['tenure'] = Tenure.objects.get(name__istartswith=sss['tenure_ignition_point']['category'])
                except:
                    #initial['tenure'] = Tenure.objects.get(name__istartswith='other')
                    initial['tenure'] = Tenure.objects.get(name='Other')
            else:
                initial['tenure'] = Tenure.objects.get(name='Other')

            if sss.has_key('region_id') and sss.has_key('district_id') and sss.get('district_id'):
                initial['region'] = Region.objects.get(id=sss['region_id'])
                initial['district'] = District.objects.get(id=sss['district_id'])

        # below for testing
        initial['origin_point'] = GEOSGeometry(Point(122.45, -33.15))
        initial['region'] = 1
        initial['district'] = 1

        return initial

    def get(self, request, *args, **kwargs):
        #import ipdb; ipdb.set_trace()
        if not self.get_object() and is_external_user(self.request.user):
            # external user cannot create bushfire
            return TemplateResponse(request, 'bfrs/error.html', context={'is_external_user': True, 'status':401}, status=401)

        return super(BushfireUpdateView, self).get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """ Overriding this method to allow UpdateView to both Create new object and Update an existing object"""
        if not self.kwargs.get(self.pk_url_kwarg):
            return None
        return super(BushfireUpdateView, self).get_object(queryset)

    def post(self, request, *args, **kwargs):
        #import ipdb; ipdb.set_trace()

        if self.request.POST.has_key('sss_create'):
            return self.render_to_response(self.get_context_data())

        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        #import ipdb; ipdb.set_trace()
        if self.request.POST.has_key('action'): # and 'create' not in self.request.get_full_path():
            # the 'initial_submit' already cleaned and saved the form, no need to save again
            # we are here because the redirected page confirmed this action
            action = self.request.POST.get('action')
            if action == 'Submit' or action == 'Authorise':
                update_status(self.request, self.object, action)
                return HttpResponseRedirect(self.get_success_url())

        """ _________________________________________________________________________________________________________________
        This Section used if district is changed from within the bushfire reporting system (FSSDRS Group can do this)
        Second use case is to update the district from SSS, which then executes the equiv code below from bfrs/api.py
        """
        if self.object:
            cur_obj = Bushfire.objects.get(id=self.object.id)
            district = District.objects.get(id=request.POST['district']) if request.POST.has_key('district') else None # get the district from the form
            if self.request.POST.has_key('action') and self.request.POST.get('action')=='invalidate' and cur_obj.report_status!=Bushfire.STATUS_INVALIDATED:
                self.object.invalid_details = self.request.POST.get('invalid_details')
                self.object.save()
                self.object = invalidate_bushfire(self.object, district, request.user)
                #url_name = 'bushfire_initial' if self.object.report_status < Bushfire.STATUS_INITIAL_AUTHORISED else 'bushfire_final'
                #return  HttpResponseRedirect(reverse('bushfire:' + url_name, kwargs={'pk': self.object.id}))
                return HttpResponseRedirect(self.get_success_url())

            elif district != cur_obj.district and not self.request.POST.has_key('fire_not_found'):
                if cur_obj.fire_not_found and form.is_valid():
                    # logic below to save object, present to allow final form change from fire_not_found=True --> to fire_not_found=False. Will allow correct fire_number invalidation
                    self.object = form.save(commit=False)
                    self.object.modifier = request.user
                    self.object.region = cur_obj.region # this will allow invalidate_bushfire() to invalidate and create the links as necessary
                    self.object.district = cur_obj.district
                    self.object.fire_number = cur_obj.fire_number
                    self.object.save()

                message = 'District has changed (from {} to {}). This action will invalidate the existing bushfire and create  a new bushfire with the new district, and a new fire number.'.format(
                    cur_obj.district.name,
                    district.name
                )
                context={
                    'action': 'invalidate',
                    'district': district.id,
                    'message': message,
                }
                return TemplateResponse(request, 'bfrs/confirm.html', context=context)
        """ _________________________________________________________________________________________________________________ """

        injury_formset          = InjuryFormSet(self.request.POST, prefix='injury_fs')
        damage_formset          = DamageFormSet(self.request.POST, prefix='damage_fs')

        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        fire_behaviour_formset  = FireBehaviourFormSet(self.request.POST, prefix='fire_behaviour_fs')

        #import ipdb; ipdb.set_trace()
        if form.is_valid():
#            if (self.request.POST.has_key('submit_initial') and self.request.POST.get('submit_initial')) or (self.request.POST.has_key('authorise_final') and self.request.POST.get('authorise_final')):
#                return self.form_valid(request, form, damage_formset)

            if form.cleaned_data['fire_not_found']:
                return self.form_valid(request, form)

            #import ipdb; ipdb.set_trace()
            if fire_behaviour_formset.is_valid() and injury_formset.is_valid() and damage_formset.is_valid(): # No need to check area_burnt_formset since the fs is readonly
                return self.form_valid(request, form, fire_behaviour_formset, area_burnt_formset, injury_formset, damage_formset)
            else:
                return self.form_invalid(request, form, fire_behaviour_formset, area_burnt_formset, injury_formset, damage_formset)
        else:
            return self.form_invalid(request, form, fire_behaviour_formset, area_burnt_formset, injury_formset, damage_formset)


    def form_invalid(self, request, form, fire_behaviour_formset, area_burnt_formset, injury_formset, damage_formset):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'area_burnt_formset': area_burnt_formset})
        context.update({'fire_behaviour_formset': fire_behaviour_formset})
        context.update({'injury_formset': injury_formset})
        context.update({'damage_formset': damage_formset})
        return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, request, form, fire_behaviour_formset=None, area_burnt_formset=None, injury_formset=None, damage_formset=None):
        template_summary = 'bfrs/detail_summary.html'
        template_error = 'bfrs/error.html'
        #template_mandatory_fields = 'bfrs/mandatory_fields.html'

        #import ipdb; ipdb.set_trace()
        if is_external_user(request.user):
            return TemplateResponse(request, template_error, context={'is_external_user': True, 'status':401}, status=401)

        self.object = form.save(commit=False)
        if not hasattr(self.object, 'creator'):
            self.object.creator = request.user
        self.object.modifier = request.user

        # reset fields
        #import ipdb; ipdb.set_trace()
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
            #import ipdb; ipdb.set_trace()
            areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        fire_behaviour_updated = update_fire_behaviour_fs(self.object, fire_behaviour_formset)
        injury_updated = update_injury_fs(self.object, injury_formset)
        damage_updated = update_damage_fs(self.object, damage_formset)

        # append/update 'Other' areas_burnt
        if self.request.POST.has_key('private_area') and self.request.POST.has_key('other_crown_area'):
            if self.request.POST.get('private_area'):
                private_tenure = self.request.POST.get('private_tenure')
                private_area = self.request.POST.get('private_area')
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name=private_tenure), defaults={"area": private_area})

            if self.request.POST.get('other_crown_area'):
                other_crown_tenure = self.request.POST.get('other_crown_tenure')
                other_crown_area = self.request.POST.get('other_crown_area')
                self.object.tenures_burnt.update_or_create(tenure=Tenure.objects.get(name=other_crown_tenure), defaults={"area": other_crown_area})

        # This section to Submit/Authorise report, placed here to allow any changes to be cleaned and saved first - effectively the 'Submit' btn is a 'save and submit'
        if self.request.POST.has_key('submit_initial') or self.request.POST.has_key('authorise_final'):
            response = authorise_report(self.request, self.object)
            if response:
                return response


#        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
#        # This section to Submit initial report, placed here to allow any changes to be cleaned and saved first - effectively the 'Submit' btn is a 'save and submit'
#        if self.request.POST.has_key('submit_initial'):
#            #import ipdb; ipdb.set_trace()
#            action = self.request.POST.get('submit_initial')
#            if action == 'Submit':
#                #context = self.get_context_data()
#                context = {
#                    'action': action,
#                    'is_authorised': True,
#                    'initial': True,
#                    'object': self.object,
#                    'snapshot': self.object,
#                    'damages': self.object.damages,
#                    'injuries': self.object.injuries,
#                    'fire_behaviour': self.object.fire_behaviour,
#                    'tenures_burnt': self.object.tenures_burnt.order_by('id'),
#                }
#
#                context['mandatory_fields'] = check_mandatory_fields(self.object, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS)
#
#                if context['mandatory_fields']:
#                    return TemplateResponse(request, template_mandatory_fields, context=context)
#
#                return TemplateResponse(request, template_summary, context=context)
#
#        # This section to Authorise Final report, placed here to allow any changes to be cleaned and saved first - effectively the 'Authorise' btn is a 'save and submit'
#        if self.request.POST.has_key('authorise_final'):
#            action = self.request.POST.get('authorise_final')
#            if action == 'Authorise':
#                context = {
#                    'action': action,
#                    'is_authorised': True,
#                    'final': True,
#                    'object': self.object,
#                    'snapshot': self.object,
#                    'damages': self.object.damages,
#                    'injuries': self.object.injuries,
#                    'fire_behaviour': self.object.fire_behaviour,
#                    'tenures_burnt': self.object.tenures_burnt.order_by('id'),
#                }
#
#                fields = AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND if self.object.fire_not_found else AUTH_MANDATORY_FIELDS
#                context['mandatory_fields'] = check_mandatory_fields(self.object, fields, AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_FORMSETS)
#
#                if context['mandatory_fields']:
#                    return TemplateResponse(request, template_mandatory_fields, context=context)
#
#                return TemplateResponse(request, template_summary, context=context)

        if self.object.report_status >=  Bushfire.STATUS_FINAL_AUTHORISED:
            # if bushfire has been authorised, update snapshot and archive old snapshot
            # That is, if FSSDRS group update the final report after it has been authorised, we archive the existing data
            try:
                serialize_bushfire('final', action, self.object)
            except NameError:
                # update is occuring after report has already been authorised (action is undefined) - ie. it is being Reviewed by FSSDRS
                serialize_bushfire('final', 'Review', self.object)

#        request.session['refreshGokart'] = True
#        request.session['region'] = self.object.region.id
#        request.session['district'] = self.object.district.id
#        request.session['id'] = self.object.fire_number
#        request.session['action'] = "update"
        refresh_gokart(request, fire_number=self.object.fire_number, region=self.object.region.id, district=self.object.district.id)

        self.object.save()

        if self.request.POST.has_key('_save_continue'):
            return HttpResponseRedirect(
                reverse("bushfire:bushfire_initial", kwargs={'pk': self.object.id})
            )

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
            if sss.has_key('area') and sss['area'].has_key('tenure_area') and sss['area']['tenure_area'].has_key('areas') and sss['area']['tenure_area']['areas']:
                area_burnt_formset = create_areas_burnt(None, sss['area']['tenure_area']['areas'])

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=bushfire, prefix='area_burnt_fs')

        fire_behaviour_formset = FireBehaviourFormSet(instance=bushfire, prefix='fire_behaviour_fs')
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

        #import ipdb; ipdb.set_trace()
        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'fire_behaviour_formset': fire_behaviour_formset,
                        'injury_formset': injury_formset,
                        'damage_formset': damage_formset,
                        'is_authorised': is_authorised, # If True, will make Report section of template read-only
                        'is_init_authorised': is_init_authorised, # If True, will make Notifications section of template read-only
                        'snapshot': bushfire.initial_snapshot if 'final' in self.request.get_full_path() else bushfire, #snapshot,
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
        #import ipdb; ipdb.set_trace()
        return context


class BushfireHistoryCompareView(HistoryCompareDetailView):
    """
    View for reversion_compare
    """
    model = Bushfire
    template_name = 'bfrs/history.html'



