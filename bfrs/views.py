from django.http import HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.core.urlresolvers import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, FormView
#from django.views.generic import CreateView
from django.forms.formsets import formset_factory
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException
#from django.template import RequestContext
#from django.shortcuts import render
from django.core import serializers
from django import forms
from django.contrib.gis.db import models

from bfrs.models import (Profile, Bushfire,
        Region, District,
        Tenure, AreaBurnt,
    )
from bfrs.forms import (ProfileForm, BushfireFilterForm, BushfireForm, BushfireCreateForm, BushfireInitUpdateForm,
        AreaBurntFormSet, InjuryFormSet, DamageFormSet,
    )
from bfrs.utils import (breadcrumbs_li,
        update_areas_burnt_fs, update_areas_burnt, update_damage_fs, update_injury_fs,
        export_final_csv, export_excel,
        serialize_bushfire, deserialize_bushfire,
        rdo_email, pvs_email, pica_email, pica_sms, police_email, dfes_email, fssdrs_email,
        #calc_coords,
    )
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.forms import ValidationError
from datetime import datetime
import pytz
import json
from django.utils.dateparse import parse_duration

import django_filters
#from  django_filters import FilterSet
from django_filters import views as filter_views
from django_filters.widgets import BooleanWidget


class BooleanFilter(django_filters.filters.Filter):
    field_class = forms.BooleanField


class BushfireFilter(django_filters.FilterSet):

    YEAR_CHOICES = [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct()]

    REGION_CHOICES = []
    for region in Region.objects.distinct('name'):
        REGION_CHOICES.append([region.id, region.name])

    DISTRICT_CHOICES = []
    for district in District.objects.distinct('name'):
        DISTRICT_CHOICES.append([district.id, district.name])

    ARCHIVE_CHOICES = [
        #['', 'All'],
        [None, 'Unarchived'],
        [False, 'All'],
        [True, 'Archived'],
    ]

    region = django_filters.ChoiceFilter(choices=REGION_CHOICES, label='Region')
    district = django_filters.ChoiceFilter(choices=DISTRICT_CHOICES, label='District')
    year = django_filters.ChoiceFilter(choices=YEAR_CHOICES, label='Year')
    report_status = django_filters.ChoiceFilter(choices=Bushfire.REPORT_STATUS_CHOICES, label='Report Status')
    #archive = django_filters.ChoiceFilter(choices=ARCHIVE_CHOICES, label='Archive Status')
    #archive = django_filters.BooleanFilter(widget=forms.CheckboxInput, label='Included archived')
    #archive = django_filters.BooleanFilter(label='Included archived')
    include_archived = BooleanFilter(name='archive', label='Include archived')

    class Meta:
        model = Bushfire
        fields = [
            'region_id',
            'district_id',
            'year',
            'report_status',
            'include_archived',
        ]
        order_by = (
            ('region_id', 'Region'),
            ('district_id', 'District'),
            ('year', 'Year'),
            ('report_status', 'Report Status'),
            ('include_archived', 'Include Archived'),
        )
