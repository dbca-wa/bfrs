from django import forms
from bfrs.models import (Bushfire, AreaBurnt, Damage, Injury, FireBehaviour,
        Region, District, Profile,
        current_finyear,
    )
from datetime import datetime, timedelta
from django.conf import settings
from django.forms import ValidationError
from django.forms.models import inlineformset_factory, formset_factory, BaseInlineFormSet
from django.contrib import messages
from django.contrib.auth.models import User, Group

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, ButtonHolder, Submit, Div, HTML
from crispy_forms.bootstrap import TabHolder, Tab
from django.utils.safestring import mark_safe
from django.forms.widgets import Widget

YESNO_CHOICES = (
    (True, 'Yes'),
    (False, 'No')
)

REPORTING_YEAR_CHOICES = (
    #(current_finyear()-1, str(current_finyear()-1) + '/' + str(current_finyear())),
    (current_finyear(), str(current_finyear()) + '/' + str(current_finyear() + 1)),
    (current_finyear() + 1, str(current_finyear() + 1) + '/' + str(current_finyear() + 2)),
)


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;&nbsp;\n'.join([u'%s&nbsp;&nbsp;&nbsp;&nbsp;\n' % w for w in self]))


class VerticalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'<br />'.join([u'%s<br />' % w for w in self]))


class DisplayOnlyField(Widget):

    def __init__(self,attrs=None):
        self.attrs = attrs or {}
        self.required = False

    def render(self, name, value="", attrs=None):
        try:
            val = value
        except AttributeError:
            val = ""
        return val


class UserForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        self.fields['is_active'].label = ("Approved User (i.e. enable login for this user?)")
        instance = getattr(self, 'instance', None)
#        if instance and instance.pk:
#            self.fields['username'].widget.attrs['readonly'] = True
#            self.fields['email'].widget.attrs['readonly'] = True
#            self.fields['first_name'].widget.attrs['readonly'] = True
#            self.fields['last_name'].widget.attrs['readonly'] = True

    class Meta:
        model = User
        fields = ('is_active', 'groups', 'user_permissions',)


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        exclude = ()



class BaseFormHelper(FormHelper):
    """
    Base helper class for rendering forms via crispy_forms.
    To remove the default "Save" button from the helper, instantiate it with
    inputs=[]
    E.g. helper = BaseFormHelper(inputs=[])
    """
    def __init__(self, *args, **kwargs):
        super(BaseFormHelper, self).__init__(*args, **kwargs)
        self.form_class = 'horizontal col-lg-2'
        self.help_text_inline = True
        self.form_method = 'POST'
        save_btn = Submit('submit', 'Save')
        save_btn.field_classes = 'btn btn-primary'
        cancel_btn = Submit('cancel', 'Cancel')
        self.add_input(save_btn)
        self.add_input(cancel_btn)


class HelperModelForm(forms.ModelForm):
    """
    Stock ModelForm with a property named ``helper`` (used by crispy_forms to
    render in templates).
    """
    @property
    def helper(self):
        helper = BaseFormHelper()
        return helper


class ProfileForm(HelperModelForm):
#class ProfileForm(forms.ModelForm):
    def clean(self):
        """District must be child of Region.
        """
        cleaned_data = super(ProfileForm, self).clean()
        district = cleaned_data.get('district', None)
        if district and district.region != cleaned_data.get('region'):
            self._errors['district'] = self.error_class(
                ['Please choose a valid District for this Region (or leave it blank).'])
        # District may not be chosen if archive_date is set.
        if district and district.archive_date:
            self._errors['district'] = self.error_class(
                ['Please choose a current District for this Region (or leave it blank).'])
        return cleaned_data

    class Meta:
        model = Profile
        exclude = ('user',)


class BushfireFilterForm(forms.ModelForm):
    """
    Used to pass region and district to the filter template (in bushfire template)
    django-filter module does not allow filter chaining

    So passing a both form and filter to the context in the BushfireView, and still allowing the BushfireFilter to filter using the
    region and district passed from this form (i.e. region and filter are also declared in the BushfireFilter class)
    """

    include_archived = forms.BooleanField(required=False)
    def __init__(self, *args, **kwargs):
        super(BushfireFilterForm, self).__init__(*args, **kwargs)

        self.fields['region'].required = False
        self.fields['district'].required = False

    class Meta:
        fields = ('region', 'district', 'include_archived')
        model = Bushfire


