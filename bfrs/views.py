from django.http import HttpResponse, HttpResponseRedirect
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

from bfrs.models import (Profile, Bushfire,
        Region, District,
        Tenure, AreaBurnt,
        SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS,
        AUTH_MANDATORY_FIELDS, AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_FORMSETS,
        check_mandatory_fields,
    )
from bfrs.forms import (ProfileForm, BushfireFilterForm, BushfireForm, BushfireCreateForm, BushfireInitUpdateForm,
        AreaBurntFormSet, InjuryFormSet, DamageFormSet, FireBehaviourFormSet,
    )
from bfrs.utils import (breadcrumbs_li,
        update_areas_burnt, update_areas_burnt_fs, create_areas_burnt, update_damage_fs, update_injury_fs, update_fire_behaviour_fs,
        export_final_csv, export_excel,
        update_status, serialize_bushfire, deserialize_bushfire,
        rdo_email, pvs_email, fpc_email, pica_email, pica_sms, police_email, dfes_email, fssdrs_email,
        invalidate_bushfire,
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

    @property
    def fssdrs_group(self):
        return Group.objects.get(name='FSS Datasets and Reporting Services')

    @property
    def external_user_group(self):
        return Group.objects.get(name='External Users')

    @property
    def can_maintain_data(self):
        return self.fssdrs_group in self.request.user.groups.all()

    @property
    def is_external_user(self):
        return self.external_user_group in self.request.user.groups.all()


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
        template_mandatory = 'bfrs/mandatory_fields.html'
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

        if self.request.GET.has_key('action'):
            action = self.request.GET.get('action')
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            if action == 'snapshot_history':
                context = {
                    'object': bushfire,
                }
                return TemplateResponse(request, template_snapshot_history, context=context)


        #import ipdb; ipdb.set_trace()
        if self.request.GET.has_key('confirm_action'):
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            action = self.request.GET.get('confirm_action')
            if action == 'mark_reviewed':
                context = self.get_context_data()
                context['action'] = action
                context['is_authorised'] = True
                context['snapshot'] = bushfire
                context['object'] = bushfire
                context['review'] = True

                context['mandatory_fields'] = check_mandatory_fields(bushfire, AUTH_MANDATORY_FIELDS, AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_FORMSETS)

                if context['mandatory_fields']:
                    return TemplateResponse(request, template_mandatory, context=context)

                return TemplateResponse(request, template_final, context=context) # --> redirects to review the final report for confirmation


            return TemplateResponse(request, template_confirm, context={'action': action, 'bushfire_id': bushfire.id})

        return response

    def post(self, request, *args, **kwargs):

        if self.request.POST.has_key('bushfire_id'):
            bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))

        if self.request.POST.has_key('action'):
            action = self.request.POST.get('action')

            if action == 'mark_reviewed' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                update_status(self.request, bushfire, action)
                return HttpResponseRedirect(self.get_success_url())

            # Delete Final Authorisation
            if action == 'delete_final_authorisation' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.authorised_by = None
                bushfire.authorised_date = None
                bushfire.final_snapshot = None
                bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
                serialize_bushfire(action, action, bushfire)

            # Delete Reviewed
            if action == 'delete_reviewed' and bushfire.report_status==Bushfire.STATUS_REVIEWED:
                bushfire.reviewed_by = None
                bushfire.reviewed_date = None
                bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
                serialize_bushfire(action, action, bushfire)

            # Archive
            if action == 'archive' and bushfire.report_status==Bushfire.STATUS_REVIEWED:
                bushfire.archive = True
            if action == 'unarchive' and bushfire.archive:
                bushfire.archive = False

            bushfire.save()

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

        # update context with form - filter is already in the context
        context['form'] = BushfireFilterForm(initial=initial)
        context['object_list'] = self.object_list.order_by('-modified') # passed by default, but we are (possibly) updating, if profile exists!
        context['sss_url'] = settings.SSS_URL
        context['can_maintain_data'] = self.can_maintain_data
        context['is_external_user'] = self.is_external_user
        return context

