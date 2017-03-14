#from django.db import models
from django.contrib.gis.db import models
from datetime import datetime, timedelta
from django.utils import timezone
from smart_selects.db_fields import ChainedForeignKey
from django.contrib.auth.models import User
from django.utils.encoding import python_2_unicode_compatible
from django.core.validators import MaxValueValidator, MinValueValidator
#from smart_selects.db_fields import ChainedForeignKey
from bfrs.base import Audit
from django.core.exceptions import (ValidationError)

import sys
import json


def current_finyear():
    year = datetime.now().year if datetime.now().month>7 else datetime.now().year-1
    return '/'.join([str(year), str(year+1)])


class Profile(models.Model):
    DEFAULT_GROUP = "Users"

    user = models.OneToOneField(User, related_name='profile')
    region = models.ForeignKey('Region', blank=True, null=True)
    district = ChainedForeignKey('District',
        chained_field="region", chained_model_field="region",
        show_all=False, auto_choose=True, blank=True, null=True)

    def to_dict(self):
        return dict(
            user_id=self.user.id,
            username=self.user.username,
            region_id=self.region.id if self.region else None,
            region=self.region if self.region else None,
            district_id=self.district.id if self.district else None,
            district=self.district if self.district else None
        )

    def __str__(self):
        return 'username: {}, region: {}, district: {}'.format(self.user.username, self.region, self.district)

    class Meta:
        default_permissions = ('add', 'change', 'view')