class BushfireUpdateForm(forms.ModelForm):
    days = forms.IntegerField(label='Days', required=False)
    hours = forms.IntegerField(label='Hours', required=False)
    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    prob_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    max_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    origin_point_str = forms.CharField(required=False, widget=DisplayOnlyField())#, widget=forms.TextInput(attrs={'readonly':'readonly'}))
    media_alert_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    park_trail_impacted = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    #dispatch_pw = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    dispatch_pw = forms.ChoiceField(choices=Bushfire.DISPATCH_PW_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    #assistance_req = forms.ChoiceField(choices=Bushfire.ASSISTANCE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    other_tenure = forms.ChoiceField(choices=Bushfire.IGNITION_POINT_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    arson_squad_notified = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    reporting_year = forms.ChoiceField(choices=REPORTING_YEAR_CHOICES, required=False, initial=REPORTING_YEAR_CHOICES[0][0])

    def __init__(self, *args, **kwargs):
        super (BushfireUpdateForm,self ).__init__(*args,**kwargs)
        active_users = User.objects.filter(is_active=True).order_by('username')
        self.fields['field_officer'].queryset = active_users
        self.fields['duty_officer'].queryset = active_users

        # For use when debugging outside SSS - need to create an origin_point manually
        #from django.contrib.gis.geos import Point, GEOSGeometry
        #self.fields['origin_point'].initial = GEOSGeometry(Point(122.45, -33.15))

    class Meta:
        model = Bushfire
        fields = ('sss_data',
                  'region', 'district', 'dfes_incident_no',
                  'name', 'year', 'prob_fire_level', 'max_fire_level', 'field_officer', 'duty_officer', #'init_authorised_by', 'init_authorised_date',
                  'media_alert_req', 'park_trail_impacted', 'fire_position', 'fire_position_override',
                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date',
                  #'assistance_req', 'assistance_details',
                  'communications', 'other_info',
                  'cause', 'cause_state', 'other_cause', 'prescribed_burn_id', 'tenure', 'other_tenure',
                  'days', 'hours', 'time_to_control',
                  'dispatch_pw', 'dispatch_aerial',
                  'investigation_req', 'fire_behaviour_unknown',
                  'initial_area', 'initial_area_unknown', 'area', 'area_limit', 'origin_point_str', 'origin_point', 'fire_boundary',

                  'fire_not_found', 'fire_monitored_only', 'invalid_details',
                  'fire_contained_date', 'fire_controlled_date', 'fire_safe_date',
                  'first_attack', 'initial_control', 'final_control',
                  'other_first_attack', 'other_initial_control', 'other_final_control',
                  'arson_squad_notified', 'offence_no', 'job_code', 'reporting_year',
                  'damage_unknown','injury_unknown',

                 )

    def clean(self):
        cleaned_data = super(BushfireUpdateForm, self).clean()

        #import ipdb; ipdb.set_trace()
        # Resetting forms fields declared above to None (from '') if None if not set in form
        if not self.cleaned_data['dispatch_pw']: self.cleaned_data['dispatch_pw'] = None
        if not self.cleaned_data['dispatch_aerial']: self.cleaned_data['dispatch_aerial'] = None
        if not self.cleaned_data['prob_fire_level']: self.cleaned_data['prob_fire_level'] = None
        if not self.cleaned_data['max_fire_level']: self.cleaned_data['max_fire_level'] = None
        if not self.cleaned_data['investigation_req']: self.cleaned_data['investigation_req'] = None
        if not self.cleaned_data['cause_state']: self.cleaned_data['cause_state'] = None
        if not self.cleaned_data['media_alert_req']: self.cleaned_data['media_alert_req'] = None
        if not self.cleaned_data['park_trail_impacted']: self.cleaned_data['park_trail_impacted'] = None
        #if not self.cleaned_data['assistance_req']: self.cleaned_data['assistance_req'] = None
        if not self.cleaned_data['other_tenure']: self.cleaned_data['other_tenure'] = None

#        if self.cleaned_data['dispatch_pw'] and eval(self.cleaned_data['dispatch_pw'])==Bushfire.DISPATCH_PW_YES:
#            if not self.cleaned_data['dispatch_pw_date']:
#                self.add_error('dispatch_pw_date', 'Must specify Date and Time of dispatch, if resource is dispatched.')
#            if not self.cleaned_data['field_officer']:
#                self.add_error('field_officer', 'Must specify Field Officer, if resource is dispatched.')