@method_decorator(csrf_exempt, name='dispatch')
class BushfireCreateView(LoginRequiredMixin, generic.CreateView):
    model = Bushfire
    form_class = BushfireCreateForm
    template_name = 'bfrs/detail.html'

    def get_success_url(self):
        return reverse("home")

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        initial = {'region': profile.region, 'district': profile.district}

        if self.request.POST.has_key('sss_create'):
            sss = json.loads(self.request.POST.get('sss_create'))
            initial['sss_data'] = self.request.POST.get('sss_create')

            if sss.has_key('area') and sss['area'].has_key('total_area') and sss['area'].get('total_area'):
                initial['area'] = round(float(sss['area']['total_area']), 2)

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
                    initial['tenure'] = Tenure.objects.get(name__istartswith='other')
            else:
                initial['tenure'] = Tenure.objects.get(name__istartswith='other')

            if sss.has_key('region_id') and sss.has_key('district_id') and sss.get('district_id'):
                initial['region'] = Region.objects.get(id=sss['region_id'])
                initial['district'] = District.objects.get(id=sss['district_id'])

        return initial

    from django.http import JsonResponse
    def get(self, request, *args, **kwargs):
#        area = None
#	if self.request.GET.has_key('area'): # and eval(self.request.GET.get('area')) > 0:
#            #area = round(eval(self.request.GET.get('area')), 1)
#            data = {'area': 10}
#            return self.JsonResponse(data)

        return super(BushfireCreateView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.request.POST.has_key('sss_create'):
            return self.render_to_response(self.get_context_data())

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        if self.request.POST.has_key('action') and self.request.POST.has_key('bushfire_id'):
            # the 'initial_submit' already cleaned and saved the form, no need to save again
            # we are here because the redirected page confirmed this action
            action = self.request.POST.get('action')
            bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))
            update_status(self.request, bushfire, action)
            return HttpResponseRedirect(self.get_success_url())

        fire_behaviour_formset      = FireBehaviourFormSet(self.request.POST, prefix='fire_behaviour_fs')

        # No need to check area_burnt_formset since the fs is hidden on the initial form and is created directly by the update_areas_burnt() method
        if form.is_valid() and fire_behaviour_formset.is_valid():
            return self.form_valid(request, form, fire_behaviour_formset, kwargs)
        else:
            return self.form_invalid(request, form, fire_behaviour_formset, kwargs)

    def form_invalid(self, request, form, fire_behaviour_formset, kwargs):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'fire_behaviour_formset': fire_behaviour_formset})
        return self.render_to_response(context)

    @transaction.atomic
    def form_valid(self, request, form, fire_behaviour_formset, kwargs):
        self.object = form.save(commit=False)
        self.object.creator = request.user #1 #User.objects.all()[0] #request.user
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user

        self.object.save()

        # allows to test without SSS - can create test tenures directly
#        tmp_list = [
#            {'area': 134.27019364961308,'category': u'Nature Reserve','id': 11805,'name': u'Marchagee Nature Reserve'},
#            {'area': 100.00,'category': u'Unallocated Crown Land - Dept Interest','id': 11805,'name': u'Marchagee Nature Reserve'},
#        ]
#        area_burnt_updated = update_areas_burnt(self.object, tmp_list)

        area_burnt_updated = None
        sss = self.object.sss_data_to_dict
        if sss and sss.has_key('area') and sss['area'].has_key('tenure_area') and sss['area']['tenure_area'].has_key('areas') and sss['area']['tenure_area']['areas']:
            area_burnt_updated = update_areas_burnt(self.object, sss['area']['tenure_area']['areas'])

        fire_behaviour_updated = update_fire_behaviour_fs(self.object, fire_behaviour_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if area_burnt_updated == 0:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        if not fire_behaviour_updated:
            messages.error(request, 'There was an error saving Fuel Behaviour.')
            return redirect_referrer

        # This section to Submit initial report, placed here to allow any changes to be cleaned and saved first - effectively the 'Submit' btn is a 'save and submit'
        if self.request.POST.has_key('submit_initial'):
            action = self.request.POST.get('submit_initial')
            if action == 'Submit':
                context = self.get_context_data()
                context['action'] = action
                context['is_authorised'] = True
                context['snapshot'] = self.object
                context['object'] = self.object
                context['initial'] = True

                context['mandatory_fields'] = check_mandatory_fields(self.object, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS)

                if context['mandatory_fields']:
                    return TemplateResponse(request, 'bfrs/mandatory_fields.html', context=context)

                return TemplateResponse(request, self.template_name, context=context)

	    request.session['refreshGokart'] = True
	    request.session['region'] = self.object.region.id
	    request.session['district'] = self.object.district.id
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireCreateView, self).get_context_data(**kwargs)
        except:
            context = {}

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        fire_behaviour_formset      = FireBehaviourFormSet(instance=None, prefix='fire_behaviour_fs')

        if self.request.POST.has_key('sss_create'):
            # don't validate the form when initially displaying
            form.is_bound = False

        context.update({'form': form,
                        'fire_behaviour_formset': fire_behaviour_formset,
                        'create': True,
                        'initial': True,
            })
        return context


