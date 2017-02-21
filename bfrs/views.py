from django.http import HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.core.urlresolvers import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, FormView
#from django.views.generic import CreateView
from django.forms.formsets import formset_factory
from django.contrib.auth.mixins import LoginRequiredMixin

from bfrs.models import (Profile, Bushfire, Activity, Response, AreaBurnt, GroundForces, AerialForces,
        AttendingOrganisation, FireBehaviour, Legal, PrivateDamage, PublicDamage, Comment,
        Region, District, ActivityType, Cause
    )
from bfrs.forms import (ProfileForm, BushfireForm, BushfireCreateForm, BushfireInitUpdateForm,
        ActivityFormSet, ResponseFormSet, AreaBurntFormSet,
        GroundForcesFormSet, AerialForcesFormSet, AttendingOrganisationFormSet, FireBehaviourFormSet,
        LegalFormSet, PrivateDamageFormSet, PublicDamageFormSet, InjuryFormSet, DamageFormSet, CommentFormSet,
        BushfireFilterForm
    )
from bfrs.utils import (breadcrumbs_li, calc_coords,
        update_activity_fs, update_areas_burnt_fs, update_attending_org_fs,
        update_groundforces_fs, update_aerialforces_fs, update_fire_behaviour_fs,
        update_legal_fs, update_injury_fs, update_damage_fs, update_response_fs,
        update_comment_fs,
        export_final_csv, serialize_bushfire, deserialize_bushfire,
    )
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.forms import ValidationError
from datetime import datetime
import pytz
from django.utils.dateparse import parse_duration

import django_filters
#from  django_filters import FilterSet
from django_filters import views as filter_views


class BushfireFilter(django_filters.FilterSet):

    YEAR_CHOICES = [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct()]

    REGION_CHOICES = []
    for region in Region.objects.distinct('name'):
        REGION_CHOICES.append([region.id, region.name])

    DISTRICT_CHOICES = []
    for district in District.objects.distinct('name'):
        DISTRICT_CHOICES.append([district.id, district.name])

    CAUSE_CHOICES = []
    for cause in Cause.objects.distinct('name'):
        CAUSE_CHOICES.append([cause.id, cause.name])

    region = django_filters.ChoiceFilter(choices=REGION_CHOICES, label='Region')
    district = django_filters.ChoiceFilter(choices=DISTRICT_CHOICES, label='District')
    year = django_filters.ChoiceFilter(choices=YEAR_CHOICES, label='Year')
    cause = django_filters.ChoiceFilter(choices=CAUSE_CHOICES, label='Cause')
    report_status = django_filters.ChoiceFilter(choices=Bushfire.REPORT_STATUS_CHOICES, label='Report Status')
    #potential_fire_level = django_filters.ChoiceFilter(choices=Bushfire.FIRE_LEVEL_CHOICES, label='Probable Fire Level')

    class Meta:
        model = Bushfire
        fields = [
			'region_id',
			'district_id',
			'year',
			'report_status',
			'cause',
			#'potential_fire_level',
		]
        order_by = (
            ('region_id', 'Region'),
            ('district_id', 'District'),
            ('year', 'Year'),
            ('report_status', 'Report Status'),
            ('cause', 'Cause'),
            #('potential_fire_level', 'Probable Fire Level'),
        )


    def __init__(self, *args, **kwargs):
        super(BushfireFilter, self).__init__(*args, **kwargs)

        # allows dynamic update of the filter set, on page refresh
        self.filters['year'].extra['choices'] = [[None, '---------']] + [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]

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

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def get(self, request, *args, **kwargs):
        response = super(BushfireView, self).get(request, *args, **kwargs)

        if self.request.GET.has_key('export_to_csv'):
            report = self.request.GET.get('export_to_csv')
            if report == 'final':
                qs = self.get_filterset(self.filterset_class).qs
                return export_final_csv(self.request, qs)

        #import ipdb; ipdb.set_trace()
        if self.request.GET.has_key('authorise'):
            status_type = self.request.GET.get('authorise')
            bushfire = Bushfire.objects.get(id=self.request.GET.get('bushfire_id'))

            # Authorise the INITIAL report
            if status_type == 'initial_auth' and bushfire.report_status==Bushfire.STATUS_INITIAL:
                bushfire.init_authorised_by = self.request.user
                bushfire.init_authorised_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
                bushfire.max_fire_level = bushfire.potential_fire_level
                serialize_bushfire('initial', bushfire)

            # CREATE the FINAL DRAFT report
            if status_type == 'final_create' and bushfire.report_status==Bushfire.STATUS_INITIAL_AUTHORISED:
                bushfire.report_status = Bushfire.STATUS_FINAL_DRAFT
                serialize_bushfire('final', bushfire)

            # Authorise the FINAL report
            if status_type == 'final_auth' and bushfire.report_status==Bushfire.STATUS_FINAL_DRAFT:
                bushfire.authorised_by = self.request.user
                bushfire.authorised_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED

            # CREATE the REVIEWABLE DRAFT report
            if status_type == 'review_create' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
                bushfire.report_status = Bushfire.STATUS_REVIEW_DRAFT

            # Authorise the REVIEW DRAFT report
            if status_type == 'reviewed' and bushfire.report_status==Bushfire.STATUS_REVIEW_DRAFT:
                bushfire.reviewed_by = self.request.user
                bushfire.reviewed_date = datetime.now(tz=pytz.utc)
                bushfire.report_status = Bushfire.STATUS_REVIEWED

            bushfire.save()

        return response

    def get_context_data(self, **kwargs):
        context = super(BushfireView, self).get_context_data(**kwargs)
        #import ipdb; ipdb.set_trace()

        # initial parameter prevents the form from resetting, if the region and district filters had a value set previously
        initial = {}
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

        # update context with form - filter is already in the context
        context['form'] = BushfireFilterForm(initial=initial)
        context['object_list'] = self.object_list # passed by default, but we are (possibly) updating, if profile exists!
        return context