#        filter_overrides = {
#            models.BooleanField: {
#                'filter_class': django_filters.BooleanFilter,
#                'extra': lambda f: {
#                    'widget': forms.CheckboxInput,
#                },
#            },
#        }

    def __init__(self, *args, **kwargs):
        super(BushfireFilter, self).__init__(*args, **kwargs)

        # allows dynamic update of the filter set, on page refresh
        self.filters['year'].extra['choices'] = [[None, '---------']] + [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]
        #self.filters['archive'].extra['choices'] =  [(False, '---------'), ['', 'All'], [True, 'Archived']]
        #import ipdb; ipdb.set_trace()


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

    def get_success_url(self):
        return reverse('main')

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def get(self, request, *args, **kwargs):
        response = super(BushfireView, self).get(request, *args, **kwargs)
        template_confirm = 'bfrs/confirm.html'
        template_preview = 'bfrs/detail.html'

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

        if self.request.GET.has_key('confirm_action'):
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))
            action = self.request.GET.get('confirm_action')
            if action == 'submit_initial' or action == 'authorise_final':
                context = self.get_context_data()
                context['action'] = action
                context['is_authorised'] = True
                context['snapshot'] = bushfire
                if action == 'submit_initial':
                    context['initial'] = True
                else:
                    context['final'] = True
                return TemplateResponse(request, template_preview, context=context)
            return TemplateResponse(request, template_confirm, context={'action': action, 'bushfire_id': bushfire.id})

        return response

    def post(self, request, *args, **kwargs):

        #import ipdb; ipdb.set_trace()
        if self.request.POST.has_key('bushfire_id'):
            bushfire = Bushfire.objects.get(id=self.request.POST.get('bushfire_id'))

        if self.request.POST.has_key('action'):
            action = self.request.POST.get('action')

            if action == 'submit_initial' and bushfire.report_status==Bushfire.STATUS_INITIAL:
                bushfire.init_authorised_by = self.request.user
                bushfire.init_authorised_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
                serialize_bushfire('initial', bushfire)

                # send emails
                rdo_email(bushfire, self.mail_url(bushfire))
                dfes_email(bushfire, self.mail_url(bushfire))
                if bushfire.park_trail_impacted:
                    pvs_email(bushfire, self.mail_url(bushfire))
                if bushfire.media_alert_req:
                    pica_email(bushfire, self.mail_url(bushfire))
                    pica_sms(bushfire, self.mail_url(bushfire))
                if bushfire.investigation_req:
                    police_email(bushfire, self.mail_url(bushfire))

            # CREATE the FINAL DRAFT report
            if action == 'create_final' and bushfire.report_status==Bushfire.STATUS_INITIAL_AUTHORISED:
                bushfire.report_status = Bushfire.STATUS_FINAL_DRAFT

            # Authorise the FINAL report
            if action == 'authorise_final' and bushfire.report_status==Bushfire.STATUS_FINAL_DRAFT:
                bushfire.authorised_by = self.request.user
                bushfire.authorised_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
                serialize_bushfire('final', bushfire)

                # send emails
                fssdrs_email(bushfire, self.mail_url(bushfire, status='final'))

            # CREATE the REVIEWABLE DRAFT report
            if action == 'create_review' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.report_status = Bushfire.STATUS_REVIEW_DRAFT

            # Authorise the REVIEW DRAFT report
            if action == 'mark_reviewed' and bushfire.report_status==Bushfire.STATUS_REVIEW_DRAFT:
                bushfire.reviewed_by = self.request.user
                bushfire.reviewed_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_REVIEWED

            # Delete Initial
            if action == 'delete_initial' and bushfire.report_status==Bushfire.STATUS_INITIAL:
                #Bushfire.objects.filter(id=bushfire.id).delete()
                bushfire.delete()
                return HttpResponseRedirect(self.get_success_url())

            # Delete Final Authorisation
            if action == 'delete_final_authorisation' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.authorised_by = None
                bushfire.authorised_date = None
                bushfire.report_status = Bushfire.STATUS_FINAL_DRAFT

            # Archive
            if action == 'archive' and bushfire.report_status==Bushfire.STATUS_REVIEWED:
                bushfire.archive = True
            if action == 'unarchive' and bushfire.archive:
                bushfire.archive = False