class BushfireInitUpdateView(LoginRequiredMixin, UpdateView):
    model = Bushfire
    form_class = BushfireInitUpdateForm
    template_name = 'bfrs/detail.html'

    def get_success_url(self):
        return reverse("home")

#    def get(self, request, *args, **kwargs):
#        return super(BushfireInitUpdateView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        if self.request.POST.has_key('action'):
            # the 'initial_submit' already cleaned and saved the form, no need to save again
            # we are here because the redirected page confirmed this action
            action = self.request.POST.get('action')
            update_status(self.request, self.object, action)
            return HttpResponseRedirect(self.get_success_url())

        """ _________________________________________________________________________________________________________________
        This Section used if district is changed from within the bushfire reporting system
        However, actual use case is to update the district from SSS, which then executes the equiv code below from bfrs/api.py
        """
        cur_obj = Bushfire.objects.get(id=self.object.id)
        district = District.objects.get(id=request.POST['district']) if request.POST.has_key('district') else None # get the district from the form
        if self.request.POST.has_key('action') and self.request.POST.get('action')=='invalidate' and cur_obj.report_status!=Bushfire.STATUS_INVALIDATED:
            self.object.invalid_details = self.request.POST.get('invalid_details')
            self.object.save()
            self.object = invalidate_bushfire(self.object, district, request.user)
            url_name = 'bushfire_initial' if self.object.report_status <= Bushfire.STATUS_INITIAL_AUTHORISED else 'bushfire_final'
            return  HttpResponseRedirect(reverse('bushfire:' + url_name, kwargs={'pk': self.object.id}))

        elif district != cur_obj.district:
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


        if not self.request.POST.has_key('sss_create'):
            # FOR Testing outide SSS
            # redefine AreaBurnFormSet to require no formsets on initial form (since its hidden in the template)
            AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=0, validate_min=False, exclude=())
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        fire_behaviour_formset  = FireBehaviourFormSet(self.request.POST, prefix='fire_behaviour_fs')

        if form.is_valid() and fire_behaviour_formset.is_valid(): # No need to check area_burnt_formset since the fs is hidden on the initial form
            return self.form_valid(request, form, area_burnt_formset, fire_behaviour_formset)
        else:
            return self.form_invalid(request, form, area_burnt_formset, fire_behaviour_formset, kwargs)

    def form_invalid(self, request, form, area_burnt_formset, fire_behaviour_formset, wargs):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'area_burnt_formset': area_burnt_formset})
        context.update({'fire_behaviour_formset': fire_behaviour_formset})
        return self.render_to_response(context)

    def form_valid(self, request, form, area_burnt_formset, fire_behaviour_formset):
        self.object = form.save(commit=False)
        if not self.object.creator:
            self.object.creator = request.user
        self.object.modifier = request.user

        self.object.save()
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        fire_behaviour_updated = update_fire_behaviour_fs(self.object, fire_behaviour_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        if not fire_behaviour_updated:
            messages.error(request, 'There was an error saving Fuel Behaviour.')
            return redirect_referrer

        if self.request.POST.has_key('_save_continue'):
            return redirect_referrer

        # This section to Submit initial report, placed here to allow any changes to be cleaned and saved first - effectively the 'Submit' btn is a 'save and submit'
        if self.request.POST.has_key('submit_initial'):
            action = self.request.POST.get('submit_initial')
            if action == 'Submit':
                context = self.get_context_data()
                context['action'] = action
                context['is_authorised'] = True
                context['snapshot'] = self.object
                context['object'] = self.object
                context['initial'] = True

                context['mandatory_fields'] = check_mandatory_fields(self.object, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS)

                if context['mandatory_fields']:
                    return TemplateResponse(request, 'bfrs/mandatory_fields.html', context=context)

                return TemplateResponse(request, self.template_name, context=context)


        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireInitUpdateView, self).get_context_data(**kwargs)
        except:
            context = {}

        bushfire = Bushfire.objects.get(id=self.kwargs['pk'])
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        area_burnt_formset = None
        if self.request.POST.has_key('sss_create'):
            sss = json.loads( self.request.POST['sss_create'] )
            if sss.has_key('tenure_area') and sss['tenure_area']:
                area_burnt_formset = create_areas_burnt(None, sss['tenure_area'])

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        fire_behaviour_formset = FireBehaviourFormSet(instance=self.object, prefix='fire_behaviour_fs')

        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'fire_behaviour_formset': fire_behaviour_formset,
                        'is_authorised': bushfire.is_init_authorised,
                        'snapshot': deserialize_bushfire('initial', bushfire) if bushfire.initial_snapshot else None,
                        'initial': True,
            })
        return context