class BushfireCreateView(LoginRequiredMixin, generic.CreateView):
    model = Bushfire
    form_class = BushfireCreateForm
    template_name = 'bfrs/create.html'

    def get_success_url(self):
        return reverse("home")

    def get_initial(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return { 'region': profile.region, 'district': profile.district }

    def post(self, request, *args, **kwargs):
        #self.object = self.get_object()
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')

        if form.is_valid() and area_burnt_formset.is_valid():
            return self.form_valid(request,
                form,
                area_burnt_formset,
            )
        else:
            return self.form_invalid(
                form,
                area_burnt_formset,
                kwargs,
            )

    def form_invalid(self,
            form,
            area_burnt_formset,
            kwargs,
        ):
        context = {
            'form': form,
            'area_burnt_formset': area_burnt_formset,
        }
        return self.render_to_response(context=context)

    def form_valid(self, request,
            form,
            area_burnt_formset,
        ):
        self.object = form.save(commit=False)
        self.object.creator = request.user #1 #User.objects.all()[0] #request.user
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user
        #calc_coords(self.object)

        self.object.save()
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)

#        if self.request.POST.has_key('init_authorise'):
#            self.object.init_authorised_by = self.request.user
#            self.object.init_authorised_date = datetime.now()
#            self.object.report_status = 2
#
#        if self.object.is_init_authorised:
#            save_initial_snapshot(self.object)

        self.object.save()

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
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'create': True,
            })
        return context


class BushfireInitUpdateView(LoginRequiredMixin, UpdateView):
    model = Bushfire
    form_class = BushfireInitUpdateForm
    template_name = 'bfrs/create.html'

    def get_success_url(self):
        return reverse("home")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')

        if form.is_valid() and area_burnt_formset.is_valid():
            return self.form_valid(request,
                form,
                area_burnt_formset,
            )
        else:
            return self.form_invalid(
                form,
                area_burnt_formset,
                kwargs,
            )

    def form_invalid(self,
            form,
            area_burnt_formset,
            kwargs,
        ):
        context = {
            'form': form,
            'area_burnt_formset': area_burnt_formset,
        }
        return self.render_to_response(context=context)

    def form_valid(self, request,
            form,
            area_burnt_formset,
        ):
        self.object = form.save(commit=False)
        if not self.object.creator:
            self.object.creator = request.user #1 #User.objects.all()[0] #request.user
        self.object.modifier = request.user # 1 #User.objects.all()[0] #request.user
        #calc_coords(self.object)

#        if self.request.POST.has_key('init_authorise'):
#            self.object.init_authorised_by = self.request.user
#            self.object.init_authorised_date = datetime.now()
#            self.object.report_status = 2
#
#        if self.object.is_init_authorised:
#            save_initial_snapshot(self.object)

        self.object.save()

        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))

        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireInitUpdateView, self).get_context_data(**kwargs)
        except:
            context = {}

        #import ipdb; ipdb.set_trace()
        bushfire = Bushfire.objects.get(id=self.kwargs['pk'])
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'is_init_authorised': bushfire.is_init_authorised,
                        'snapshot': deserialize_bushfire('initial', bushfire) if bushfire.initial_snapshot else None,
                        'initial': True,
            })
        return context