@python_2_unicode_compatible
class Region(models.Model):
    name = models.CharField(max_length=64, unique=True)

    def to_dict(self):
        """ Returns a dict of regions with their corresponding districts
        """
        qs=District.objects.filter(region_id=self.id)
        return dict(region=self.name, region_id=self.id, districts=[dict(district=q.name, id=q.id) for q in qs])

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class District(models.Model):
    region = models.ForeignKey(Region)
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=3)
    archive_date = models.DateField(
        null=True, blank=True, help_text="Archive this District (prevent from creating new ePFPs)"
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Bushfire(Audit):
    STATUS_INITIAL            = 1
    STATUS_INITIAL_AUTHORISED = 2
    STATUS_FINAL_DRAFT        = 3 # allows for CREATE of FINAL DRAFT REPORT
    STATUS_FINAL_AUTHORISED   = 4
    STATUS_REVIEW_DRAFT       = 5 # allows for CREATE of REVIEW DRAFT REPORT
    STATUS_REVIEWED           = 6
    REPORT_STATUS_CHOICES = (
        (STATUS_INITIAL, 'Initial'),
        (STATUS_INITIAL_AUTHORISED, 'Initial Authorised'),
        (STATUS_FINAL_DRAFT, 'Draft Final'),
        (STATUS_FINAL_AUTHORISED, 'Final Authorised'),
        (STATUS_REVIEW_DRAFT, 'Draft Review'),
        (STATUS_REVIEWED, 'Reviewed'),
    )

    FIRE_LEVEL_CHOICES = (
        (1, 1),
        (2, 2),
        (3, 3),
    )
    CAUSE_STATE_CHOICES = (
        (1, 'Known'),
        (2, 'Possible'),
    )

    # Common Fields
    region = models.ForeignKey(Region)
    district = ChainedForeignKey(
        District, chained_field="region", chained_model_field="region",
        show_all=False, auto_choose=True)

    name = models.CharField(max_length=100, verbose_name="Fire Name")
    incident_no = models.PositiveIntegerField(verbose_name="Fire Number", validators=[MinValueValidator(1), MaxValueValidator(999)])
    year = models.CharField(verbose_name="Financial Year", max_length=9, default=current_finyear())

    fire_level = models.PositiveSmallIntegerField(choices=FIRE_LEVEL_CHOICES)
    media_alert_req = models.BooleanField(verbose_name="Media Alert Required", default=False)
    park_trail_impacted = models.BooleanField(verbose_name="Park and/or trail potentially impacted", default=False)
    fuel_type = models.CharField(verbose_name='Fuel Type', max_length=64)
    cause = models.ForeignKey('Cause')
    cause_state = models.PositiveSmallIntegerField(choices=CAUSE_STATE_CHOICES)
    other_cause = models.CharField(verbose_name='Other Cause', max_length=64, null=True, blank=True)
    tenure = models.ForeignKey('Tenure')
    other_tenure = models.CharField(verbose_name='Other Tenure', max_length=64, null=True, blank=True)

    dfes_incident_no = models.PositiveIntegerField(verbose_name="DFES Fire Number", null=True, blank=True)
    job_code = models.PositiveIntegerField(verbose_name="job Code", null=True, blank=True)
    fire_position = models.CharField(verbose_name="Position of Fire", max_length=100, null=True, blank=True)

    # Point of Origin
    origin_point = models.PointField(null=True, blank=True, editable=True, help_text='Optional.')
    fire_boundary = models.MultiPolygonField(srid=4326, null=True, blank=True, editable=True, help_text='Optional.')
    #grid = models.CharField(verbose_name="Lat/Long, MGA, FD Grid", max_length=100, null=True, blank=True)
    fire_not_found = models.BooleanField(default=False)


    # FireBehaviour FS here
    #tenure = models.ForeignKey('Tenure', null=True, blank=True)
    #fuel = models.CharField(max_length=50, null=True, blank=True)
    assistance_req = models.BooleanField(default=False)
    assistance_details = models.CharField(max_length=64, null=True, blank=True)
    communications = models.CharField(verbose_name='Communication', max_length=50, null=True, blank=True)
    other_info = models.CharField(verbose_name='Other Information', max_length=100, null=True, blank=True)

    field_officer = models.ForeignKey(User, verbose_name="Field Officer", null=True, blank=True, related_name='init_field_officer')
    duty_officer = models.ForeignKey(User, verbose_name="Duty Officer", null=True, blank=True, related_name='init_duty_officer')
    init_authorised_by = models.ForeignKey(User, verbose_name="Authorised By", null=True, blank=True, related_name='init_authorised_by')
    init_authorised_date = models.DateTimeField(verbose_name='Authorised Date', null=True, blank=True)

    dispatch_pw = models.BooleanField(default=False)
    dispatch_aerial = models.BooleanField(default=False)
    dispatch_pw_date = models.DateTimeField(verbose_name='P&W Resource dispatched', null=True, blank=True)
    dispatch_aerial_date = models.DateTimeField(verbose_name='Aerial support dispatched', null=True, blank=True)
    fire_detected_date = models.DateTimeField(verbose_name='Fire Detected', null=True, blank=True)
    # we serialise/snapshot the initial and final reports when authorised
    initial_snapshot = models.TextField(null=True, blank=True)
    final_snapshot = models.TextField(null=True, blank=True)

    # FINAL Fire Report Fields
    fire_contained_date = models.DateTimeField(verbose_name='Fire Contained', null=True, blank=True)
    fire_controlled_date = models.DateTimeField(verbose_name='Fire Controlled', null=True, blank=True)
    fire_safe_date = models.DateTimeField(verbose_name='Fire Safe', null=True, blank=True)

    first_attack = models.ForeignKey('Agency', verbose_name="First Attack Agency", null=True, blank=True, related_name='first_attack')
    other_first_attack = models.CharField(verbose_name="Other First Attack Agency", max_length=50, null=True, blank=True)
    initial_control = models.ForeignKey('Agency', verbose_name="Initial Controlling Agency", null=True, blank=True, related_name='initial_control')
    other_initial_control = models.CharField(verbose_name="Other Initial Control Agency", max_length=50, null=True, blank=True)
    final_control = models.ForeignKey('Agency', verbose_name="Final Controlling Agency", null=True, blank=True, related_name='final_control')
    other_final_control = models.CharField(verbose_name="Other Final Control Agency", max_length=50, null=True, blank=True)

    #max_fire_level = models.PositiveSmallIntegerField(choices=FIRE_LEVEL_CHOICES, null=True, blank=True)
    arson_squad_notified = models.BooleanField(verbose_name="Arson Squad Notified", default=False)
    investigation_req = models.BooleanField(verbose_name="Investigation Required", default=False)
    offence_no = models.CharField(verbose_name="Police Offence No.", max_length=10, null=True, blank=True)
    #area = models.DecimalField(verbose_name="Final Fire Area (ha)", max_digits=12, decimal_places=1, validators=[MinValueValidator(0)], null=True, blank=True)
    area = models.FloatField(verbose_name="Final Fire Area (ha)", validators=[MinValueValidator(0)], null=True, blank=True)
    time_to_control = models.DurationField(verbose_name="Time to Control", null=True, blank=True)
    # Private Damage FS here
    # Public Damage FS here

    authorised_by = models.ForeignKey(User, verbose_name="Authorised By", null=True, blank=True, related_name='authorised_by')
    authorised_date = models.DateTimeField(verbose_name="Authorised Date", null=True, blank=True)

    reviewed_by = models.ForeignKey(User, verbose_name="Reviewed By", null=True, blank=True, related_name='reviewed_by')
    reviewed_date = models.DateTimeField(verbose_name="Reviewed Date", null=True, blank=True)

    report_status = models.PositiveSmallIntegerField(choices=REPORT_STATUS_CHOICES, editable=False, default=1)
    sss_id = models.CharField(verbose_name="Spatial Support System ID", max_length=64, null=True, blank=True)

    archive = models.BooleanField(verbose_name="Archive report", default=False)
#    def save(self, *args, **kwargs):
#        '''Overide save() to cleanse text input fields.
#        '''
#        self.name = unidecode(unicode(self.name))
#        if self.description:
#            self.description = unidecode(unicode(self.description))
#        super(Bushfire, self).save()

    @property
    def is_init_authorised(self):
        return True if self.init_authorised_by and self.init_authorised_date else False

    @property
    def is_final_authorised(self):
        return True if self.authorised_by and self.authorised_date else False

    @property
    def is_reviewed(self):
        #return True if self.reviewed_by and self.reviewed_date else False
        return False # no need to lock down Review report

    @property
    def can_create_final(self):
        return self.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED

    @property
    def can_create_review(self):
        return self.report_status >= Bushfire.STATUS_FINAL_AUTHORISED

    @property
    def has_restapi_write_perms(self):
        # TODO add auth logic
        return True

    @property
    def origin_coords(self):
        return 'Lat/Lon {}'.format(self.origin_point.get_coords()) if self.origin_point else None

    def user_unicode_patch(self):
        """ overwrite the User model's __unicode__() method """
        if self.first_name or self.last_name:
            return '%s %s' % (self.first_name, self.last_name)
        return self.username
    User.__unicode__ = user_unicode_patch

    def unique_id(self):
        return ' '.join(['BF', self.district.code, str(self.year), '{0:03d}'.format(self.incident_no)])

    def __str__(self):
        return ', '.join([self.name, self.district.name, self.year, self.incident_no])

    class Meta:
        unique_together = ('district', 'year', 'incident_no')
        default_permissions = ('add', 'change', 'delete', 'view')


@python_2_unicode_compatible
class Tenure(models.Model):
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ['id']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class FuelType(models.Model):
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ['name']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Cause(models.Model):
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ['id']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name

@python_2_unicode_compatible
class Agency(models.Model):

    name = models.CharField(max_length=50, verbose_name="Agency Name")
    code = models.CharField(verbose_name="Agency Short Code", max_length=10)

    class Meta:
        ordering = ['name']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class InjuryType(models.Model):
    name = models.CharField(max_length=25, verbose_name="Injury/Fatality Type")

    class Meta:
        ordering = ['name']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class DamageType(models.Model):
    name = models.CharField(max_length=50, verbose_name="Damage Type")

    class Meta:
        ordering = ['name']
        default_permissions = ('add', 'change', 'delete', 'view')

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class AreaBurnt(models.Model):
    tenure = models.ForeignKey(Tenure, related_name='tenures')
    area = models.DecimalField(verbose_name="Area (ha)", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    bushfire = models.ForeignKey(Bushfire, related_name='tenures_burnt')

#    def clean(self):
#        if self.bushfire.areas_burnt.all().count() == 0:
#            raise ValidationError("You must enter one Area Burnt record")

    def to_json(self):
        return json.dumps(self.to_dict)

    def to_dict(self):
        return dict(tenure=self.tenure.name, area=round(self.area,2))

    def __str__(self):
		return 'Tenure: {}, Area: {}'.format(self.tenure.name, self.area)

    class Meta:
        unique_together = ('bushfire', 'tenure',)
        default_permissions = ('add', 'change', 'delete', 'view')


@python_2_unicode_compatible
class Injury(models.Model):
    injury_type = models.ForeignKey(InjuryType)
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])
    bushfire = models.ForeignKey(Bushfire, related_name='injuries')

    def __str__(self):
        return 'Injury Type {}, Number {}'.format(self.injury_type, self.number)

    class Meta:
        unique_together = ('bushfire', 'injury_type',)
        default_permissions = ('add', 'change', 'delete', 'view')


