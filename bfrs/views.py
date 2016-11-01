from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, FormView
#from django.views.generic import CreateView
from django.forms.formsets import formset_factory

from bfrs.models import (Bushfire, Activity, Response, AreaBurnt, GroundForces, AerialForces,
        AttendingOrganisation, FireBehaviour, Legal, PrivateDamage, PublicDamage, Comment
    )
from bfrs.forms import (BushfireForm, BushfireCreateForm, BushfireInitUpdateForm,
        ActivityFormSet, ResponseFormSet, AreaBurntFormSet,
        GroundForcesFormSet, AerialForcesFormSet, AttendingOrganisationFormSet, FireBehaviourFormSet,
        LegalFormSet, PrivateDamageFormSet, PublicDamageFormSet, CommentFormSet
    )
from bfrs.utils import (breadcrumbs_li, calc_coords,
        update_activity_fs, update_areas_burnt_fs, update_attending_org_fs,
        update_groundforces_fs, update_aerialforces_fs, update_fire_behaviour_fs,
        update_legal_fs, update_private_damage_fs, update_public_damage_fs, update_response_fs,
        update_comment_fs,
    )
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.forms import ValidationError

class BushfireView(generic.ListView):
    model = Bushfire
    template_name = 'bushfire/bushfire.html'

#    def get_queryset(self):
#        #return Permutation.objects.all().filter(scenario__id=self.kwargs['pk'])
#        return Bushfire.objects.all()
#
#    def get_context_data(self, **kwargs):
#        context = super(BushfireView, self).get_context_data(**kwargs)
#        bushfire = Bushfire.objects.get(pk=self.kwargs['pk'])
#
#        links = [
#            (reverse('bushfire:bushfire'), 'Bushfire {}'.format(bushfire.id)),
#            (None, 'Bushfire')
#        ]
#        context['model_name'] = self.model._meta.model_name
#        context['breadcrumb_trail'] = breadcrumbs_li(links)
#
#        return context


