from django import forms
from bfrs.models import (Bushfire, Activity, Response, AreaBurnt, GroundForces, AerialForces,
        AttendingOrganisation, FireBehaviour, Legal, PrivateDamage, PublicDamage, InjuryFatality, Damage, Comment,
        Region, District, Profile
    )
from datetime import datetime, timedelta
from django.conf import settings
from django.forms import ValidationError
from django.forms.models import inlineformset_factory, formset_factory, BaseInlineFormSet
#from django.forms.formsets import BaseFormSet
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
        #import ipdb; ipdb.set_trace()
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            self.fields['username'].widget.attrs['readonly'] = True
            self.fields['email'].widget.attrs['readonly'] = True
            self.fields['first_name'].widget.attrs['readonly'] = True
            self.fields['last_name'].widget.attrs['readonly'] = True

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

    def __init__(self, *args, **kwargs):
        super(BushfireFilterForm, self).__init__(*args, **kwargs)

        self.fields['region'].required = False
        self.fields['district'].required = False

    class Meta:
        fields = ('region', 'district')
        model = Bushfire


class BushfireForm(forms.ModelForm):
    days = forms.IntegerField(label='Days', required=False)
    hours = forms.IntegerField(label='Hours', required=False)
    class Meta:
        model = Bushfire
        exclude = ('initial_snapshot', 'init_authorised_by', 'init_authorised_date',
				   'potential_fire_level')

#    def save(self, commit=True, *args, **kwargs):
#        m = super(BushfireForm, self).save(commit=False, *args, **kwargs)
#        import ipdb; ipdb.set_trace()


    def clean(self):
        """
        Form can be saved prior to sign-off, without checking req'd fields.
        Required fields are checked during Authorisation sign-off, therefore checking and adding error fields manually
        """
        req_fields = [
            #'region', 'district', 'incident_no', 'season', # these are delcared Required in models.py
            #'name', 'potential_fire_level', 'init_authorised_by', 'init_authorised_date',
            'name', 'authorised_by', 'authorised_date',
            'job_code',
            'cause',
            'field_officer',
            'fire_level',
            #'known_possible',
        ]

        req_dep_fields = { # required dependent fields
            'first_attack': 'other_first_attack',
            'initial_control': 'other_initial_control',
            'final_control': 'other_final_control',
            'cause': 'other_cause',
#            'coord_type': {
#                'MGA': ['MGA Zone','MGA Easting','MGA Northing'],
#                }
        }

#        req_coord_fields = {
#            'MGA': ['mga_zone','mga_easting','mga_northing'],
#            'FD Grid': ['fd_letter','fd_number','fd_tenths'],
#            'Lat/Long': ['lat_decimal','lat_degrees','lat_minutes', 'lon_decimal','lon_degrees','lon_minutes'],
#        }

        if self.cleaned_data['authorised_by']:
            # check all required fields
            #import ipdb; ipdb.set_trace()
            [self.add_error(field, 'This field is required.') for field in req_fields if not self.cleaned_data.has_key(field) or not self.cleaned_data[field]]

            # check if 'Other' has been selected from drop down and field has been set
            for field in req_dep_fields.keys():
                if self.cleaned_data.has_key(field) and 'other' in str(self.cleaned_data[field]).lower():
                    other_field = self.cleaned_data[req_dep_fields[field]]
                    if not other_field:
                        #import ipdb; ipdb.set_trace()
                        self.add_error(req_dep_fields[field], 'This field is required.')
            #import ipdb; ipdb.set_trace()

#            coord_type = [i[1] for i in Bushfire.COORD_TYPE_CHOICES if i[0]==self.cleaned_data['coord_type']]
#            if coord_type:
#                #import ipdb; ipdb.set_trace()
#                for field in req_coord_fields[coord_type[0]]:
#                    if self.cleaned_data.has_key(field) and not self.cleaned_data[field]:
#                        self.add_error(field, 'This field is required.')

            #import ipdb; ipdb.set_trace()
            #if missing_fields:
            #    raise ValidationError('Cannot Authorise, must input required fields: {}'.format(', '.join([i.replace('_', ' ').title() for i in missing_fields])))

