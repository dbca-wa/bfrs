from django import forms
from bfrs.models import (Bushfire, AreaBurnt, Damage, Injury, 
        Region, District, Profile,
        current_finyear,
        reporting_years,
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

from bfrs.utils import (can_maintain_data,)

YESNO_CHOICES = (
    (True, 'Yes'),
    (False, 'No')
)

REPORTING_YEAR_CHOICES = ( reporting_years() )

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
    django-filter module does not allow filter chaining
    Form are used to populate user interface, django-filter are used to filter query set.

    So passing a both form and filter to the context in the BushfireView, and still allowing the BushfireFilter to filter using the
    region and district passed from this form (i.e. region and filter are also declared in the BushfireFilter class)
    """

    try:
        YEAR_CHOICES = [[i['year'], i['year']] for i in Bushfire.objects.all().values('year').distinct()]
        RPT_YEAR_CHOICES = [[i['reporting_year'], i['reporting_year']] for i in Bushfire.objects.all().values('reporting_year').distinct()]
        STATUS_CHOICES = [(u'-1', '---------')] + list(Bushfire.REPORT_STATUS_CHOICES)
    except:
        pass

    year = forms.ChoiceField(choices=YEAR_CHOICES,required=False)
    reporting_year = forms.ChoiceField(choices=RPT_YEAR_CHOICES, required=False)
    include_archived = forms.BooleanField(required=False)
    exclude_missing_final_fire_boundary = forms.BooleanField(required=False)
    report_status = forms.ChoiceField(choices=STATUS_CHOICES, label='Report Status',required=False)
    def __init__(self, *args, **kwargs):
        super(BushfireFilterForm, self).__init__(*args, **kwargs)

        self.fields['region'].required = False
        self.fields['district'].required = False

        try:
            # allows dynamic update of the filter set, on page refresh
            self.fields["year"].choices = [[None, '---------']] + [[i['year'], str(i['year']) + '/' + str(i['year']+1)] for i in Bushfire.objects.all().values('year').distinct().order_by('year')]
            self.fields["reporting_year"].choices = [[None, '---------']] + [[i['reporting_year'], str(i['reporting_year']) + '/' + str(i['reporting_year']+1)] for i in Bushfire.objects.all().values('reporting_year').distinct().order_by('reporting_year')]
            # allows dynamic update of the filter set, on page refresh
            if not can_maintain_data(self.request.user):
                # pop the 'Reviewed' option
                self.fields['report_status'].choices = [(u'-1', '---------'), (1, 'Initial Fire Report'), (2, 'Notifications Submitted'), (3, 'Report Authorised'), (5, 'Invalidated'), (6, 'Outstanding Fires')]
        except:
            pass

    class Meta:
        fields = ('region', 'district')
        model = Bushfire


class BushfireUpdateForm(forms.ModelForm):
    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    prob_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    max_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    origin_point_str = forms.CharField(required=False, widget=DisplayOnlyField())#, widget=forms.TextInput(attrs={'readonly':'readonly'}))
    media_alert_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    park_trail_impacted = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    dispatch_pw = forms.ChoiceField(choices=Bushfire.DISPATCH_PW_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    other_tenure = forms.ChoiceField(choices=Bushfire.IGNITION_POINT_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    arson_squad_notified = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer), required=False)
    reporting_year = forms.ChoiceField(choices=REPORTING_YEAR_CHOICES, required=False, initial=REPORTING_YEAR_CHOICES[0][0])

    def __init__(self, *args, **kwargs):
        super (BushfireUpdateForm,self ).__init__(*args,**kwargs)
        # order alphabetically, but with username='other', as first item in list
        active_users = User.objects.filter(groups__name='Users').filter(is_active=True).exclude(username__icontains='admin').extra(select={'other': "CASE WHEN username='other' THEN 0 ELSE 1 END"}).order_by('other', 'username')
        self.fields['field_officer'].queryset = active_users
        self.fields['duty_officer'].queryset = active_users.exclude(username='other')
        self.fields['reporting_year'].initial = current_finyear()

        # For use when debugging outside SSS - need to create an origin_point manually
        #from django.contrib.gis.geos import Point, GEOSGeometry
        #self.fields['origin_point'].initial = GEOSGeometry(Point(122.45, -33.15))
        #self.fields['region'].initial = 1
        #self.fields['district'].initial = 1

    class Meta:
        model = Bushfire
        fields = ('sss_data', 'sss_id',
                  'region', 'district', 'dfes_incident_no',
                  'name', 'year', 'prob_fire_level', 'max_fire_level', 'duty_officer',
                  'field_officer', 'other_field_officer', 'other_field_officer_agency', 'other_field_officer_phone',
                  'media_alert_req', 'park_trail_impacted', 'fire_position', 'fire_position_override',
                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date',
                  'other_info',
                  'cause', 'cause_state', 'other_cause', 'prescribed_burn_id', 'tenure', 'other_tenure',
                  'dispatch_pw', 'dispatch_aerial',
                  'investigation_req',
                  'initial_area', 'initial_area_unknown', 'area', 'area_limit', 'other_area',
                  'origin_point_str', 'origin_point', 'origin_point_mga', 'fire_boundary',
                  'fire_not_found', 'fire_monitored_only', 'invalid_details',
                  'fire_contained_date', 'fire_controlled_date', 'fire_safe_date',
                  'first_attack', 'initial_control', 'final_control',
                  'other_first_attack', 'other_initial_control', 'other_final_control',
                  'arson_squad_notified', 'offence_no', 'job_code', 'reporting_year',
                  'damage_unknown','injury_unknown',
                 )

    def clean(self):
        cleaned_data = super(BushfireUpdateForm, self).clean()

        # Resetting forms fields declared above to None (from '') if None if not set in form
        if not self.cleaned_data['dispatch_pw']: self.cleaned_data['dispatch_pw'] = None
        if not self.cleaned_data['dispatch_aerial']: self.cleaned_data['dispatch_aerial'] = None
        if not self.cleaned_data['prob_fire_level']: self.cleaned_data['prob_fire_level'] = None
        if not self.cleaned_data['max_fire_level']: self.cleaned_data['max_fire_level'] = None
        if not self.cleaned_data['investigation_req']: self.cleaned_data['investigation_req'] = None
        if not self.cleaned_data['cause_state']: self.cleaned_data['cause_state'] = None
        if not self.cleaned_data['media_alert_req']: self.cleaned_data['media_alert_req'] = None
        if not self.cleaned_data['park_trail_impacted']: self.cleaned_data['park_trail_impacted'] = None
        if not self.cleaned_data['other_tenure']: self.cleaned_data['other_tenure'] = None

        if self.cleaned_data.has_key('job_code') and self.cleaned_data['job_code']:
            job_code = self.cleaned_data['job_code']
            if not job_code.isalpha() or len(job_code)!=3 or not job_code.isupper():
                self.add_error('job_code', 'Must be alpha characters, length 3, and uppercase, eg. UOV')

        if self.cleaned_data.has_key('fire_detected_date') and self.cleaned_data['fire_detected_date']:
            if self.cleaned_data.has_key('dispatch_pw_date') and self.cleaned_data['dispatch_pw_date'] and self.cleaned_data['dispatch_pw_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_pw_date', 'Datetime must not be before Fire Detected Datetime.')
            if self.cleaned_data.has_key('dispatch_aerial_date') and self.cleaned_data['dispatch_aerial_date'] and self.cleaned_data['dispatch_aerial_date'] < self.cleaned_data['fire_detected_date']:
                self.add_error('dispatch_aerial_date', 'Datetime must not be before Fire Detected Datetime.')

        # FINAL Form
        if self.cleaned_data['fire_not_found']:
            self.cleaned_data['max_fire_level'] = None
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['fire_contained_date'] = None
            self.cleaned_data['fire_controlled_date'] = None
            self.cleaned_data['fire_safe_date'] = None
            self.cleaned_data['first_attack'] = None
            self.cleaned_data['final_control'] = None
            self.cleaned_data['other_first_attack'] = None
            self.cleaned_data['other_initial_control'] = None
            self.cleaned_data['other_final_control'] = None
            self.cleaned_data['area'] = None
            self.cleaned_data['area_limit'] = False
            self.cleaned_data['arson_squad_notified'] = None
            self.cleaned_data['offence_no'] = None
            self.cleaned_data['reporting_year'] = None #current_finyear()
            self.cleaned_data['region_id'] = self.initial['region']
            self.cleaned_data['district_id'] = self.initial['district']
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

        if self.cleaned_data.has_key('dispatch_pw') and self.cleaned_data['dispatch_pw']:
            self.cleaned_data['dispatch_pw'] = int(self.cleaned_data['dispatch_pw'])

        if self.cleaned_data.has_key('other_tenure') and self.cleaned_data['other_tenure']:
            self.cleaned_data['other_tenure'] = int(self.cleaned_data['other_tenure'])

        if self.cleaned_data.has_key('field_officer') and self.cleaned_data['field_officer'] and self.cleaned_data['field_officer'].username != 'other':
            self.cleaned_data['other_field_officer'] = None
            self.cleaned_data['other_field_officer_agency'] = None
            self.cleaned_data['other_field_officer_phone'] = None

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

                duplicates = False
                if not remove:
                    if not injury_type or not number:
                        #if either injury_type or number is null, the injury data will be removed if it exists; or ignored if it doesn't exist
                        form.cleaned_data['DELETE'] = True
                        continue

                    # Check that no two records have the same injury_type
                    if injury_type.name in injuries:
                        duplicates = True
                    else:
                        injuries.append((injury_type.name))

                    if duplicates:
                        form.add_error('injury_type', 'Duplicate: Injury type must be unique')

        return

    def is_valid(self, injury_unknown):
        if injury_unknown:
            # no need to validate formset
            self.errors.pop()
            self.is_bound = False
            return True
        return super(BaseInjuryFormSet, self).is_valid()

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

                duplicates = False
                if not remove:
                    if not damage_type or not number:
                        form.cleaned_data['DELETE'] = True
                        continue

                    # Check that no two records have the same damage_type
                    if damage_type.name in damages:
                        duplicates = True
                    else:
                        damages.append((damage_type.name))

                    if duplicates:
                        form.add_error('damage_type', 'Duplicate: Damage type must be unique')

        return

    def is_valid(self, damage_unknown):
        if damage_unknown:
            # no need to validate formset
            self.errors.pop()
            self.is_bound = False
            return True
        return super(BaseDamageFormSet, self).is_valid()


#class BaseFireBehaviourFormSet(BaseInlineFormSet):
#    def clean(self):
#        """
#        Adds validation to check:
#            1. no duplicate (fuel_type) combination
#            2. all fields are filled
#        """
#        duplicates = False
#        fire_behaviour = []
#
#        for form in self.forms:
#            if form.cleaned_data:
#                fuel_type = form.cleaned_data['fuel_type'] if form.cleaned_data.has_key('fuel_type') else None
#                ros = form.cleaned_data['ros'] if form.cleaned_data.has_key('ros') else None
#                flame_height = form.cleaned_data['flame_height'] if form.cleaned_data.has_key('flame_height') else None
#                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False
#
#                if not remove:
#                    if not fuel_type and not ros and not flame_height:
#                        form.cleaned_data['DELETE'] = True
#
#                    # Check that no two records have the same damage_type
#                    if fuel_type and ros and flame_height:
#                        if set([(fuel_type.name)]).issubset(fire_behaviour):
#                            duplicates = True
#                        fire_behaviour.append((fuel_type.name))
#
#                    if duplicates:
#                        form.add_error('fuel_type', 'Duplicate: Fuel type must be unique')
#
#        return


class AreaBurntForm(forms.ModelForm):
    class Meta:
        model = AreaBurnt
        fields = ('tenure', 'area',)

    def __init__(self, *args, **kwargs):
        super(AreaBurntForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            self.fields['tenure'].widget.attrs['readonly'] = True
            self.fields['area'].widget.attrs['readonly'] = True


RECOMMENDATION_CHOICES = (
    (1, 'Noted'),
    (2, 'Noted/Endorsed'),
    (3, 'Noted/Endorsed with Amendment'),
    (4, 'Accept/Attending'),
)

class PDFReportForm(forms.Form):
    author = forms.CharField(max_length=100)
    position = forms.CharField(max_length=100)
    phone_no = forms.CharField(max_length=100)
    branch = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'eg. Fire Management Services Branch'}))
    division = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'eg. Regional and Fire Management Services Division'}))
    your_ref = forms.CharField(max_length=20, required=False)
    our_ref = forms.CharField(max_length=20, required=False)
    title = forms.CharField(max_length=50, widget=forms.TextInput(attrs={'placeholder': 'eg. BUSHFIRE SUPPRESSION'}))

    supplementary_text = forms.CharField(max_length=500, widget=forms.Textarea(), required=False)
    cost_implications = forms.CharField(max_length=250, widget=forms.Textarea(), required=False)
    urgency = forms.CharField(max_length=2500, widget=forms.Textarea(), required=False)
    contentious_issues = forms.CharField(max_length=250, widget=forms.Textarea(), required=False)
    sig_date = forms.CharField(max_length=20, required=True)
    recommendation = forms.ChoiceField(choices=RECOMMENDATION_CHOICES, widget=forms.RadioSelect(), initial=1,  required=True)


AreaBurntFormSet            = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=0, exclude=(), form=AreaBurntForm)
InjuryFormSet               = inlineformset_factory(Bushfire, Injury, formset=BaseInjuryFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
DamageFormSet               = inlineformset_factory(Bushfire, Damage, formset=BaseDamageFormSet, extra=1, max_num=7, min_num=0, validate_min=False, exclude=())
#FireBehaviourFormSet        = inlineformset_factory(Bushfire, FireBehaviour, formset=BaseFireBehaviourFormSet, extra=1, min_num=0, validate_min=False, exclude=())