class BushfireFinalUpdateView(LoginRequiredMixin, UpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/final.html'

    @property
    def fssdrs_group(self):
        return Group.objects.get(name='FSS Datasets and Reporting Services')

    @property
    def external_user_group(self):
        return Group.objects.get(name='External Users')

    @property
    def can_maintain_data(self):
        return self.fssdrs_group in self.request.user.groups.all()

    @property
    def is_external_user(self):
        return self.external_user_group in self.request.user.groups.all()

    def get_initial(self):
        if self.object.time_to_control:
            return { 'days': self.object.time_to_control.days, 'hours': self.object.time_to_control.seconds/3600 }

    def get_success_url(self):
        return reverse("home")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        # Authorise the FINAL report
        if self.request.POST.has_key('action') and self.object.report_status==Bushfire.STATUS_INITIAL_AUTHORISED:
            action = self.request.POST.get('action')
            if action == 'Authorise':
                update_status(self.request, self.object, action)
                return HttpResponseRedirect(self.get_success_url())

        """ _________________________________________________________________________________________________________________

        This Section used if district is changed from within the bushfire reporting system
        Only FSSDRS Group can change district after it is STATUS_INITIAL_SUBMITTED

        """
        # Check if district is has changed and whether the record needs to be invalidated
        cur_obj = Bushfire.objects.get(id=self.object.id)
        district = District.objects.get(id=request.POST['district']) if request.POST.has_key('district') else None # get the district from the form

        if self.request.POST.has_key('action') and self.request.POST.get('action')=='invalidate' and cur_obj.report_status!=Bushfire.STATUS_INVALIDATED:
            self.object.invalid_details = self.request.POST.get('invalid_details')
            self.object.save()
            self.object = invalidate_bushfire(self.object, district, request.user)
            #url_name = 'bushfire_initial' if self.object.report_status <= Bushfire.STATUS_INITIAL_AUTHORISED else 'bushfire_final'
            url_name = 'bushfire_final'
            return  HttpResponseRedirect(reverse('bushfire:' + url_name, kwargs={'pk': self.object.id}))

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

        if not self.request.POST.has_key('sss_create'):
            # FOR Testing outide SSS
            # redefine AreaBurnFormSet to require no formsets on final form (since it is readonly in the template)
            AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=0, validate_min=False, exclude=())
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')


        if form.is_valid():
            if form.cleaned_data['fire_not_found']:
                return self.form_valid(request, form)

            if injury_formset.is_valid() and damage_formset.is_valid(): # No need to check area_burnt_formset since the fs is readonly on the final form
                return self.form_valid(request, form, area_burnt_formset, injury_formset, damage_formset)
            else:
                return self.form_invalid(request, form, area_burnt_formset, injury_formset, damage_formset)
        else:
            return self.form_invalid(request, form, area_burnt_formset, injury_formset, damage_formset)

    def form_invalid(self, request, form, area_burnt_formset, injury_formset, damage_formset):
        context = self.get_context_data()
        context.update({
            'form': form,
            'area_burnt_formset': area_burnt_formset,
            'injury_formset': injury_formset,
            'damage_formset': damage_formset,
        })
        return self.render_to_response(context=context)

    def form_valid(self, request, form, area_burnt_formset=None, injury_formset=None, damage_formset=None):
        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        self.object = form.save(commit=False)
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user
        self.object.save()
        action = None

        if area_burnt_formset:
            areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
            injury_updated = update_injury_fs(self.object, injury_formset)
            damage_updated = update_damage_fs(self.object, damage_formset)

            if not areas_burnt_updated:
                messages.error(request, 'There was an error saving Areas Burnt.')
                return redirect_referrer

            elif not injury_updated:
                messages.error(request, 'There was an error saving Injury.')
                return redirect_referrer

            elif not damage_updated:
                messages.error(request, 'There was an error saving Damage.')
                return redirect_referrer

        # This section to Authorise Final report, placed here to allow any changes to be cleaned and saved first - effectively the 'Authorise' btn is a 'save and submit'
        if self.request.POST.has_key('authorise_final'):
            action = self.request.POST.get('authorise_final')
            if action == 'Authorise':
                context = self.get_context_data()
                context['action'] = action
                context['is_authorised'] = True # False if request.user.is_superuser else True
                context['snapshot'] = self.object
                context['object'] = self.object
                context['final'] = True

                context['mandatory_fields'] = check_mandatory_fields(self.object, AUTH_MANDATORY_FIELDS, AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_FORMSETS)

                if context['mandatory_fields']:
                    return TemplateResponse(request, 'bfrs/mandatory_fields.html', context=context)

                return TemplateResponse(request, self.template_name, context=context)

        if self.object.report_status >=  Bushfire.STATUS_FINAL_AUTHORISED:
            # if bushfire has been authorised, update snapshot and archive old snapshot
            # That is, if FSSDRS group update the final report after it has been authorised, we archive the existing data
            serialize_bushfire('final', action, self.object)

        return HttpResponseRedirect(self.get_success_url())


    def get_context_data(self, **kwargs):
        context = super(BushfireFinalUpdateView, self).get_context_data(**kwargs)

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        injury_formset  = InjuryFormSet(instance=self.object, prefix='injury_fs')
        damage_formset   = DamageFormSet(instance=self.object, prefix='damage_fs')

        area_burnt_formset = None
        if self.request.POST.has_key('sss_create'):
            sss = json.loads( self.request.POST['sss_create'] )
            if sss.has_key('tenure_area') and sss['tenure_area']:
                area_burnt_formset = create_areas_burnt(None, sss['tenure_area'])

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')

        #import ipdb; ipdb.set_trace()
        if self.can_maintain_data: # or self.request.user.is_superuser:
            is_authorised = False
        elif self.is_external_user:
            is_authorised = True # template will display non-editable text
        else:
            is_authorised = self.object.is_final_authorised

        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'injury_formset': injury_formset,
                        'damage_formset': damage_formset,
                        'is_authorised': is_authorised,
                        'snapshot': deserialize_bushfire('final', self.object) if self.object.final_snapshot else None, #bushfire.snapshot,
                        'final': True,
                        'can_maintain_data': self.can_maintain_data,
            })
        return context

class BushfireReviewUpdateView(BushfireFinalUpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/final.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireReviewUpdateView, self).get_context_data(**kwargs)

        context.update({
             'review': True,
        })
        return context