#            if not action.startswith('delete'):
#                bushfire.save()
            bushfire.save()

        return HttpResponseRedirect(self.get_success_url())


            # Authorise the INITIAL report

    def get_context_data(self, **kwargs):
        context = super(BushfireView, self).get_context_data(**kwargs)
        #import ipdb; ipdb.set_trace()

        # initial parameter prevents the form from resetting, if the region and district filters had a value set previously

	# TODO this can be moved to the get method
        initial = {}
        profile = self.get_initial() # Additional profile Filters must also be added to the JS in bushfire.html- profile_field_list
        if self.request.GET.has_key('region'):
            initial.update({'region': self.request.GET['region']})
            #self.object_list = self.object_list.filter(region=self.request.GET['region'])
        elif profile['region']:
            initial.update({'region': profile['region'].id})
            self.object_list = self.object_list.filter(region=profile['region'])

        if self.request.GET.has_key('district'):
            initial.update({'district': self.request.GET['district']})
            #self.object_list = self.object_list.filter(district=self.request.GET[''])
        elif profile['district']:
            initial.update({'district': profile['district'].id})
            self.object_list = self.object_list.filter(district=profile['district'])

        if not self.request.GET.has_key('include_archived'):
            self.object_list = self.object_list.exclude(archive=True)
	else:
            initial.update({'include_archived': self.request.GET['include_archived']})

        # update context with form - filter is already in the context
        context['form'] = BushfireFilterForm(initial=initial)
        context['object_list'] = self.object_list.order_by('id') # passed by default, but we are (possibly) updating, if profile exists!
        return context

    def mail_url(self, bushfire, status='initial'):
	if status == 'initial':
            return "http://" + self.request.get_host() + reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id})
	if status == 'final':
            return "http://" + self.request.get_host() + reverse('bushfire:bushfire_final', kwargs={'pk':bushfire.id})

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

#        import ipdb; ipdb.set_trace()
        #tmp = '{"origin_point":[117.30008118682615,-30.849007786590157],"fire_boundary":[[[[117.29201309106732,-30.850896064320946],[117.30179780294505,-30.866002286167266],[117.30832094419686,-30.840081382771874],[117.29201309106732,-30.850896064320946]]],[[[117.31518740867246,-30.867032255838605],[117.3213672267005,-30.858277513632217],[117.34299658979864,-30.874413705149877],[117.31175417643466,-30.87733195255201],[117.31518740867246,-30.867032255838605]]]],"area":5068734.391653851,"sss_id":"6d09d9ce023e4dd3361ba125dfe1f9db"}'
        #sss = json.loads(tmp)
        if self.request.POST.has_key('sss_create'):
            sss = json.loads(self.request.POST.get('sss_create'))
            if sss.has_key('area'):
                initial['area'] = float(sss['area'])

            if sss.has_key('sss_id'):
                initial['sss_id'] = sss['sss_id']

            if sss.has_key('origin_point') and isinstance(sss['origin_point'], list):
                initial['origin_point_str'] = Point(sss['origin_point']).get_coords()
                initial['origin_point'] = Point(sss['origin_point'])

            if sss.has_key('fire_boundary') and isinstance(sss['fire_boundary'], list):
                initial['fire_boundary'] = MultiPolygon([Polygon(p[0]) for p in sss['fire_boundary']])

            if sss.has_key('fire_position'):
                initial['fire_position'] = sss['fire_position']

            #if sss.has_key('tenure_ignition_point') and sss['tenure_ignition_point'].has_key('category'):
            if sss.has_key('tenure_iginition_point') and sss['tenure_iginition_point'].has_key('category'):
                try:
                    tenure = Tenure.objects.get(name__icontains=sss['tenure_ignition_point']['category'])
                except:
                    tenure = Tenure.objects.get(name__icontains='other')
                initial['tenure'] = tenure



            #import ipdb; ipdb.set_trace()
#            if sss.has_key('tenure_area'):
#                self.area_burnt_list = sss['tenure_area']

#            if sss.has_key('tenure_area') and hasattr(self, 'object'):
#                self.area_burnt_list = sss['tenure_area']
#                update_areas_burnt(self.object, self.area_burnt_list)

#            if sss.has_key('fire_boundary') and isinstance(sss['fire_boundary'], list):
#                if sss.has_key('tenure_area'):
#                    initial['area'] = sss['sss_id']
#
#                initial['fire_position'] = sss['fire_position']