class BushfireFinalUpdateView(LoginRequiredMixin, UpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/final.html'

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
        fire_behaviour_formset  = FireBehaviourFormSet(self.request.POST, prefix='fire_behaviour_fs')
        injury_formset          = InjuryFormSet(self.request.POST, prefix='injury_fs')
        damage_formset          = DamageFormSet(self.request.POST, prefix='damage_fs')
        comment_formset         = CommentFormSet(self.request.POST, prefix='comment_fs')

        if form.is_valid() and area_burnt_formset.is_valid():
            return self.form_valid(request,
                form,
                area_burnt_formset,
                fire_behaviour_formset,
                injury_formset,
                damage_formset,
                comment_formset
            )
        else:
            return self.form_invalid(request,
                form,
                area_burnt_formset,
                fire_behaviour_formset,
                injury_formset,
                damage_formset,
                comment_formset
            )

    def form_invalid(self, request,
            form,
            area_burnt_formset,
            fire_behaviour_formset,
            injury_formset,
            damage_formset,
            comment_formset):

        context = {
            'form': form,
            'area_burnt_formset': area_burnt_formset,
            'fire_behaviour_formset': fire_behaviour_formset,
            'injury_formset': injury_formset,
            'damage_formset': damage_formset,
            'comment_formset': comment_formset,
        }
        return self.render_to_response(context=context)


    def form_valid(self, request,
            form,
            area_burnt_formset,
            fire_behaviour_formset,
            injury_formset,
            damage_formset,
            comment_formset):


        #import ipdb; ipdb.set_trace()
        self.object = form.save(commit=False)
        self.object.modifier = request.user #1 #User.objects.all()[0] #request.user
        days = form.cleaned_data['days'] if form.cleaned_data['days'] else 0
        hours = form.cleaned_data['hours'] if form.cleaned_data['hours'] else 0
        self.object.time_to_control = parse_duration('{} {}:00:00'.format(days, hours)) # 3 02:00:00
        self.object.save()

        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        fire_behaviour_updated = update_fire_behaviour_fs(self.object, fire_behaviour_formset)
        injury_updated = update_injury_fs(self.object, injury_formset)
        damage_updated = update_damage_fs(self.object, damage_formset)
        comment_updated = update_comment_fs(self.object, request, comment_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))

        if not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        elif not fire_behaviour_updated:
            messages.error(request, 'There was an error saving Fire Behaviour.')
            return redirect_referrer

        elif not injury_updated:
            messages.error(request, 'There was an error saving Injury.')
            return redirect_referrer

        elif not damage_updated:
            messages.error(request, 'There was an error saving Damage.')
            return redirect_referrer

        elif not comment_updated:
            messages.error(request, 'There was an error saving Comment.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())


    def get_context_data(self, **kwargs):
        context = super(BushfireFinalUpdateView, self).get_context_data(**kwargs)

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        #import ipdb; ipdb.set_trace()
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        fire_behaviour_formset  = FireBehaviourFormSet(instance=self.object, prefix='fire_behaviour_fs')
        injury_formset  = InjuryFormSet(instance=self.object, prefix='injury_fs')
        damage_formset   = DamageFormSet(instance=self.object, prefix='damage_fs')
        comment_formset         = CommentFormSet(instance=self.object, prefix='comment_fs')
        context.update({'form': form,
                        'area_burnt_formset': area_burnt_formset,
                        'fire_behaviour_formset': fire_behaviour_formset,
                        'injury_formset': injury_formset,
                        'damage_formset': damage_formset,
                        'comment_formset': comment_formset,
                        'snapshot': deserialize_bushfire('final', self.object) if self.object.final_snapshot else None, #bushfire.snapshot,
            })
        return context

class BushfireReviewUpdateView(BushfireFinalUpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bfrs/review.html'

    def get_context_data(self, **kwargs):
        context = super(BushfireReviewUpdateView, self).get_context_data(**kwargs)

#        context.update({
#            'dummy': True,
#        })
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


#from bfrs.forms import (BushfireCreateForm2, ActivityFormSet2, Activity2)
#from bfrs.models import (BushfireTest2)
#class BushfireCreateTest2View(LoginRequiredMixin, generic.CreateView):
#    model = BushfireTest2
#    form_class = BushfireCreateForm2
#    template_name = 'bfrs/create2.html'
#
#    def get_success_url(self):
#        #return reverse("bushfire:index")
#        return reverse("home")
#
#    def get_context_data(self, **kwargs):
#        context = super(BushfireCreateTest2View, self).get_context_data(**kwargs)
#
#        form_class = self.get_form_class()
#        form = self.get_form(form_class)
#        activity_formset        = ActivityFormSet2(instance=self.object, prefix='activity_fs') # self.object posts the initial data
#        context.update({'form': form,
#                        'activity_formset': activity_formset,
#            })
#        return context
#
#    def post(self, request, *args, **kwargs):
#        """
#        Handles POST requests, instantiating a form instance with the passed
#        POST variables and then checked for validity.
#        """
#        form_class = self.get_form_class()
#        form = self.get_form(form_class)
#        activity_formset        = ActivityFormSet2(self.request.POST, prefix='activity_fs')
#
#        if form.is_valid() and activity_formset.is_valid():
#        #if form.is_valid():
#            #return self.form_valid(form)
#            return self.form_valid(request, form, activity_formset)
#        else:
#            return self.form_invalid(form)
#
#    def form_valid(self, request,
#            form,
#            activity_formset,
#        ):
#        self.object = form.save()
#        activities_updated = update_activity_fs(self.object, activity_formset)
#
#        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
#        if not activities_updated:
#            messages.error(request, 'There was an error saving Activities.')
#            return redirect_referrer
#
#        return HttpResponseRedirect(self.get_success_url())


