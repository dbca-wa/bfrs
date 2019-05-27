import sys
import json
from datetime import datetime, timedelta
import pytz

from django.contrib.gis.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.encoding import python_2_unicode_compatible
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import (ValidationError)
from django.conf import settings
from django.core import serializers
from django.utils.safestring import mark_safe
from django.core.exceptions import ObjectDoesNotExist

from smart_selects.db_fields import ChainedForeignKey
import LatLon
import reversion

from bfrs.base import Audit,DictMixin


SNAPSHOT_INITIAL = 1
SNAPSHOT_FINAL = 2
SNAPSHOT_TYPE_CHOICES = (
    (SNAPSHOT_INITIAL, 'Initial'),
    (SNAPSHOT_FINAL, 'Final'),
)

User.OTHER = User.objects.get(username='other')

def current_finyear():
    return datetime.now().year if datetime.now().month>6 else datetime.now().year-1

def reporting_years():
    """ Returns: [[2016, '2016/2017'], [2017, '2017/2018']] """
    try:
        yrs = list(Bushfire.objects.values_list('reporting_year', flat=True).distinct())
        finyear = current_finyear()
        for y in (finyear,finyear + 1):
            if y not in yrs:
                yrs.append(y)
        yrs.sort()
        return [[yr, '/'.join([str(yr),str(yr+1)])] for yr in yrs]
    except:
        return [[None, None]]
        #return [[2016, '2016/2017'], [2017, '2017/2018']]

def get_field(obj,field):
    if "." in field:
        field = field.split(".")
        result = getattr(obj,field[0]) if hasattr(obj,field[0]) else None
        if not result:
            return None
        for f in field[1:]:
            if not result:
                return None
            elif isinstance(result,dict):
                result = result.get(f)
            elif isinstance(result,(list,tuple)):
                result = result[int(f)] if int(f) < len(result) else None
            else:
                result = getattr(result,f) if hasattr(result,f) else None
        return result
    else:
        return getattr(obj,field) if hasattr(obj,field) else None

def check_mandatory_fields(obj, fields, dep_fields, formsets):
    """
    Method to check all required fields have been fileds before allowing Submit/Authorise of report.

    The report can be saved with missing data - so most fields are non-mandatory (as defined in the Model).
    Idea is to fill in report over time as and when info becomes available.

    However, the report cannot be Submitted/Authorosed unless a given set of fields have been filled.

    fields    - basic fields
    dep_field - dependent fields (if one field has a value, check that the other has been filled)
    formsets  - fields in formsets
    """
    missing = []
    for field in fields:
        is_active_f = None
        field_label = None
        if isinstance(field,tuple):
            #field label is provided
            if len(field) == 1:
                field = field[0]
            elif len(field) == 2:
                field_label = field[1]
                field = field[0]
            elif len(field) >= 3:
                field_label = field[1]
                is_active_f = field[2]
                field = field[0]
            else:
                continue

        if is_active_f and not is_active_f(obj):
            continue

        value = get_field(obj,field)
        if value is None or value=='':
            if field_label:
                missing.append(field_label)
            else:
                try:
                    missing.append(Bushfire._meta.get_field(field).verbose_name)
                except:
                    missing.append(field)
            


    if obj.fire_not_found and obj.is_init_authorised:
        # no need to check these
        #dep_fields = {}
        formsets = []

    for field, dep_sets in dep_fields.iteritems():
        for dep_set in dep_sets:
            # next line checks for normal Field or Enumerated list field (i.e. '.name')
            is_active_f = None
            if isinstance(field,tuple):
                if len(field) == 1:
                    field = field[0]
                elif len(field) >= 2:
                    is_active_f = field[1]
                    field = field[0]
                else:
                    continue

            try:
                if is_active_f and not is_active_f(obj):
                    continue

                if hasattr(obj, field) and getattr(obj, field)==dep_set[0]:
                    for dep in dep_set[1:]:
                        if isinstance(dep,tuple):
                            #field label is provided
                            dep_label = dep[1]
                            dep = dep[0]
                        else:
                            dep_label = None

                        value = get_field(obj,dep)
                        if value is None or (isinstance(value, (str, unicode)) and not value.strip()) or (isinstance(value,(list,tuple)) and not value):
                            # field is unset or empty string
                            if dep_label:
                                missing.append(dep_label)
                            else:
                                try:
                                    missing.append(Bushfire._meta.get_field(dep).verbose_name)
                                except:
                                    missing.append(dep)
            except:
                pass

    for fs in formsets:
        if fs == 'damages':
            if (obj.damage_unknown):
                continue
            elif getattr(obj, fs) is None or not getattr(obj, fs).all():
                missing.append(fs)

        if fs == 'injuries':
            if (obj.injury_unknown):
                continue
            elif getattr(obj, fs) is None or not getattr(obj, fs).all():
                missing.append(fs)

    # initial fire boundary required for fires > 2 ha
    if not obj.initial_area_unknown:
        if not obj.initial_area and obj.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
            missing.append("Must enter Area of Arrival, if area < {}ha".format(settings.AREA_THRESHOLD))

    if not obj.fire_not_found and obj.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED:
        if not obj.area_limit and (obj.area < settings.AREA_THRESHOLD or obj.area is None) and not obj.final_fire_boundary:
            missing.append("Final fire shape must be uploaded for fires > {}ha".format(settings.AREA_THRESHOLD))

    return missing


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