#           1. no origin, no fire boundary --> No Arrival/Final Area, Tenure-Area Other (specify)
#           2. origin, but no fire boundary --> No Arrival/Final Area, Tenure-Area Other (specify), tenure_iginition_point
#           3. origin, but no fire boundary --> No Arrival/Final Area, Other (specify), No tenure_iginition_point (Other specify)
#           4. if area --> Other (specify), Tenure-Area list exists (fields can be null, except tenure area)

        return initial

    def post(self, request, *args, **kwargs):
        #import ipdb; ipdb.set_trace()
        if self.request.POST.has_key('sss_create'):
            return self.render_to_response(self.get_context_data())

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')

        #import ipdb; ipdb.set_trace()
        if form.is_valid() and area_burnt_formset.is_valid():
            return self.form_valid(request, form, area_burnt_formset)
        else:
            return self.form_invalid(request, form, area_burnt_formset, kwargs)

    def form_invalid(self, request, form, area_burnt_formset, kwargs):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'area_burnt_formset': area_burnt_formset})
        return self.render_to_response(context)

    def form_valid(self, request, form, area_burnt_formset):
        self.object = form.save(commit=False)
        self.object.creator = request.user #1 #User.objects.all()[0] #request.user
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user
        #calc_coords(self.object)
        #import ipdb; ipdb.set_trace()

        self.object.save()
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireCreateView, self).get_context_data(**kwargs)
        except:
            context = {}

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        #import ipdb; ipdb.set_trace()
        area_burnt_formset = None
        if self.request.POST.has_key('sss_create'):
            sss = json.loads( self.request.POST['sss_create'] )
            if sss.has_key('tenure_area'):
                area_burnt_formset = update_areas_burnt(None, sss['tenure_area'])

#        import ipdb; ipdb.set_trace()
#        t=Tenure.objects.all()[0]
#        initial = [{'tenure': t, 'area':0.0, 'name':'ABC', 'other':'Other'}]
#
#        from django.forms.models import inlineformset_factory
#        AreaBurntFormset = inlineformset_factory(Bushfire, AreaBurnt, extra=len(initial), can_delete=False, exclude=())
#        fs = AreaBurntFormset(instance=self.object, prefix='area_burnt_fs')
#        for subform, data in zip(fs.forms, initial):
#            subform.initial = data

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=self.object if hasattr(self, 'object') else None, prefix='area_burnt_fs')
            #area_burnt_formset      = AreaBurntFormSet(instance=None, prefix='area_burnt_fs')

        if self.request.POST.has_key('sss_create'):
            # don't validate the form when initially displaying
            form.is_bound = False

        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        #'area_burnt_formset': fs,
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

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')

        if form.is_valid() and area_burnt_formset.is_valid():
            return self.form_valid(request, form, area_burnt_formset)
        else:
            return self.form_invalid(request, form, area_burnt_formset, kwargs)

    def form_invalid(self, request, form, area_burnt_formset, wargs):
        context = self.get_context_data()
        context.update({'form': form})
        context.update({'area_burnt_formset': area_burnt_formset})
        return self.render_to_response(context)

    def form_valid(self, request, form, area_burnt_formset):
        self.object = form.save(commit=False)
        if not self.object.creator:
            self.object.creator = request.user
        self.object.modifier = request.user
        #calc_coords(self.object)

        archive_spatial_data(self.object)

        self.object.save()
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)

        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireInitUpdateView, self).get_context_data(**kwargs)
        except:
            context = {}

        #import ipdb; ipdb.set_trace()
        bushfire = Bushfire.objects.get(id=self.kwargs['pk'])
        #bushfire = self.object
        form_class = self.get_form_class()
        form = self.get_form(form_class)

	#import ipdb; ipdb.set_trace()
        area_burnt_formset = None
        if self.request.POST.has_key('sss_create'):
            sss = json.loads( self.request.POST['sss_create'] )
            if sss.has_key('tenure_area'):
                area_burnt_formset = update_areas_burnt(None, sss['tenure_area'])

        if not area_burnt_formset:
            area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')

        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'is_authorised': bushfire.is_init_authorised,
                        'snapshot': deserialize_bushfire('initial', bushfire) if bushfire.initial_snapshot else None,
                        'initial': True,
            })
        return context