class BushfireCreateView(generic.CreateView):
    model = Bushfire
    form_class = BushfireCreateForm
    template_name = 'bushfire/create.html'

    def get_success_url(self):
        return reverse("bushfire:index")

    def post(self, request, *args, **kwargs):
        #self.object = self.get_object()
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(self.request.POST, prefix='activity_fs')
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        attending_org_formset   = AttendingOrganisationFormSet(self.request.POST, prefix='attending_org_fs')

        if form.is_valid() and activity_formset.is_valid():
            #self.object = self.get_object()
            return self.form_valid(request,
                form,
                activity_formset,
                area_burnt_formset,
                attending_org_formset,
            )
        else:
            import ipdb; ipdb.set_trace()
            activity_formset        = ActivityFormSet(prefix='activity_fs')
            area_burnt_formset      = AreaBurntFormSet(prefix='area_burnt_fs')
            attending_org_formset   = AttendingOrganisationFormSet(prefix='attending_org_fs')

            #self.object = self.get_object()
            return self.form_invalid(
                form,
                activity_formset,
                area_burnt_formset,
                attending_org_formset,
                kwargs,
            )

    def form_invalid(self,
            form,
            activity_formset,
            area_burnt_formset,
            attending_org_formset,
            kwargs,
        ):
        import ipdb; ipdb.set_trace()
        context = {
            'form': form,
            'activity_formset': activity_formset,
            'area_burnt_formset': area_burnt_formset,
            'attending_org_formset': attending_org_formset,
        }
        return self.render_to_response(context=context)

    def form_valid(self, request,
            form,
            activity_formset,
            area_burnt_formset,
            attending_org_formset,
        ):
        import ipdb; ipdb.set_trace()
        self.object = form.save(commit=False)
        self.object.creator_id = 1 #User.objects.all()[0] #request.user
        self.object.modifier_id = 1 #User.objects.all()[0] #request.user
        calc_coords(self.object)
        self.object.save()
        activities_updated = update_activity_fs(self.object, activity_formset)
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        attending_org_updated = update_attending_org_fs(self.object, attending_org_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not activities_updated:
            messages.error(request, 'There was an error saving Activities.')
            return redirect_referrer

        elif not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        elif not attending_org_updated:
            messages.error(request, 'There was an error saving Attending Organisation.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireCreateView, self).get_context_data(**kwargs)
        except:
            context = {}

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(instance=self.object, prefix='activity_fs') # self.object posts the initial data
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        attending_org_formset   = AttendingOrganisationFormSet(instance=self.object, prefix='attending_org_fs')
        context.update({'form': form,
                        'activity_formset': activity_formset,
                        'area_burnt_formset': area_burnt_formset,
                        'attending_org_formset': attending_org_formset,
            })
        return context


class BushfireInitUpdateView(UpdateView):
    model = Bushfire
    form_class = BushfireInitUpdateForm
    template_name = 'bushfire/create.html'

    def get_success_url(self):
        return reverse("bushfire:index")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # needed for update
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(self.request.POST, prefix='activity_fs')
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        attending_org_formset   = AttendingOrganisationFormSet(self.request.POST, prefix='attending_org_fs')

        if form.is_valid() and activity_formset.is_valid() and area_burnt_formset.is_valid() and attending_org_formset.is_valid():
            return self.form_valid(request,
                form,
                activity_formset,
                area_burnt_formset,
                attending_org_formset,
            )
        else:
            return self.form_invalid(
                form,
                activity_formset,
                area_burnt_formset,
                attending_org_formset,
                kwargs,
            )

    def form_invalid(self,
            form,
            activity_formset,
            area_burnt_formset,
            attending_org_formset,
            kwargs,
        ):
        context = {
            'form': form,
            'activity_formset': activity_formset,
            'area_burnt_formset': area_burnt_formset,
            'attending_org_formset': attending_org_formset,
        }
        return self.render_to_response(context=context)

    def form_valid(self, request,
            form,
            activity_formset,
            area_burnt_formset,
            attending_org_formset,
        ):
        self.object = form.save(commit=False)
        if not self.object.creator:
            self.object.creator_id = 1 #User.objects.all()[0] #request.user
        self.object.modifier_id = 1 #User.objects.all()[0] #request.user
        calc_coords(self.object)
        self.object.save()

        activities_updated = update_activity_fs(self.object, activity_formset)
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        attending_org_updated = update_attending_org_fs(self.object, attending_org_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not activities_updated:
            messages.error(request, 'There was an error saving Activities.')
            return redirect_referrer

        elif not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        elif not attending_org_updated:
            messages.error(request, 'There was an error saving Attending Organisation.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        try:
            context = super(BushfireInitUpdateView, self).get_context_data(**kwargs)
        except:
            context = {}

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(instance=self.object, prefix='activity_fs') # self.object posts the initial data
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        attending_org_formset   = AttendingOrganisationFormSet(instance=self.object, prefix='attending_org_fs')
        context.update({'form': form,
                        'activity_formset': activity_formset,
                        'area_burnt_formset': area_burnt_formset,
                        'attending_org_formset': attending_org_formset,
            })
        return context


class BushfireUpdateView(UpdateView):
    model = Bushfire
    form_class = BushfireForm
    template_name = 'bushfire/detail.html'
    success_url = 'success'

#    def get_form_kwargs(self):
#        # pass "user" keyword argument with the current user to your form
#        kwargs = super(BushfireCreateView2, self).get_form_kwargs()
#        kwargs['user'] = self.request.user
#        return kwargs

    def get_success_url(self):
        return reverse("bushfire:index")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(self.request.POST, prefix='activity_fs')
        response_formset        = ResponseFormSet(self.request.POST, prefix='response_fs')
        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
        groundforces_formset    = GroundForcesFormSet(self.request.POST, prefix='groundforces_fs')
        aerialforces_formset    = AerialForcesFormSet(self.request.POST, prefix='aerialforces_fs')
        attending_org_formset   = AttendingOrganisationFormSet(self.request.POST, prefix='attending_org_fs')
        fire_behaviour_formset  = FireBehaviourFormSet(self.request.POST, prefix='fire_behaviour_fs')
        legal_formset           = LegalFormSet(self.request.POST, prefix='legal_fs')
        private_damage_formset  = PrivateDamageFormSet(self.request.POST, prefix='private_damage_fs')
        public_damage_formset   = PublicDamageFormSet(self.request.POST, prefix='public_damage_fs')
        comment_formset         = CommentFormSet(self.request.POST, prefix='comment_fs')

        #import ipdb; ipdb.set_trace()
        if form.is_valid() and activity_formset.is_valid() and area_burnt_formset.is_valid() and attending_org_formset.is_valid() and \
            fire_behaviour_formset.is_valid():
            return self.form_valid(request,
                form,
                activity_formset,
                response_formset,
                area_burnt_formset,
                groundforces_formset,
                aerialforces_formset,
                attending_org_formset,
                fire_behaviour_formset,
                legal_formset,
                private_damage_formset,
                public_damage_formset,
                comment_formset
            )
        else:
            return self.form_invalid(request,
                form,
                activity_formset,
                response_formset,
                area_burnt_formset,
                groundforces_formset,
                aerialforces_formset,
                attending_org_formset,
                fire_behaviour_formset,
                legal_formset,
                private_damage_formset,
                public_damage_formset,
                comment_formset
            )

    def form_invalid(self, request,
            form,
            activity_formset,
            response_formset,
            area_burnt_formset,
            groundforces_formset,
            aerialforces_formset,
            attending_org_formset,
            fire_behaviour_formset,
            legal_formset,
            private_damage_formset,
            public_damage_formset,
            comment_formset):

        context = {
            'form': form,
            'activity_formset': activity_formset,
            'response_formset': response_formset,
            'area_burnt_formset': area_burnt_formset,
            'groundforces_formset': groundforces_formset,
            'aerialforces_formset': aerialforces_formset,
            'attending_org_formset': attending_org_formset,
            'fire_behaviour_formset': fire_behaviour_formset,
            'legal_formset': legal_formset,
            'private_damage_formset': private_damage_formset,
            'public_damage_formset': public_damage_formset,
            'comment_formset': comment_formset,
        }
        return self.render_to_response(context=context)


    def form_valid(self, request,
            form,
            activity_formset,
            response_formset,
            area_burnt_formset,
            groundforces_formset,
            aerialforces_formset,
            attending_org_formset,
            fire_behaviour_formset,
            legal_formset,
            private_damage_formset,
            public_damage_formset,
            comment_formset):
        #import ipdb; ipdb.set_trace()

        self.object = form.save(commit=False)
        self.object.modifier_id = 1 #User.objects.all()[0] #request.user
        self.object.save()

        activities_updated = update_activity_fs(self.object, activity_formset)
        responses_updated = update_response_fs(self.object, response_formset)
        areas_burnt_updated = update_areas_burnt_fs(self.object, area_burnt_formset)
        groundforces_updated = update_groundforces_fs(self.object, groundforces_formset)
        aerialforces_updated = update_aerialforces_fs(self.object, aerialforces_formset)
        attending_org_updated = update_attending_org_fs(self.object, attending_org_formset)
        fire_behaviour_updated = update_fire_behaviour_fs(self.object, fire_behaviour_formset)
        legal_updated = update_legal_fs(self.object, legal_formset)
        private_damage_updated = update_private_damage_fs(self.object, private_damage_formset)
        public_damage_updated = update_public_damage_fs(self.object, public_damage_formset)
        comment_updated = update_comment_fs(self.object, request, comment_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not activities_updated:
            messages.error(request, 'There was an error saving Activities.')
            return redirect_referrer

        elif not responses_updated:
            messages.error(request, 'There was an error saving Responses.')
            return redirect_referrer

        elif not areas_burnt_updated:
            messages.error(request, 'There was an error saving Areas Burnt.')
            return redirect_referrer

        elif not groundforces_updated:
            messages.error(request, 'There was an error saving Ground Forces.')
            return redirect_referrer

        elif not aerialforces_updated:
            messages.error(request, 'There was an error saving Aerial Forces.')
            return redirect_referrer

        elif not attending_org_updated:
            messages.error(request, 'There was an error saving Attending Organisation.')
            return redirect_referrer

        elif not fire_behaviour_updated:
            messages.error(request, 'There was an error saving Fire Behaviour.')
            return redirect_referrer

        elif not legal_updated:
            messages.error(request, 'There was an error saving Legal.')
            return redirect_referrer

        elif not private_damage_updated:
            messages.error(request, 'There was an error saving Private Damage.')
            return redirect_referrer

        elif not public_damage_updated:
            messages.error(request, 'There was an error saving Public Damage.')
            return redirect_referrer

        elif not comment_updated:
            messages.error(request, 'There was an error saving Comment.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())


    def get_context_data(self, **kwargs):
        context = super(BushfireUpdateView, self).get_context_data(**kwargs)

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet(instance=self.object, prefix='activity_fs') # self.object posts the initial data
        #activity_formset        = ActivityFormSet(initial=self.object, prefix='activity_fs') # self.object posts the initial data
        response_formset        = ResponseFormSet(instance=self.object, prefix='response_fs')
        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
        groundforces_formset    = GroundForcesFormSet(instance=self.object, prefix='groundforces_fs')
        aerialforces_formset    = AerialForcesFormSet(instance=self.object, prefix='aerialforces_fs')
        attending_org_formset   = AttendingOrganisationFormSet(instance=self.object, prefix='attending_org_fs')
        fire_behaviour_formset  = FireBehaviourFormSet(instance=self.object, prefix='fire_behaviour_fs')
        legal_formset           = LegalFormSet(instance=self.object, prefix='legal_fs')
        private_damage_formset  = PrivateDamageFormSet(instance=self.object, prefix='private_damage_fs')
        public_damage_formset   = PublicDamageFormSet(instance=self.object, prefix='public_damage_fs')
        comment_formset         = CommentFormSet(instance=self.object, prefix='comment_fs')
        #import ipdb; ipdb.set_trace()
        context.update({'form': form,
                        'activity_formset': activity_formset,
                        'response_formset': response_formset,
                        'area_burnt_formset': area_burnt_formset,
                        'groundforces_formset': groundforces_formset,
                        'aerialforces_formset': aerialforces_formset,
                        'attending_org_formset': attending_org_formset,
                        'fire_behaviour_formset': fire_behaviour_formset,
                        'legal_formset': legal_formset,
                        'private_damage_formset': private_damage_formset,
                        'public_damage_formset': public_damage_formset,
                        'comment_formset': comment_formset,
            })
        return context



"""
NEXT - For Testing ONLY
"""
from bfrs.forms import (BushfireTestForm)
from bfrs.models import (BushfireTest)
class BushfireCreateTestView(generic.CreateView):
    model = BushfireTest
    form_class = BushfireTestForm
    template_name = 'bushfire/create_tmp.html'

    def get_success_url(self):
        return reverse("bushfire:index")


from bfrs.forms import (BushfireCreateForm2, ActivityFormSet2, Activity2)
from bfrs.models import (BushfireTest2)
class BushfireCreateTest2View(generic.CreateView):
    model = BushfireTest2
    form_class = BushfireCreateForm2
    template_name = 'bushfire/create2.html'

    def get_success_url(self):
        return reverse("bushfire:index")

    def get_context_data(self, **kwargs):
        context = super(BushfireCreateTest2View, self).get_context_data(**kwargs)

        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet2(instance=self.object, prefix='activity_fs') # self.object posts the initial data
#        area_burnt_formset      = AreaBurntFormSet(instance=self.object, prefix='area_burnt_fs')
#        attending_org_formset   = AttendingOrganisationFormSet(instance=self.object, prefix='attending_org_fs')
#        activity_formset        = ActivityFormSet(prefix='activity_fs') # self.object posts the initial data
#        area_burnt_formset      = AreaBurntFormSet(prefix='area_burnt_fs')
#        attending_org_formset   = AttendingOrganisationFormSet(prefix='attending_org_fs')
        context.update({'form': form,
                        'activity_formset': activity_formset,
#                        'area_burnt_formset': area_burnt_formset,
#                        'attending_org_formset': attending_org_formset,
            })
        return context

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests, instantiating a form instance with the passed
        POST variables and then checked for validity.
        """
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        activity_formset        = ActivityFormSet2(self.request.POST, prefix='activity_fs')

        if form.is_valid() and activity_formset.is_valid():
        #if form.is_valid():
            #return self.form_valid(form)
            return self.form_valid(request, form, activity_formset)
        else:
            return self.form_invalid(form)

    def form_valid(self, request,
            form,
            activity_formset,
        ):
        #import ipdb; ipdb.set_trace()
        self.object = form.save()
        activities_updated = update_activity_fs(self.object, activity_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        if not activities_updated:
            messages.error(request, 'There was an error saving Activities.')
            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())

    def _post(self, request, *args, **kwargs):
        #self.object = self.get_object()
        form_class = self.get_form_class()
        form = self.get_form(form_class)
#        activity_formset        = ActivityFormSet(self.request.POST, prefix='activity_fs')
#        area_burnt_formset      = AreaBurntFormSet(self.request.POST, prefix='area_burnt_fs')
#        attending_org_formset   = AttendingOrganisationFormSet(self.request.POST, prefix='attending_org_fs')

        #if form.is_valid() and activity_formset.is_valid():
        if form.is_valid():
            self.object = self.get_object()
            return self.form_valid(request,
                form,
#                activity_formset,
#                area_burnt_formset,
#                attending_org_formset,
            )
        else:
            import ipdb; ipdb.set_trace()
#            activity_formset        = ActivityFormSet(prefix='activity_fs')
#            area_burnt_formset      = AreaBurntFormSet(prefix='area_burnt_fs')
#            attending_org_formset   = AttendingOrganisationFormSet(prefix='attending_org_fs')

            self.object = self.get_object()
            return self.form_invalid(request,
                form,
#                activity_formset,
#                area_burnt_formset,
#                attending_org_formset,
            )

    def _form_invalid(self, request,
            form,
#            activity_formset,
#            area_burnt_formset,
#            attending_org_formset,
        ):
        #import ipdb; ipdb.set_trace()
        return self.render_to_response(
            self.get_context_data(
                form=form,
#                activity_formset=activity_formset,
#                area_burnt_formset=area_burnt_formset,
#                attending_org_formset=attending_org_formset,
            )
        )

    def _form_valid(self, request,
            form,
#            activity_formset,
#            area_burnt_formset,
#            attending_org_formset,
        ):
        self.object = form.save()
#        activities_updated = self.update_activity_fs(activity_formset)
#        areas_burnt_updated = self.update_areas_burnt_fs(area_burnt_formset)
#        attending_org_updated = self.update_attending_org_fs(attending_org_formset)

        redirect_referrer =  HttpResponseRedirect(request.META.get('HTTP_REFERER'))
#        if not activities_updated:
#            messages.error(request, 'There was an error saving Activities.')
#            return redirect_referrer
#
#        elif not areas_burnt_updated:
#            messages.error(request, 'There was an error saving Areas Burnt.')
#            return redirect_referrer
#
#        elif not attending_org_updated:
#            messages.error(request, 'There was an error saving Attending Organisation.')
#            return redirect_referrer

        return HttpResponseRedirect(self.get_success_url())