#        if self.cleaned_data['dispatch_aerial'] and eval(self.cleaned_data['dispatch_aerial']):
#            if not self.cleaned_data['dispatch_aerial_date']:
#                self.add_error('dispatch_aerial_date', 'Must specify Date and Time of dispatch, if resource is dispatched.')

        #import ipdb; ipdb.set_trace()
        if self.cleaned_data.has_key('job_code') and self.cleaned_data['job_code']:
            job_code = self.cleaned_data['job_code']
            if not job_code.isalpha() or len(job_code)!=3 or not job_code.isupper():
                self.add_error('job_code', 'Must be alpha characters, length 3, and uppercase, eg. UOV')

        if self.cleaned_data.has_key('fire_detected_date') and self.cleaned_data['fire_detected_date']:
            if self.cleaned_data.has_key('dispatch_pw_date') and self.cleaned_data['dispatch_pw_date'] and self.cleaned_data['dispatch_pw_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_pw_date', 'Datetime must not be before Fire Detected Datetime.')
            if self.cleaned_data.has_key('dispatch_aerial_date') and self.cleaned_data['dispatch_aerial_date'] and self.cleaned_data['dispatch_aerial_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_aerial_date', 'Datetime must not be before Fire Detected Datetime.')

        hours = self.cleaned_data['hours'] if self.cleaned_data.has_key('hours') and self.cleaned_data['hours'] else 0
        days = self.cleaned_data['days'] if self.cleaned_data.has_key('days') and self.cleaned_data['days'] else 0
        self.cleaned_data['time_to_control'] = timedelta(days=days, hours=hours)

        # FINAL Form
        if self.cleaned_data['fire_not_found']:
            self.cleaned_data['prob_fire_level'] = None
            self.cleaned_data['max_fire_level'] = None
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['fire_contained_date'] = None
            self.cleaned_data['fire_controlled_date'] = None
            self.cleaned_data['fire_safe_date'] = None
            self.cleaned_data['first_attack'] = None
            self.cleaned_data['initial_control'] = None
            self.cleaned_data['final_control'] = None
            self.cleaned_data['other_first_attack'] = None
            self.cleaned_data['other_initial_control'] = None
            self.cleaned_data['other_final_control'] = None
            self.cleaned_data['area'] = None
            self.cleaned_data['area_limit'] = False
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['offence_no'] = None
            self.cleaned_data['job_code'] = None
            self.cleaned_data['reporting_year'] = None #current_finyear()
            self.cleaned_data['region_id'] = self.initial['region']
            self.cleaned_data['district_id'] = self.initial['district']
            #self.errors.pop('region') # since these are required fields
            #self.errors.pop('district')
            return cleaned_data
        if self.cleaned_data['fire_monitored_only']:
            self.cleaned_data['first_attack'] = None
            self.cleaned_data['other_first_attack'] = None
        else:
            self.cleaned_data['invalid_details'] = None

        if self.cleaned_data['arson_squad_notified'] == '':
            self.cleaned_data['arson_squad_notified'] = None
        else:
            self.cleaned_data['arson_squad_notified'] = eval(self.cleaned_data['arson_squad_notified'])

        if self.cleaned_data.has_key('year') and self.cleaned_data.has_key('reporting_year') and int(self.cleaned_data['reporting_year']) < int(self.cleaned_data['year']):
            self.add_error('reporting_year', 'Cannot be before report financial year, {}/{}.'.format(self.cleaned_data['year'], int(self.cleaned_data['year'])+1))

        if self.cleaned_data.has_key('fire_detected_date') and self.cleaned_data['fire_detected_date']:
            if self.cleaned_data.has_key('fire_contained_date') and self.cleaned_data['fire_contained_date'] and self.cleaned_data['fire_contained_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('fire_contained_date', 'Datetime must not be before Fire Detected Datetime - {}.'.format(self.cleaned_data['fire_detected_date']))

        if self.cleaned_data.has_key('fire_contained_date') and self.cleaned_data['fire_contained_date']:
            if self.cleaned_data.has_key('fire_controlled_date') and self.cleaned_data['fire_controlled_date'] and self.cleaned_data['fire_controlled_date'] < self.cleaned_data['fire_contained_date']:
                self.add_error('fire_controlled_date', 'Datetime must not be before Fire Contained Datetime.')

        if self.cleaned_data.has_key('fire_controlled_date') and self.cleaned_data['fire_controlled_date']:
            if self.cleaned_data.has_key('fire_safe_date') and self.cleaned_data['fire_safe_date'] and self.cleaned_data['fire_safe_date'] < self.cleaned_data['fire_controlled_date']:
                self.add_error('fire_safe_date', 'Datetime must not be before Fire Controlled Datetime.')

        if self.cleaned_data.has_key('dispatch_pw_date') and self.cleaned_data['dispatch_pw_date'] and int(self.cleaned_data['dispatch_pw']) == Bushfire.DISPATCH_PW_NO:
            self.cleaned_data['dispatch_pw_date'] = None
        if self.cleaned_data.has_key('dispatch_aerial_date') and self.cleaned_data['dispatch_aerial_date'] and eval(self.cleaned_data['dispatch_aerial']) == False:
            self.cleaned_data['dispatch_aerial_date'] = None

        return cleaned_data


class BaseInjuryFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate (injury_type) combination
            2. all fields are filled
        """
        #import ipdb; ipdb.set_trace()
        #if any(self.errors):
        #    return

        duplicates = False
        injuries = []

        for form in self.forms:
            if form.cleaned_data:
                injury_type = form.cleaned_data['injury_type'] if form.cleaned_data.has_key('injury_type') else None
                number = form.cleaned_data['number'] if form.cleaned_data.has_key('number') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    if not injury_type and not number:
                        form.cleaned_data['DELETE'] = True

#                    if not injury_type:
#                        form.add_error('injury_type', 'Injury type required')
#                    if not number:
#                        form.add_error('number', 'Number required')

                    # Check that no two records have the same injury_type
                    if injury_type and number:
                        if set([(injury_type.name)]).issubset(injuries):
                            duplicates = True
                        injuries.append((injury_type.name))

                    if duplicates:
                        form.add_error('injury_type', 'Duplicate: Injury type must be unique')

        return


class BaseDamageFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate (damage_type) combination
            2. all fields are filled
        """
        duplicates = False
        damages = []

        for form in self.forms:
            if form.cleaned_data:
                damage_type = form.cleaned_data['damage_type'] if form.cleaned_data.has_key('damage_type') else None
                number = form.cleaned_data['number'] if form.cleaned_data.has_key('number') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    if not damage_type and not number:
                        form.cleaned_data['DELETE'] = True

                    # Check that no two records have the same damage_type
                    if damage_type and number:
                        if set([(damage_type.name)]).issubset(damages):
                            duplicates = True
                        damages.append((damage_type.name))

                    if duplicates:
                        form.add_error('damage_type', 'Duplicate: Damage type must be unique')

        return


class BaseFireBehaviourFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate (fuel_type) combination
            2. all fields are filled
        """
        duplicates = False
        fire_behaviour = []

        for form in self.forms:
            if form.cleaned_data:
                fuel_type = form.cleaned_data['fuel_type'] if form.cleaned_data.has_key('fuel_type') else None
                ros = form.cleaned_data['ros'] if form.cleaned_data.has_key('ros') else None
                flame_height = form.cleaned_data['flame_height'] if form.cleaned_data.has_key('flame_height') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    if not fuel_type and not ros and not flame_height:
                        form.cleaned_data['DELETE'] = True

                    # Check that no two records have the same damage_type
                    if fuel_type and ros and flame_height:
                        if set([(fuel_type.name)]).issubset(fire_behaviour):
                            duplicates = True
                        fire_behaviour.append((fuel_type.name))

                    if duplicates:
                        form.add_error('fuel_type', 'Duplicate: Fuel type must be unique')

        return


class AreaBurntForm(forms.ModelForm):
    class Meta:
        model = AreaBurnt
        fields = ('tenure', 'area',)

    def __init__(self, *args, **kwargs):
        super(AreaBurntForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            self.fields['tenure'].widget.attrs['readonly'] = True
            self.fields['area'].widget.attrs['readonly'] = True

AreaBurntFormSet            = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=0, exclude=(), form=AreaBurntForm)
InjuryFormSet               = inlineformset_factory(Bushfire, Injury, formset=BaseInjuryFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
DamageFormSet               = inlineformset_factory(Bushfire, Damage, formset=BaseDamageFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
FireBehaviourFormSet        = inlineformset_factory(Bushfire, FireBehaviour, formset=BaseFireBehaviourFormSet, extra=1, min_num=0, validate_min=False, exclude=())