@python_2_unicode_compatible
class CaptureMethod(models.Model):
    OTHER_CODE = "999"
    code = models.CharField(max_length=32,unique=True)
    desc = models.CharField(max_length=128)

    def to_dict(self):
        """ Returns a dict of regions with their corresponding districts
        """
        qs=District.objects.filter(region_id=self.id)
        return dict(id=self.id, code=self.code, desc=self.desc)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.code


@python_2_unicode_compatible
class Region(models.Model):
    name = models.CharField(max_length=64, unique=True)
    forest_region = models.BooleanField(default=False)

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
    archive_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class BushfireBase(Audit,DictMixin):
    STATUS_INITIAL                = 1
    STATUS_INITIAL_AUTHORISED     = 2
    STATUS_FINAL_AUTHORISED       = 3
    STATUS_REVIEWED               = 4
    STATUS_INVALIDATED            = 5
    STATUS_MISSING_FINAL          = 6 # This is not really a status, and is never set - used for filtering qs only
    STATUS_MERGED                 = 100
    STATUS_DUPLICATED             = 101
    REPORT_STATUS_CHOICES = (
        (STATUS_INITIAL, 'Initial Fire Report'),
        (STATUS_INITIAL_AUTHORISED, 'Notifications Submitted'),
        (STATUS_FINAL_AUTHORISED, 'Report Authorised'),
        (STATUS_REVIEWED, 'Reviewed'),
        (STATUS_INVALIDATED, 'Invalidated'),
        (STATUS_MISSING_FINAL, 'Outstanding Fires'), # This is not really a status, and is never set - used for filtering qs only
        (STATUS_MERGED, 'Merged'),
        (STATUS_DUPLICATED, 'Duplicated')
    )
    REPORT_STATUS_MAP = dict(REPORT_STATUS_CHOICES)

    FIRE_LEVEL_CHOICES = (
        (1, 1),
        (2, 2),
        (3, 3),
    )

    CAUSE_STATE_KNOWN    = 1
    CAUSE_STATE_POSSIBLE = 2
    CAUSE_STATE_CHOICES = (
        (CAUSE_STATE_KNOWN, 'Known'),
        (CAUSE_STATE_POSSIBLE, 'Possible'),
    )

    DISPATCH_PW_YES        = 1
    DISPATCH_PW_NO         = 2
    DISPATCH_PW_MONITORING = 3
    DISPATCH_PW_CHOICES = (
        (DISPATCH_PW_YES, 'Yes'),
        (DISPATCH_PW_NO, 'No'),
        #(DISPATCH_PW_MONITORING, 'Monitoring only'),
    )

    # TODO - Comment out Assistance section below also the two model fields - confirm if form no longer requires these (Kanboard #3697)
    ASSISTANCE_YES     = 1
    ASSISTANCE_NO      = 2
    ASSISTANCE_UNKNOWN = 3
    ASSISTANCE_CHOICES = (
        (ASSISTANCE_YES, 'Yes'),
        (ASSISTANCE_NO, 'No'),
        (ASSISTANCE_UNKNOWN, 'Unknown'),
    )

    IGNITION_POINT_PRIVATE = 1
    IGNITION_POINT_CROWN  = 2
    IGNITION_POINT_CHOICES = (
        (IGNITION_POINT_PRIVATE, 'Private'),
        (IGNITION_POINT_CROWN, 'Crown'),
    )

    FIRE_BOMBING_RESOURCES = [
        (1,"Fixed Wing"),
        (2,"Helitak"),
        (3,"Aerial Intelligence"),
    ]
    FIRE_BOMBING_ACTIVATION_CRITERIAS = [
        (1,"Public Safety at Risk"),
        (2,"Fire Crews in Imminent Danger"),
        (3,"Assets at Imminent Risk"),
        (4,"Known high fuel loads and likelihood of excessive ROS and/or extreme fire danger"),
    ]
    FIRE_BOMBING_ACTIVATION_CRITERIAS_LATEX = [
        (1,"Public Safety at Risk"),
        (2,"Fire Crews in Imminent Danger"),
        (3,"Assets at Imminent Risk"),
        (4,"Known high fuel loads and likelihood of excessive ROS \\\\and/or extreme fire danger"),
    ]
    FIRE_BOMBING_RESPONSES = [
        (1,mark_safe("Zone 2/2A<br>(Perth Hills Response)")),
        (2,mark_safe("Enhanced<br> (Metropolitan)")),
        (3,mark_safe("I/O Zone<br>(Capes Response)")),
        (4,mark_safe("SWZR<br>(Bunbury Response)")),
    ]
    FIRE_BOMBING_RESPONSES_LATEX = [
        (1,mark_safe("Zone 2/2A\\\\{\\small( Perth Hills Response)}")),
        (2,mark_safe("Enhanced\\\\{\\small (Metropolitan)}")),
        (3,mark_safe("I/O Zone\\\\{\\small (Capes Response)}")),
        (4,mark_safe("SWZR\\\\{\\small (Bunbury Response)}")),
    ]

    # Common Fields
    region = models.ForeignKey(Region, verbose_name="Region")
    district = ChainedForeignKey(
        District, chained_field="region", chained_model_field="region",
        show_all=False, auto_choose=True, verbose_name="District")

    name = models.CharField(max_length=100, verbose_name="Fire Name")
    year = models.PositiveSmallIntegerField(verbose_name="Financial Year", default=current_finyear())
    reporting_year = models.PositiveSmallIntegerField(verbose_name="Reporting Year", default=current_finyear(), blank=True)

    prob_fire_level = models.PositiveSmallIntegerField(verbose_name='Probable fire level', choices=FIRE_LEVEL_CHOICES, null=True, blank=True)
    max_fire_level = models.PositiveSmallIntegerField(verbose_name='Maximum fire level', choices=FIRE_LEVEL_CHOICES, null=True, blank=True)
    media_alert_req = models.NullBooleanField(verbose_name="Media Alert Required", null=True)
    park_trail_impacted = models.NullBooleanField(verbose_name="Park and/or trail potentially impacted", null=True)
    cause = models.ForeignKey('Cause', verbose_name="Fire Cause", null=True, blank=True)
    cause_state = models.PositiveSmallIntegerField(verbose_name="Fire Cause State (Known/Possible)", choices=CAUSE_STATE_CHOICES, null=True, blank=True)
    other_cause = models.CharField(verbose_name='Other Fire Cause', max_length=64, null=True, blank=True)
    prescribed_burn_id = models.CharField(verbose_name='Prescribed Burn ID', max_length=7, null=True, blank=True)
    tenure = models.ForeignKey('Tenure', verbose_name="Tenure of Ignition Point", null=True, blank=True)

    dfes_incident_no = models.CharField(verbose_name='DFES Fire Number', max_length=32, null=True, blank=True)
    job_code = models.CharField(verbose_name="Job Code", max_length=12, null=True, blank=True)
    fire_position = models.CharField(verbose_name="Position of Fire", max_length=100, null=True, blank=True)
    fire_position_override = models.BooleanField(verbose_name="SSS override", default=False)

    # Point of Origin
    origin_point = models.PointField(verbose_name="Point of Origin", editable=True)
    origin_point_mga = models.CharField(verbose_name='Point of Origin (MGA)', max_length=64, null=True, blank=True)
    origin_point_grid = models.CharField(verbose_name='Point of Origin (GRID)', max_length=16, null=True, blank=True)
    fire_boundary = models.MultiPolygonField(srid=4326, null=True, blank=True, editable=True, help_text='Optional.')
    fire_not_found = models.BooleanField(default=False)
    fire_monitored_only = models.BooleanField(default=False)
    final_fire_boundary = models.BooleanField(default=False)
    fb_validation_req = models.NullBooleanField(verbose_name="Fire Boundary Validation Required?", null=True)
    other_info = models.CharField(verbose_name='Other Information', max_length=250, null=True, blank=True)

    field_officer = models.ForeignKey(User, verbose_name="Field Officer", null=True, blank=True, related_name='%(class)s_init_field_officer')
    other_field_officer = models.CharField(verbose_name="Other Field Officer Name", max_length=75, null=True, blank=True)
    other_field_officer_agency = models.CharField(verbose_name="Other Field Officer Agency", max_length=36, null=True, blank=True)
    other_field_officer_phone = models.CharField(verbose_name="Other Field Officer Phone", max_length=24, null=True, blank=True)

    duty_officer = models.ForeignKey(User, verbose_name="Duty Officer", null=True, blank=True, related_name='%(class)s_init_duty_officer')
    init_authorised_by = models.ForeignKey(User, verbose_name="Initial Authorised By", null=True, blank=True, related_name='%(class)s_init_authorised_by')
    init_authorised_date = models.DateTimeField(verbose_name='Initial Authorised Date', null=True, blank=True)

    dispatch_pw = models.PositiveSmallIntegerField(verbose_name="P&W Resource dispatched", choices=DISPATCH_PW_CHOICES, null=True, blank=True)
    dispatch_aerial = models.NullBooleanField(verbose_name="Aerial support requested", null=True)
    dispatch_pw_date = models.DateTimeField(verbose_name='P&W Resource dispatch date', null=True, blank=True)
    dispatch_aerial_date = models.DateTimeField(verbose_name='Aerial support request date', null=True, blank=True)
    fire_detected_date = models.DateTimeField(verbose_name='Date and time fire detected', null=True, blank=True)

    # FINAL Fire Report Fields
    fire_contained_date = models.DateTimeField(verbose_name='Date fire Contained', null=True, blank=True)
    fire_controlled_date = models.DateTimeField(verbose_name='Date fire Controlled', null=True, blank=True)
    fire_safe_date = models.DateTimeField(verbose_name='Date fire inactive', null=True, blank=True)

    first_attack = models.ForeignKey('Agency', verbose_name="Initial Attack Agency", null=True, blank=True, related_name='%(class)s_first_attack')
    other_first_attack = models.CharField(verbose_name="Other Initial Attack Agency", max_length=50, null=True, blank=True)
    initial_control = models.ForeignKey('Agency', verbose_name="Initial Controlling Agency", null=True, blank=True, related_name='%(class)s_initial_control')
    other_initial_control = models.CharField(verbose_name="Other Initial Control Agency", max_length=50, null=True, blank=True)
    final_control = models.ForeignKey('Agency', verbose_name="Final Controlling Agency", null=True, blank=True, related_name='%(class)s_final_control')
    other_final_control = models.CharField(verbose_name="Other Final Control Agency", max_length=50, null=True, blank=True)

    arson_squad_notified = models.NullBooleanField(verbose_name="Arson Squad Notified", null=True)
    investigation_req = models.NullBooleanField(verbose_name="Investigation Required", null=True)
    offence_no = models.CharField(verbose_name="Police Offence No.", max_length=15, null=True, blank=True)
    initial_area = models.FloatField(verbose_name="Area of fire at arrival (ha)", validators=[MinValueValidator(0)], null=True, blank=True)
    initial_area_unknown = models.BooleanField(default=False)
    area = models.FloatField(verbose_name="Final Fire Area (ha)", validators=[MinValueValidator(0)], null=True, blank=True)
    area_limit = models.BooleanField(verbose_name="Area < 2ha", default=False)
    other_area = models.FloatField(verbose_name="Other Area (ha)", validators=[MinValueValidator(0)], null=True, blank=True)
    damage_unknown = models.BooleanField(verbose_name="Damages to report?", default=False)
    injury_unknown = models.BooleanField(verbose_name="Injuries to report?", default=False)

    authorised_by = models.ForeignKey(User, verbose_name="Authorised By", null=True, blank=True, related_name='%(class)s_authorised_by')
    authorised_date = models.DateTimeField(verbose_name="Authorised Date", null=True, blank=True)

    reviewed_by = models.ForeignKey(User, verbose_name="Reviewed By", null=True, blank=True, related_name='%(class)s_reviewed_by')
    reviewed_date = models.DateTimeField(verbose_name="Reviewed Date", null=True, blank=True)

    report_status = models.PositiveSmallIntegerField(choices=REPORT_STATUS_CHOICES, editable=False, default=1)
    sss_data = models.TextField(verbose_name="SSS REST Api Dict", null=True, blank=True)

    archive = models.BooleanField(verbose_name="Archive report", default=False)
    invalid_details = models.CharField(verbose_name="Reason for invalidating", max_length=64, null=True, blank=True)

    # recursive relationship - an object that has a many-to-many relationship with itself
    valid_bushfire = models.ForeignKey('self', null=True, related_name='%(class)s_invalidated')

    fireboundary_uploaded_by = models.ForeignKey(User,editable=False,null=True,blank=True)
    fireboundary_uploaded_date = models.DateTimeField(verbose_name='Date fireboundary uploaded', null=True, blank=True,editable=False)

    capturemethod = models.ForeignKey(CaptureMethod,editable=True,null=True,blank=True)
    other_capturemethod = models.CharField(verbose_name="Other Capture Methdod", max_length=128, editable=True, null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def report_status_name(self):
        return self.REPORT_STATUS_MAP.get(self.report_status,"Unknown")

    @property
    def can_submit(self):
        return True if not self.missing_initial() else False

    @property
    def can_authorise(self):
        if not self.missing_final() and self.report_status == self.STATUS_INITIAL_AUTHORISED:
            return True
        return False

    @property
    def can_review(self):
        # can only review if spatial data (final_fire_boundary == True) has been uploaded
        if not self.fire_not_found and self.area and self.final_fire_boundary and self.is_final_authorised:
            return True
        return False

    @property
    def is_init_authorised(self):
        return True if self.init_authorised_by and self.init_authorised_date and self.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED and self.report_status < Bushfire.STATUS_INVALIDATED else False

    @property
    def is_final_authorised(self):
        return True if self.authorised_by and self.authorised_date and self.report_status >= Bushfire.STATUS_FINAL_AUTHORISED and self.report_status < Bushfire.STATUS_INVALIDATED else False

    @property
    def is_reviewed(self):
        return True if self.reviewed_by and self.reviewed_date and self.report_status >= Bushfire.STATUS_REVIEWED and self.report_status < Bushfire.STATUS_INVALIDATED else False

    @property
    def is_invalidated(self):
        return self.report_status >= Bushfire.STATUS_INVALIDATED

    @property
    def other_contact(self):
        return 'Name: {}, Agency: {}, Phone: {}'.format(self.other_field_officer, self.other_field_officer_agency, self.other_field_officer_phone)

    @property
    def can_create_final(self):
        return self.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED

    @property
    def fire_cause(self):
        if not self.cause:
            return ""
        
        cause = ""
        if self.cause == Cause.OTHER:
            cause = self.other_cause or ""
        else:
            cause = self.cause.name

        if self.cause_state == self.CAUSE_STATE_KNOWN:
            return "{} (Known)".format(cause)
        elif self.cause_state == self.CAUSE_STATE_POSSIBLE:
            return "{} (Possible)".format(cause)
        else:
            return cause

    @property
    def fire_number_slug(self):
        if not self.fire_number:
            return ""

        if not hasattr(self,"_fire_number_slug"):
            self._fire_number_slug = self.fire_number.replace(' ','-')
        
        return self._fire_number_slug

    @property
    def origin_coords(self):
        return 'Lon/Lat ({}, {})'.format(round(self.origin_point.get_x(), 2), round(self.origin_point.get_y(), 2)) if self.origin_point else None

    @property
    def origin_latlon(self):
        if not self.origin_point:
            return None
        
        if not hasattr(self,"_origin_latlon"):
            self._origin_latlon = LatLon.LatLon(LatLon.Latitude(self.origin_point.get_y()),LatLon.Longitude(self.origin_point.get_x()))
        
        return self._origin_latlon


    @property
    def origin_geo(self):
        if not self.origin_point:
            return None

        c=self.origin_latlon
        latlon = c.to_string('d% %m% %S% %H')
        lat = latlon[0].split(' ')
        lon = latlon[1].split(' ')

        # need to format float number (seconds) to 1 dp
        lon[2] = str(round(eval(lon[2]), 1))
        lat[2] = str(round(eval(lat[2]), 1))

        # Degrees Minutes Seconds Hemisphere
        lat_str = lat[0] + u'\N{DEGREE SIGN} ' + lat[1].zfill(2) + '\' ' + lat[2].zfill(4) + '\" ' + lat[3]
        lon_str = lon[0] + u'\N{DEGREE SIGN} ' + lon[1].zfill(2) + '\' ' + lon[2].zfill(4) + '\" ' + lon[3]

        return 'Lat/Lon ' + lat_str + ', ' + lon_str

    @property
    def origin_latex(self):
        if not self.origin_point:
            return ""

        c=self.origin_latlon
        latlon = c.to_string('d% %m% %S% %H')
        lat = latlon[0].split(' ')
        lon = latlon[1].split(' ')

        # need to format float number (seconds) to 1 dp
        lon[2] = str(round(eval(lon[2]), 1))
        lat[2] = str(round(eval(lat[2]), 1))

        # Degrees Minutes Seconds Hemisphere
        lat_str = lat[0] + u'$^\circ$ ' + lat[1].zfill(2) + '\' ' + lat[2].zfill(4) + '\" ' + lat[3]
        lon_str = lon[0] + u'$^\circ$ ' + lon[1].zfill(2) + '\' ' + lon[2].zfill(4) + '\" ' + lon[3]

        return 'Lat/Lon ' + lat_str + ', ' + lon_str

    @property
    def initial_control_value(self):
        if not self.initial_control:
            return ""
        elif self.initial_control == Agency.OTHER:
            return self.other_initial_control
        else:
            return self.initial_control.name


class BushfireSnapshot(BushfireBase):

    fire_number = models.CharField(max_length=15, verbose_name="Fire Number")
    sss_id = models.CharField(verbose_name="Unique SSS ID", max_length=64, null=True, blank=True)

    snapshot_type = models.PositiveSmallIntegerField(choices=SNAPSHOT_TYPE_CHOICES)
    action = models.CharField(verbose_name="Action Type", max_length=50)
    bushfire = models.ForeignKey('Bushfire', related_name='snapshots')

    @property
    def fire_bombing(self):
        if not hasattr(self,"_fire_bombing"):
            try:
                fire_bombing = BushfirePropertySnapshot.objects.get(snapshot=self,name="fire_bombing").value
                if fire_bombing is None:
                    fire_bombing = {}
                else:
                    fire_bombing = json.loads(fire_bombing)
            except BushfirePropertySnapshot.DoesNotExist:
                fire_bombing = {}

            self._fire_bombing = fire_bombing

        return self._fire_bombing

    def __str__(self):
        return ', '.join([self.fire_number, self.get_snapshot_type_display()])


class Bushfire(BushfireBase):

    fire_number = models.CharField(max_length=15, verbose_name="Fire Number", unique=True)
    sss_id = models.CharField(verbose_name="Unique SSS ID", max_length=64, null=True, blank=True, unique=True)

    class Meta:
        permissions = (
            ("final_authorise_bushfire","Can final authorise bushfire"),
        )

    @property
    def fire_bombing(self):
        if not hasattr(self,"_fire_bombing"):
            try:
                fire_bombing = BushfireProperty.objects.get(bushfire=self,name="fire_bombing").value
                if fire_bombing is None:
                    fire_bombing = {}
                else:
                    fire_bombing = json.loads(fire_bombing)
            except BushfireProperty.DoesNotExist:
                fire_bombing = {}

            self._fire_bombing = fire_bombing

        return self._fire_bombing

    def save_properties(self,update_fields = None):
        if not update_fields:
            return
        if any([field.startswith("fire_bombing.") for field in update_fields]):
            #save fire_bombing
            if not self.dispatch_aerial:
                #fire bombing not required
                BushfireProperty.objects.filter(bushfire=self,name="fire_bombing").delete()
                return

            #initialize fire bombing data
            if not self.fire_bombing.get("sar_arrangements"):
                self.fire_bombing["sar_arrangements"] = "Default SAR state air desk"

            BushfireProperty.objects.update_or_create(bushfire=self,name="fire_bombing",defaults={"value":json.dumps(self.fire_bombing)})

    def user_unicode_patch(self):
        """ overwrite the User model's __unicode__() method """
        if self.first_name or self.last_name:
            return '%s %s' % (self.first_name, self.last_name)
        return self.username
    User.__unicode__ = user_unicode_patch

    def __str__(self):
        return ', '.join([self.fire_number])

    @property
    def initial_snapshot(self):
        qs = self.snapshots.filter(snapshot_type=SNAPSHOT_INITIAL)
        return qs.latest('created') if len(qs)>0 and self.is_init_authorised else None

    @property
    def final_snapshot(self):
        qs = self.snapshots.filter(snapshot_type=SNAPSHOT_FINAL)
        return qs.latest('created') if len(qs)>0 and self.is_final_authorised else None

    @property
    def snapshot_list(self):
        return self.snapshots.all().order_by('created')

    def next_id(self, district):
        ids = map(int, [i.fire_number.split(' ')[-1] for i in Bushfire.objects.filter(district=district, year=self.year)])
        return max(ids) + 1 if ids else 1

    @property
    def linked_valid_bushfire(self):
        # check forwards
        for linked in self.linked.all():
            if linked.linked_bushfire.report_status != Bushfire.STATUS_INVALIDATED:
                return linked.linked_bushfire

        # check backwards
        for linked in self.linkedbushfire_set.all():
            if linked.linked_bushfire.report_status != Bushfire.STATUS_INVALIDATED:
                return linked.linked_bushfire

    def clean(self):
        # create the bushfire fire number
        if not self.id and not self.fire_number:
            try:
                self.fire_number = ' '.join(['BF', str(self.year), self.district.code, '{0:03d}'.format(self.next_id(self.district))])
            except:
                raise ValidationError('Could not create unique fire number')

    def full_clean(self, *args, **kwargs):
        return self.clean()

    def save(self, *args, **kwargs):
        self.full_clean(*args, **kwargs)
        super(Bushfire, self).save(*args, **kwargs)

    @property
    def sss_data_to_dict(self):
        return json.loads(self.sss_data) if self.sss_data else None

    @property
    def finyear_display(self):
        return '/'.join([str(year), str(year+1)])


    def missing_initial(self):
        missing_fields = check_mandatory_fields(self, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS)
        l = []
        for field in missing_fields:
            l.append(
                ' '.join([i.capitalize() for i in field.split('_')])
            )
        return l

    def missing_final(self):
        missing_fields = check_mandatory_fields(self, AUTH_MANDATORY_FIELDS, AUTH_MANDATORY_DEP_FIELDS)
        l = []
        for field in missing_fields:
            l.append(
                ' '.join([i.capitalize() for i in field.split('_')])
            )
        return l

@python_2_unicode_compatible
class Tenure(models.Model):
    name = models.CharField(verbose_name='Tenure category', max_length=200)
    report_name = models.CharField(verbose_name='Tenure category report name', max_length=200,default="")
    report_group = models.CharField(verbose_name='Tenure category report group', max_length=32,default="")
    report_order = models.PositiveSmallIntegerField(verbose_name='order in annual report',default=1)
    report_group_order = models.PositiveSmallIntegerField(verbose_name='group order in annual report',default=1)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name

try:
    Tenure.OTHER = Tenure.objects.get(name="Other")
except ObjectDoesNotExist as ex:
    raise
except:
    Tenure.OTHER = None

try:
    Tenure.PRIVATE_PROPERTY = Tenure.objects.get(name="Private Property")
except ObjectDoesNotExist as ex:
    raise
except:
    Tenure.PRIVATE_PROPERTY = None

try: 
    Tenure.OTHER_CROWN = Tenure.objects.get(name="Other Crown")
except ObjectDoesNotExist as ex:
    raise
except:
    Tenure.OTHER_CROWN = None



@python_2_unicode_compatible
class TenureMapping(models.Model):
    tenure = models.ForeignKey(Tenure)
    name = models.CharField(verbose_name='Tenure sub category', max_length=200)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "{}.{}".format(self.tenure.name,self.name)

@python_2_unicode_compatible
class FuelType(models.Model):
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Cause(models.Model):
    name = models.CharField(max_length=50)
    report_name = models.CharField(max_length=50,default="")
    report_order = models.PositiveSmallIntegerField(verbose_name='order in annual report',default=1)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name

try:
    Cause.OTHER = Cause.objects.get(name="Other (specify)")
except ObjectDoesNotExist as ex:
    raise
except:
    Cause.OTHER = None

try:
    Cause.ESCAPE_DPAW_BURNING = Cause.objects.get(name="Escape P&W burning")
except ObjectDoesNotExist as ex:
    raise
except:
    Cause.ESCAPE_DPAW_BURNING = None


@python_2_unicode_compatible
class Agency(models.Model):

    name = models.CharField(max_length=50, verbose_name="Agency Name")
    code = models.CharField(verbose_name="Agency Short Code", max_length=10)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name

Agency.OTHER = Agency.objects.get(code="OTHER")
Agency.DBCA = Agency.objects.get(code="DBCA")

@python_2_unicode_compatible
class InjuryType(models.Model):
    name = models.CharField(max_length=25, verbose_name="Injury/Fatality Type")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class DamageType(models.Model):
    name = models.CharField(max_length=50, verbose_name="Damage Type")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class AreaBurntBase(models.Model):
    tenure = models.ForeignKey(Tenure, related_name='%(class)s_tenures')
    area = models.DecimalField(verbose_name="Area (ha)", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], null=True, blank=True)

    def to_json(self):
        return json.dumps(self.to_dict)

    def to_dict(self):
        return dict(tenure=self.tenure.name, area=round(self.area,2))

    def __str__(self):
        return 'Tenure: {}, Area: {}'.format(self.tenure.name, self.area)

    class Meta:
        abstract = True