@python_2_unicode_compatible
class Damage(models.Model):
    damage_type = models.ForeignKey(DamageType)
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])
    bushfire = models.ForeignKey(Bushfire, related_name='damages')

    def __str__(self):
        return 'Damage Type {}, Number {}'.format(self.damage_type, self.number)

    class Meta:
        unique_together = ('bushfire', 'damage_type',)
        default_permissions = ('add', 'change', 'delete', 'view')


#@python_2_unicode_compatible
#class Prescription(models.Model):
#    burn_id = models.CharField(max_length=7)
#
#    class Meta:
#        ordering = ['burn_id']
#
#    def __str__(self):
#        return self.burn_id


#@python_2_unicode_compatible
#class Direction(models.Model):
#    name = models.CharField(max_length=25)
#    code = models.CharField(max_length=3)
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class FrbEffect(models.Model):
#    name = models.CharField(max_length=50)
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class WaterBombEffect(models.Model):
#    name = models.CharField(max_length=50)
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class PriorityRating(models.Model):
#    name = models.CharField(max_length=50)
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name



#@python_2_unicode_compatible
#class ResponseType(models.Model):
#
#    name = models.CharField(max_length=50, verbose_name="Agency Name")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class Organisation(models.Model):
#    name = models.CharField(max_length=50, verbose_name="Organisation")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class InvestigationType(models.Model):
#    name = models.CharField(max_length=50, verbose_name="Investigation Type")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class LegalResultType(models.Model):
#    name = models.CharField(max_length=50, verbose_name="Legal Result Type")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class PublicDamageType(models.Model):
#    name = models.CharField(max_length=50, verbose_name="Public Damage Type")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#@python_2_unicode_compatible
#class PrivateDamageType(models.Model):
#    name = models.CharField(max_length=25, verbose_name="Private Damage Type")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name