class BushfireCreateBaseForm(forms.ModelForm):
    days = forms.IntegerField(label='Days', required=False)
    hours = forms.IntegerField(label='Hours', required=False)
    dispatch_pw = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
    potential_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
    origin_point_str = forms.CharField(required=False, widget=DisplayOnlyField())#, widget=forms.TextInput(attrs={'readonly':'readonly'}))

    class Meta:
        model = Bushfire
        fields = ('region', 'district', 'incident_no', 'job_code', 'dfes_incident_no',
                  'name', 'year', 'potential_fire_level', 'field_officer', 'duty_officer', 'init_authorised_by', 'init_authorised_date',
                  'media_alert_req', 'fire_position',
                  'grid', 'fire_not_found',
                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date', 'fuel_type',
                  'assistance_req', 'assistance_details', 'communications', 'other_info',
                  'cause', 'cause_state', 'other_cause', 'tenure', 'other_tenure',
                  'days','hours',
                  'dispatch_pw', 'dispatch_aerial',
                  'investigation_req',
		  'area', 'origin_point_str', 'origin_point', 'fire_boundary',
                 )

    def clean_investigation_req(self):
        if not self.cleaned_data.has_key('investigation_req'):
            raise ValidationError('Must specify investigation required')

        investigation_req = eval(self.cleaned_data['investigation_req'])
        return investigation_req


#class BushfireCreateForm(forms.ModelForm):
#    days = forms.IntegerField(label='Days', required=False)
#    hours = forms.IntegerField(label='Hours', required=False)
#    dispatch_pw = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    potential_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#
#    class Meta:
#        model = Bushfire
#        fields = ('region', 'district', 'incident_no', 'job_code', 'dfes_incident_no',
#                  'name', 'year', 'potential_fire_level', 'field_officer', 'duty_officer', 'init_authorised_by', 'init_authorised_date',
#                  'media_alert_req', 'fire_position',
#                  'grid', 'arrival_area', 'fire_not_found',
#                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date', 'fuel_type',
#                  'assistance_req', 'assistance_details', 'communications', 'other_info',
#                  'cause', 'cause_state', 'other_cause', 'tenure', 'other_tenure',
#                  'days','hours',
#                  'dispatch_pw', 'dispatch_aerial',
#                 )


class BushfireCreateForm(BushfireCreateBaseForm):
    def __init__(self, *args, **kwargs):
        super(BushfireCreateForm, self).__init__(*args, **kwargs)

    #def clean_district(self):
    def clean(self):
        #import ipdb; ipdb.set_trace()
        district = self.cleaned_data['district']
        incident_no = self.cleaned_data['incident_no']
        #investigation_req = eval(self.cleaned_data['investigation_req'])
        #season = self.cleaned_data['season']
        #bushfire = Bushfire2.objects.filter(district=district, season=season, incident_no=incident_no)
        bushfire = Bushfire.objects.filter(district=district, incident_no=incident_no)
        if bushfire:
            raise ValidationError('There is already a Bushfire with this District and Incident No. {} - {} - {}'.format(district, incident_no))
        else:
            return self.cleaned_data


#class BushfireInitUpdateForm(forms.ModelForm):
#    days = forms.IntegerField(label='Days', required=False)
#    hours = forms.IntegerField(label='Hours', required=False)
#    dispatch_pw = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    dispatch_aerial = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    potential_fire_level = forms.ChoiceField(choices=Bushfire.FIRE_LEVEL_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    investigation_req = forms.ChoiceField(choices=YESNO_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    cause_state = forms.ChoiceField(choices=Bushfire.CAUSE_STATE_CHOICES, widget=forms.RadioSelect(renderer=HorizontalRadioRenderer))
#    class Meta:
#        model = Bushfire
#        fields = ('region', 'district', 'incident_no', 'job_code', 'dfes_incident_no',
#                  'name', 'year', 'potential_fire_level', 'field_officer', 'duty_officer', 'init_authorised_by', 'init_authorised_date',
#                  'media_alert_req', 'fire_position',
#                  'grid', 'arrival_area', 'fire_not_found',
#                  'fire_detected_date', 'dispatch_pw_date', 'dispatch_aerial_date', 'fuel_type',
#                  'assistance_req', 'assistance_details', 'communications', 'other_info',
#                  'cause', 'cause_state', 'other_cause', 'tenure', 'other_tenure',
#                  'days','hours',
#                  'dispatch_pw', 'dispatch_aerial',
#                 )

class BushfireInitUpdateForm(BushfireCreateBaseForm):
    def clean(self):
        """
        Form can be saved prior to sign-off, without checking req'd fields.
        Required fields are checked during Authorisation sign-off, therefore checking and adding error fields manually
        """
        req_fields = [
            #'region', 'district', 'incident_no', 'season', # these are delcared Required in models.py
            'name', 'potential_fire_level', 'init_authorised_by', 'init_authorised_date',
            #'first_attack',
            'cause',
            'field_officer',
            #'known_possible',
        ]

        req_dep_fields = { # required dependent fields
            'cause': 'other_cause',
#            'coord_type': {
#                'MGA': ['MGA Zone','MGA Easting','MGA Northing'],
#                }
        }