class AreaBurnt(AreaBurntBase):
    bushfire = models.ForeignKey(Bushfire, related_name='tenures_burnt')

    class Meta:
        unique_together = ('bushfire', 'tenure',)


class AreaBurntSnapshot(AreaBurntBase, Audit):
    snapshot_type = models.PositiveSmallIntegerField(choices=SNAPSHOT_TYPE_CHOICES)
    snapshot = models.ForeignKey(BushfireSnapshot, related_name='tenures_burnt_snapshot')

    class Meta:
        unique_together = ('tenure', 'snapshot')


@python_2_unicode_compatible
class InjuryBase(models.Model):
    injury_type = models.ForeignKey(InjuryType)
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])

    def __str__(self):
        return 'Injury Type {}, Number {}'.format(self.injury_type, self.number)

    class Meta:
        abstract = True


class Injury(InjuryBase):
    bushfire = models.ForeignKey(Bushfire, related_name='injuries')

    class Meta:
        unique_together = ('bushfire', 'injury_type',)


class InjurySnapshot(InjuryBase, Audit):
    snapshot_type = models.PositiveSmallIntegerField(choices=SNAPSHOT_TYPE_CHOICES)
    snapshot = models.ForeignKey(BushfireSnapshot, related_name='injury_snapshot')

    class Meta:
        unique_together = ('injury_type', 'snapshot')