class BushfireFinalUpdateView(LoginRequiredMixin, UpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/detail.html'

    def get_initial(self):
        if self.object.time_to_control:
            return { 'days': self.object.time_to_control.days, 'hours': self.object.time_to_control.seconds/3600 }

    def get_success_url(self):
        return reverse("home")

    def post(self, request, *args, **kwargs):
        #import ipdb; ipdb.set_trace()

        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        injury_formset          = InjuryFormSet(self.request.POST, prefix='injury_fs')
        damage_formset          = DamageFormSet(self.request.POST, prefix='damage_fs')

        if form.is_valid() and area_burnt_formset.is_valid() and injury_formset.is_valid() and damage_formset.is_valid():
            return self.form_valid(request,
                form,
                area_burnt_formset,
                injury_formset,
                damage_formset,
            )
        else:
            return self.form_invalid(request,
                form,
                area_burnt_formset,
                injury_formset,
                damage_formset,
            )

    def form_invalid(self, request,
            form,
            area_burnt_formset,
            injury_formset,
            damage_formset,
        ):

        context = self.get_context_data()
        context.update({
            'form': form,
            'area_burnt_formset': area_burnt_formset,
            'injury_formset': injury_formset,
            'damage_formset': damage_formset,
        })
        #import ipdb; ipdb.set_trace()
        return self.render_to_response(context=context)

    def form_valid(self, request,
            form,
            area_burnt_formset,
            injury_formset,
            damage_formset,
        ):

        #import ipdb; ipdb.set_trace()
        self.object = form.save(commit=False)
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user
        days = form.cleaned_data['days'] if form.cleaned_data['days'] else 0
        hours = form.cleaned_data['hours'] if form.cleaned_data['hours'] else 0
        self.object.time_to_control = parse_duration('{} {}:00:00'.format(days, hours)) # 3 02:00:00
        self.object.save()

        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        injury_updated = update_injury_fs(self.object, injury_formset)
        damage_updated = update_damage_fs(self.object, damage_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))

        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        elif not injury_updated:
            messages.error(request, 'There was an error saving Injury.')
            return redirect_referrer

        elif not damage_updated:
            messages.error(request, 'There was an error saving Damage.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())


    def get_context_data(self, **kwargs):
        context = super(BushfireFinalUpdateView, self).get_context_data(**kwargs)

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        #import ipdb; ipdb.set_trace()
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        injury_formset  = InjuryFormSet(instance=self.object, prefix='injury_fs')
        damage_formset   = DamageFormSet(instance=self.object, prefix='damage_fs')
        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'injury_formset': injury_formset,
                        'damage_formset': damage_formset,
                        'is_authorised': self.object.is_final_authorised,
                        'snapshot': deserialize_bushfire('final', self.object) if self.object.final_snapshot else None, #bushfire.snapshot,
                        'final': True,
            })
        return context

class BushfireReviewUpdateView(BushfireFinalUpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/detail.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireReviewUpdateView, self).get_context_data(**kwargs)

        context.update({
             'review': True,
        })
        return context



"""
NEXT - For Testing ONLY
"""
from bfrs.forms import (BushfireTestForm)
from bfrs.models import (BushfireTest)
class BushfireCreateTestView(LoginRequiredMixin, generic.CreateView):
    model = BushfireTest
    form_class = BushfireTestForm
    template_name = 'bfrs/create_tmp.html'

    def get_success_url(self):
        #return reverse("bushfire:index")
        return reverse("home")