#@python_2_unicode_compatible
#class ActivityType(models.Model):
#    name = models.CharField(max_length=25, verbose_name="Activity Type")
#
#    class Meta:
#        ordering = ['name']
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.name
#
#
#
#
#@python_2_unicode_compatible
#class Response(models.Model):
#    bushfire = models.ForeignKey(Bushfire, related_name='responses')
#    response = models.ForeignKey(ResponseType)
#    #response = models.PositiveSmallIntegerField(choices=RESPONSE_CHOICES)
#
#    def __str__(self):
#        return self.response.name
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    class Meta:
#        unique_together = ('bushfire', 'response',)
#        default_permissions = ('add', 'change', 'delete', 'view')



#@python_2_unicode_compatible
#class Comment(Audit):
#    comment = models.TextField()
#    bushfire = models.ForeignKey(Bushfire, related_name='comments')
#
#    class Meta:
#        default_permissions = ('add', 'change', 'delete', 'view')
#
#    def __str__(self):
#        return self.comment



class BushfireTest(models.Model):
    region = models.ForeignKey(Region)
    district = ChainedForeignKey(
        District, chained_field="region", chained_model_field="region",
        show_all=False, auto_choose=True)


#class BushfireTest2(Audit):
class BushfireTest2(models.Model):

    FIRE_LEVEL_CHOICES = (
        (1, 1),
        (2, 2),
        (3, 3),
    )

    region = models.ForeignKey(Region)
    district = ChainedForeignKey(
        District, chained_field="region", chained_model_field="region",
        show_all=False, auto_choose=True)

    name = models.CharField(max_length=100, verbose_name="Fire Name")
    incident_no = models.CharField(verbose_name="Fire Incident No.", max_length=10)
    season = models.CharField(max_length=9)
    dfes_incident_no = models.CharField(verbose_name="DFES Incident No.", max_length=10)
    job_code = models.CharField(verbose_name="Job Code", max_length=10, null=True, blank=True)
    fire_level = models.PositiveSmallIntegerField(choices=FIRE_LEVEL_CHOICES)

    init_authorised_by = models.ForeignKey(User, verbose_name="Authorised By", blank=True, null=True)
    init_authorised_date = models.DateTimeField(verbose_name='Authorised Date', default=timezone.now, null=True, blank=True)