class DamageBase(models.Model):
    damage_type = models.ForeignKey(DamageType)
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])

    def __str__(self):
        return 'Damage Type {}, Number {}'.format(self.damage_type, self.number)

    class Meta:
        abstract = True


class Damage(DamageBase):
    bushfire = models.ForeignKey(Bushfire, related_name='damages')

    class Meta:
        unique_together = ('bushfire', 'damage_type',)


class DamageSnapshot(DamageBase, Audit):
    snapshot_type = models.PositiveSmallIntegerField(choices=SNAPSHOT_TYPE_CHOICES)
    snapshot = models.ForeignKey(BushfireSnapshot, related_name='damage_snapshot')

    class Meta:
        unique_together = ('damage_type', 'snapshot')


class BushfirePropertyBase(models.Model):
    name = models.CharField(max_length=32,null=False,editable=False, verbose_name="Property Name")
    value = models.TextField(null=True,blank=True, verbose_name="Property Value")

    class Meta:
        abstract = True

    @property
    def json_value(self):
        if hasattr(self,"_json_value"):
            result = getattr(self,"_json_value")
        else:
            result = json.loads(self.value)
            setattr(self,"_json_value",result)
        return result


    def __str__(self):
        return '{}={}'.format(self.name,self.value)


class BushfireProperty(BushfirePropertyBase):
    bushfire = models.ForeignKey(Bushfire, related_name='properties')

    class Meta:
        unique_together = ('bushfire', 'name',)