#        req_coord_fields = {
#            'MGA': ['mga_zone','mga_easting','mga_northing'],
#            'FD Grid': ['fd_letter','fd_number','fd_tenths'],
#            'Lat/Long': ['lat_decimal','lat_degrees','lat_minutes', 'lon_decimal','lon_degrees','lon_minutes'],
#        }

        if self.cleaned_data['init_authorised_by']:
            # check all required fields
            #import ipdb; ipdb.set_trace()
            [self.add_error(field, 'This field is required.') for field in req_fields if not self.cleaned_data.has_key(field) or not self.cleaned_data[field]]

            # check if 'Other' has been selected from drop down and field has been set
            for field in req_dep_fields.keys():
                if self.cleaned_data.has_key(field) and 'other' in str(self.cleaned_data[field]).lower():
                    other_field = self.cleaned_data[req_dep_fields[field]]
                    if not other_field:
                        self.add_error(req_dep_fields[field], 'This field is required.')

#            coord_type = [i[1] for i in Bushfire.COORD_TYPE_CHOICES if i[0]==self.cleaned_data['coord_type']]
#            if coord_type:
#                #import ipdb; ipdb.set_trace()
#                for field in req_coord_fields[coord_type[0]]:
#                    if self.cleaned_data.has_key(field) and not self.cleaned_data[field]:
#                        self.add_error(field, 'This field is required.')

            #import ipdb; ipdb.set_trace()
            #if missing_fields:
            #    raise ValidationError('Cannot Authorise, must input required fields: {}'.format(', '.join([i.replace('_', ' ').title() for i in missing_fields])))


class BaseActivityFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate activities
            2. required activities have been selected
        """
        #import ipdb; ipdb.set_trace()
        if any(self.errors):
            import ipdb; ipdb.set_trace()
            return

        activities = []
        dates = []
        duplicates = False
        required_activities = ['FIRE DETECTED*', 'FIRE REPORT COMPILED*']

        #import ipdb; ipdb.set_trace()
        for form in self.forms:
            if form.cleaned_data:
                activity = form.cleaned_data['activity'] if form.cleaned_data.has_key('activity') else None
                date = form.cleaned_data['date'] if form.cleaned_data.has_key('date') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    # Check that no two records have the same activity
                    if activity:
                        if activity.name in activities:
                            duplicates = True
                        activities.append(activity.name)

                    if duplicates:
                        form.add_error('activity', 'Duplicate: must be unique')

        # check required activities have been selected, only when main form has been authorised
        #import ipdb; ipdb.set_trace()
        if self.data.has_key('init_authorised_by') and self.data['init_authorised_by']:
            if not set(required_activities).issubset(activities) and self.forms:
                form.add_error('__all__', 'Must select required Activities: {}'.format(', '.join(required_activities)))

        if self.data.has_key('authorised_by'):
            if not set(required_activities).issubset(activities) and self.forms:
                form.add_error('__all__', 'Must select required Activities: {}'.format(', '.join(required_activities)))

#    class Meta:
#        model = Activity
#        exclude = ()


#class BaseAreaBurntFormSet(BaseInlineFormSet):
#    def clean(self):
#        """
#        Adds validation to check:
#            1. no duplicate (tenure, fuel_type) combination
#        """
#        if any(self.errors):
#            return
#
#        duplicates = False
#        tenures = []
#
#        #import ipdb; ipdb.set_trace()
#        for form in self.forms:
#            if form.cleaned_data:
#                tenure = form.cleaned_data['tenure'] if form.cleaned_data.has_key('tenure') else None
#                #area = form.cleaned_data['area'] if form.cleaned_data.has_key('area') else None
#                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False
#
#                if not remove:
#                    # Check that no two records have the same (tenure and fuel_type) combination
#                    #if tenure and fuel_type and area:
#					if tenure:
#                        if set([(tenure.name, fuel_type.name)]).issubset(tenures):
#                            duplicates = True
#                        tenures.append((tenure.name, fuel_type.name))
#
#                    if duplicates:
#                        form.add_error('tenure', 'Duplicate (Tenure - Fuel Type): must be unique')


class BaseAttendingOrganisationFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate organisation
        """
        if any(self.errors):
            return

        duplicates = False
        organisations = []

        #import ipdb; ipdb.set_trace()
        for form in self.forms:
            if form.cleaned_data:
                name = form.cleaned_data['name'] if form.cleaned_data.has_key('name') else None
                other = form.cleaned_data['other'] if form.cleaned_data.has_key('other') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    # Check that no two records have the same organisation (name)
                    if name:
                        if name in organisations:
                            duplicates = True
                        organisations.append(name)

                    if duplicates:
                        form.add_error('name', 'Duplicate Organisation: must be unique')

                    if name and 'other' in name.name.lower() and not other:
                        form.add_error('name', 'Must specify other organisation')


class BaseFireBehaviourFormSet(BaseInlineFormSet):
    def clean(self):
        """
        Adds validation to check:
            1. no duplicate fire_behaviour
            2. FDI is a required field
        """
        if any(self.errors):
            return

        duplicates = False
        fire_behaviours = []

        for form in self.forms:
            if form.cleaned_data:
                name = form.cleaned_data['name'] if form.cleaned_data.has_key('name') else None
                fuel_type = form.cleaned_data['fuel_type'] if form.cleaned_data.has_key('fuel_type') else None
                fuel_weight = form.cleaned_data['fuel_weight'] if form.cleaned_data.has_key('fuel_weight') else None
                fdi = form.cleaned_data['fdi'] if form.cleaned_data.has_key('fdi') else None
                ros = form.cleaned_data['ros'] if form.cleaned_data.has_key('ros') else None
                remove = form.cleaned_data['DELETE'] if form.cleaned_data.has_key('DELETE') else False

                if not remove:
                    # Check that no two records have the same organisation (name)
                    if name:
                        if name in fire_behaviours:
                            duplicates = True
                        fire_behaviours.append(name)

                    if duplicates:
                        form.add_error('name', 'Duplicate Fire Behaviour: must be unique')

                    if name and not fdi:
                        form.add_error('fdi', 'This field is required')


ActivityFormSet             = inlineformset_factory(Bushfire, Activity, formset=BaseActivityFormSet, extra=0, max_num=7, min_num=2, can_delete=True, validate_min=True, exclude=())
ResponseFormSet             = inlineformset_factory(Bushfire, Response, extra=0, max_num=13, min_num=1, exclude=())
#AreaBurntFormSet            = inlineformset_factory(Bushfire, AreaBurnt, formset=BaseAreaBurntFormSet, extra=0, min_num=1, validate_min=True, exclude=())
AreaBurntFormSet            = inlineformset_factory(Bushfire, AreaBurnt, extra=0, min_num=1, validate_min=True, exclude=())
GroundForcesFormSet         = inlineformset_factory(Bushfire, GroundForces, extra=0, max_num=3, min_num=1, exclude=())
AerialForcesFormSet         = inlineformset_factory(Bushfire, AerialForces, extra=0, max_num=2, min_num=1, exclude=())
AttendingOrganisationFormSet= inlineformset_factory(Bushfire, AttendingOrganisation, formset=BaseAttendingOrganisationFormSet, extra=0, max_num=11, min_num=1, validate_min=True, exclude=())
FireBehaviourFormSet        = inlineformset_factory(Bushfire, FireBehaviour, formset=BaseFireBehaviourFormSet, extra=0, max_num=3, min_num=1, validate_min=True, exclude=())
LegalFormSet                = inlineformset_factory(Bushfire, Legal, extra=0, max_num=5*12, min_num=1, exclude=())
PrivateDamageFormSet        = inlineformset_factory(Bushfire, PrivateDamage, extra=0, max_num=12, min_num=1, exclude=())
PublicDamageFormSet         = inlineformset_factory(Bushfire, PublicDamage, extra=0, min_num=1, exclude=())
InjuryFormSet               = inlineformset_factory(Bushfire, InjuryFatality, extra=0, max_num=7, min_num=1, exclude=())
DamageFormSet               = inlineformset_factory(Bushfire, Damage, extra=0, max_num=5, min_num=1, exclude=())
CommentFormSet              = inlineformset_factory(Bushfire, Comment, extra=0, min_num=1, exclude=())


"""
NEXT - For Testing ONLY
"""

#from bfrs.models import (BushfireTest2, Activity2)
#ActivityFormSet2            = inlineformset_factory(BushfireTest2, Activity2, extra=1, max_num=7, can_delete=True, exclude=())
#class BushfireCreateForm2(forms.ModelForm):
#    class Meta:
#        model = BushfireTest2
#        fields = ('region', 'district', 'incident_no', 'season', 'job_code',
#                  'name', 'potential_fire_level', 'init_authorised_by', 'init_authorised_date',
#                 )


from bfrs.models import (BushfireTest)
class BushfireTestForm(forms.ModelForm):
    class Meta:
        model = BushfireTest
        fields = ('region', 'district')