class BushfirePropertySnapshot(BushfirePropertyBase):
    snapshot_type = models.PositiveSmallIntegerField(choices=SNAPSHOT_TYPE_CHOICES)
    snapshot = models.ForeignKey(BushfireSnapshot, related_name='properties_snapshot')

    class Meta:
        unique_together = ('snapshot','name')



SUBMIT_MANDATORY_FIELDS= [
    'region', 'district', 'year', 'fire_number', 'name', 'fire_detected_date', 'prob_fire_level',
    'dispatch_pw', 'dispatch_aerial', 'investigation_req', 'park_trail_impacted', 'media_alert_req',
    'duty_officer', 'initial_control'
]
FIRE_BOMBING_GOLIVE_DATE = datetime(2018,11,23,tzinfo=pytz.timezone("Australia/Perth"))
SUBMIT_MANDATORY_DEP_FIELDS= {
    'dispatch_pw': [[1, 'dispatch_pw_date']], # if 'dispatch_pw' == 1 then 'dispatch_pw_date' is required
    'initial_control': [[Agency.OTHER, 'other_initial_control']],
    'dispatch_aerial': [[True, 'dispatch_aerial_date']],
    ('dispatch_aerial',lambda bf:bf.report_status == Bushfire.STATUS_INITIAL or (bf.init_authorised_date and bf.init_authorised_date > FIRE_BOMBING_GOLIVE_DATE)):[[True,("fire_bombing.ground_controller.username","Ground Controller"),("fire_bombing.ground_controller.callsign","Ground Controller Call Sign"),("fire_bombing.radio_channel","Radio Channel"),("fire_bombing.prefered_resources","Prefered Resource"),("fire_bombing.activation_criterias","Indicate Requesting Activation Criteria")]]
}
SUBMIT_MANDATORY_FORMSETS= [
]

AUTH_MANDATORY_FIELDS= [
    'area',
    'cause_state', 'cause',
    'fire_contained_date', 'fire_controlled_date',
    'fire_safe_date',
    'final_control',
    'max_fire_level', 'arson_squad_notified', 'job_code',
    'dfes_incident_no'
]

AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND= [
    'duty_officer',
]
AUTH_MANDATORY_DEP_FIELDS_FIRE_NOT_FOUND= {
    'dispatch_pw': [[1, 'field_officer', 'dispatch_pw_date']], # if 'dispatch_pw' == '1' then 'field_officer' is required
    'field_officer': [[User.OTHER, 'other_field_officer','other_field_officer_agency']], # username='other'
}

AUTH_MANDATORY_DEP_FIELDS= {
    'dispatch_pw': [[1, 'field_officer', 'dispatch_pw_date']], # if 'dispatch_pw' == '1' then 'field_officer' is required
    'fire_monitored_only': [[False, 'first_attack']],

    'cause': [[Cause.OTHER, 'other_cause'], [Cause.ESCAPE_DPAW_BURNING, 'prescribed_burn_id']],
    'first_attack': [[Agency.OTHER, 'other_first_attack']],
    'final_control': [[Agency.OTHER, 'other_final_control']],
    'area_limit': [[True, 'area']],
    'field_officer': [[User.OTHER, 'other_field_officer', 'other_field_officer_agency']], # username='other'
}
AUTH_MANDATORY_FORMSETS= [
    #'fire_behaviour',
    'damages',
    'injuries',
]

reversion.register(Bushfire, follow=['tenures_burnt', 'injuries', 'damages'])
reversion.register(Profile)
reversion.register(Region)
reversion.register(District)
reversion.register(Tenure)
reversion.register(FuelType)
reversion.register(Cause)
reversion.register(Agency)
reversion.register(InjuryType)
reversion.register(DamageType)
reversion.register(AreaBurnt)       # related_name=tenures_burnt
reversion.register(Injury)          # related_name=injuries
reversion.register(Damage)          # related_name=damages
reversion.register(BushfireSnapshot) # related_name=snapshots

reversion.register(BushfireProperty) 
