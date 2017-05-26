from bfrs.models import (Bushfire, AreaBurnt, Damage, Injury, FireBehaviour, Tenure, SnapshotHistory) #, LinkedBushfire)
#from bfrs.forms import (BaseAreaBurntFormSet)
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User, Group
import json
import pytz

import unicodecsv
from django.utils.encoding import smart_str
from datetime import datetime
from django.core import serializers
from xlwt import Workbook
from itertools import count
from django.forms.models import inlineformset_factory
from collections import defaultdict
from copy import deepcopy
from django.core.urlresolvers import reverse


def breadcrumbs_li(links):
    """Returns HTML: an unordered list of URLs (no surrounding <ul> tags).
    ``links`` should be a iterable of tuples (URL, text).
    """
    crumbs = ''
    li_str = '<li><a href="{}">{}</a></li>'
    li_str_last = '<li class="active"><span>{}</span></li>'
    # Iterate over the list, except for the last item.
    if len(links) > 1:
        for i in links[:-1]:
            crumbs += li_str.format(i[0], i[1])
    # Add the last item.
    crumbs += li_str_last.format(links[-1][1])
    return crumbs

def fssdrs_group():
    return Group.objects.get(name='FSS Datasets and Reporting Services')

def can_maintain_data(user):
    return fssdrs_group() in user.groups.all() and not is_external_user(user)


def is_external_user(user):
    try:
        return user.email.split('@')[1].lower() != settings.INTERNAL_EMAIL #'dpaw.wa.gov.au'
    except:
        return True

def serialize_bushfire(auth_type, action, obj):
    "Serializes a Bushfire object"
    if auth_type == 'initial':
        obj.initial_snapshot = serializers.serialize('json', [obj])
    if auth_type == 'final':
        obj.final_snapshot = serializers.serialize('json', [obj])
    archive_snapshot(auth_type, action, obj)
    obj.save()

def deserialize_bushfire(auth_type, obj):
    """Returns a deserialized Bushfire object

       obj is either:
         1. bushfire obj, eg.
            b=Bushfire.objects.get(id=12)
            deserialize_bushfire('final', b.final_snapshot)

         2. serialized json object (bushfire text string JSONified), eg.
            snapshop_history_obj=b.snapshot_history.all()[0]
            deserialize_bushfire(snapshots_history_obj.auth_type, snapshots_history_obj.snapshot)
    """
    if auth_type == 'initial':
        obj = obj.initial_snapshot if hasattr(obj, 'initial_snapshot') else obj
    if auth_type == 'final':
        obj = obj.final_snapshot if hasattr(obj, 'final_snapshot') else obj

    return serializers.deserialize("json", obj).next().object

def archive_snapshot(auth_type, action, obj):
        """ allows archicing of existing snapshot before overwriting """
        cur_snapshot_history = obj.snapshot_history.all()
        SnapshotHistory.objects.create(
            creator = obj.modifier,
            modifier = obj.modifier,
            auth_type = auth_type,
            action = action if action else 'Update',
            snapshot = obj.initial_snapshot if auth_type =='initial' else obj.final_snapshot if obj.final_snapshot else '{"Deleted": True}',
            prev_snapshot = cur_snapshot_history.latest('created') if cur_snapshot_history else None,
            bushfire_id = obj.id
        )

def invalidate_bushfire(obj, new_district, user):
    """ Invalidate the current bushfire, create new bushfire and update links, including historical links """
    if obj.district == new_district:
        return None

    with transaction.atomic():
        old_rpt_status = obj.report_status
        obj.report_status = Bushfire.STATUS_INVALIDATED
        obj.save()
        old_obj = deepcopy(obj)
        old_invalidated = old_obj.invalidated.all()

        # create a new object as a copy of existing
        obj.pk = None

        # check if we have this district already in the list of invalidated linked bushfires, and re-use fire_number if so
        invalidated_objs = [invalidated_obj for invalidated_obj in old_invalidated if invalidated_obj.district==new_district]
        if invalidated_objs and invalidated_objs[0].report_status==Bushfire.STATUS_INVALIDATED:
            # re-use previous fire_number
            linked_bushfire = invalidated_objs[0]
            obj.fire_number = linked_bushfire.fire_number
            linked_bushfire.delete() # to avoid integrity constraint
        else:
            # create new fire_number
            obj.fire_number = ' '.join(['BF', str(obj.year), new_district.code, '{0:03d}'.format(obj.next_id(new_district))])

        obj.report_status = old_rpt_status
        obj.district = new_district
        obj.region = new_district.region
        obj.valid_bushfire = None
        obj.fire_not_found = False
        obj.save()

        # link the new bushfire to the old invalidated bushfire
        created = datetime.now(tz=pytz.utc)

        # copy all links from the above invalidated bushfire to the new bushfire
        if old_invalidated:
            for linked in old_invalidated:
                obj.invalidated.add(linked)

        # link the old invalidate bushfire to the new (valid) bushfire - fwd link
        old_obj.valid_bushfire = obj
        old_obj.save()

        return obj
    return False


def create_areas_burnt(bushfire, area_burnt_list):
    """
    Creates the initial bushfire record together with AreaBurnt FormSet from BushfireCreateView (Operates on data dict from SSS)

    """
    #t=Tenure.objects.all()[0]
    #initial = [{'tenure': t, 'area':0.0, 'name':'ABC', 'other':'Other'}]

    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for d in area_burnt_list:
        aggregated_sums[d["category"]] += d["area"]

    area_other = 0.0
    new_area_burnt_list = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_list.append({
                'tenure': tenure_qs[0],
                'area': round(area, 2)
            })

        elif area:
            area_other += area

    if area_other > 0:
        new_area_burnt_list.append({'tenure': Tenure.objects.get(name__icontains='other'), 'area': round(area_other, 2)})

    AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=len(new_area_burnt_list), min_num=1, validate_min=True, exclude=())
    area_burnt_formset = AreaBurntFormSet(instance=bushfire, prefix='area_burnt_fs')
    for subform, data in zip(area_burnt_formset.forms, new_area_burnt_list):
        subform.initial = data

    return area_burnt_formset

def update_areas_burnt(bushfire, area_burnt_list):
    """
    Updates the bushfire record from api.py, via REST API (Operates on data dict from SSS)
    """
    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for d in area_burnt_list:
        aggregated_sums[d["category"]] += d["area"]

    area_other = 0.0
    new_area_burnt_object = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure_qs[0], area=round(area, 2)))
        elif area:
            area_other += area

    if area_other > 0:
        new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=Tenure.objects.get(name__icontains='other'), area=round(area, 2)))

    try:
        with transaction.atomic():
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_area_burnt_object)
    except IntegrityError:
        return 0

    return 1

#def update_areas_burnt_fs(bushfire, area_burnt_formset):
#    """
#    Updates the AreaBurnt FormSet from BushfireInitUpdateView
#    """
#    new_fs_object = []
#    for form in area_burnt_formset:
#        if form.is_valid():
#            tenure = form.cleaned_data.get('tenure')
#            area = form.cleaned_data.get('area')
#            remove = form.cleaned_data.get('DELETE')
#
#            if not remove and (tenure):
#                new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, area=area))
#
#    try:
#        with transaction.atomic():
#            AreaBurnt.objects.filter(bushfire=bushfire).delete()
#            AreaBurnt.objects.bulk_create(new_fs_object)
#    except IntegrityError:
#        return 0
#
#    return 1

def update_injury_fs(bushfire, injury_formset):
    new_fs_object = []
    for form in injury_formset:
        if form.is_valid():
            injury_type = form.cleaned_data.get('injury_type')
            number = form.cleaned_data.get('number')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (injury_type and number):
                new_fs_object.append(Injury(bushfire=bushfire, injury_type=injury_type, number=number))

    try:
        with transaction.atomic():
            Injury.objects.filter(bushfire=bushfire).delete()
            Injury.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_damage_fs(bushfire, damage_formset):
    new_fs_object = []
    for form in damage_formset:
        if form.is_valid():
            damage_type = form.cleaned_data.get('damage_type')
            number = form.cleaned_data.get('number')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (damage_type and number):
                new_fs_object.append(Damage(bushfire=bushfire, damage_type=damage_type, number=number))

    try:
        with transaction.atomic():
            Damage.objects.filter(bushfire=bushfire).delete()
            Damage.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_fire_behaviour_fs(bushfire, fire_behaviour_formset):
    new_fs_object = []
    for form in fire_behaviour_formset:
        if form.is_valid():
            fuel_type = form.cleaned_data.get('fuel_type')
            ros = form.cleaned_data.get('ros')
            flame_height = form.cleaned_data.get('flame_height')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (fuel_type and ros>=0 and flame_height>0.0):
                new_fs_object.append(FireBehaviour(bushfire=bushfire, fuel_type=fuel_type, ros=ros, flame_height=flame_height))

    try:
        with transaction.atomic():
            FireBehaviour.objects.filter(bushfire=bushfire).delete()
            if not bushfire.fire_behaviour_unknown:
                FireBehaviour.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def mail_url(request, bushfire, status='initial'):
    if status == 'initial':
        return "http://" + request.get_host() + reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id})
    if status == 'final' or status == 'review':
        return "http://" + request.get_host() + reverse('bushfire:bushfire_final', kwargs={'pk':bushfire.id})


def update_status(request, bushfire, action):
    notification = {}
    if action == 'Submit' and bushfire.report_status==Bushfire.STATUS_INITIAL:
        bushfire.init_authorised_by = request.user
        bushfire.init_authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
        serialize_bushfire('initial', action, bushfire)

        # send emails
        resp = rdo_email(bushfire, mail_url(request, bushfire))
        notification['RDO'] = 'Email Sent' if resp else 'Email failed'

        resp = dfes_email(bushfire, mail_url(request, bushfire))
        notification['DFES'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.park_trail_impacted:
            resp = pvs_email(bushfire, mail_url(request, bushfire))
            notification['PVS'] = 'Email Sent' if resp else 'Email failed'

	# TODO awaiting item notification in SSS dictionary
#            resp = fpc_email(bushfire, mail_url(request, bushfire))
#            notification['FPC'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.media_alert_req:
            resp = pica_email(bushfire, mail_url(request, bushfire))
            notification['PICA'] = 'Email Sent' if resp else 'Email failed'

            resp = pica_sms(bushfire, mail_url(request, bushfire))
            notification['PICA SMS'] = 'SMS Sent' if resp else 'SMS failed'

        if bushfire.investigation_req:
            resp = police_email(bushfire, mail_url(request, bushfire))
            notification['POLICE'] = 'Email Sent' if resp else 'Email failed'

        bushfire.area = 0. # reset bushfire area
        bushfire.save()

    elif action == 'Authorise' and bushfire.report_status==Bushfire.STATUS_INITIAL_AUTHORISED:
        bushfire.authorised_by = request.user
        bushfire.authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        serialize_bushfire('final', action, bushfire)

        # send emails
        resp = fssdrs_email(bushfire, mail_url(request, bushfire, status='final'), status='final')
        notification['FSSDRS-Auth'] = 'Email Sent' if resp else 'Email failed'

        bushfire.save()

    elif action == 'mark_reviewed' and bushfire.report_status==Bushfire.STATUS_FINAL_AUTHORISED:
        bushfire.reviewed_by = request.user
        bushfire.reviewed_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_REVIEWED
        serialize_bushfire('final', action, bushfire)

        # send emails
        resp = fssdrs_email(bushfire, mail_url(request, bushfire, status='review'), status='review')
        notification['FSSDRS-Review'] = 'Email Sent' if resp else 'Email failed'

        bushfire.save()

    return notification

def rdo_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'RDO Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'RDO Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.RDO_EMAIL)

def pvs_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'PVS Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'PVS Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.PVS_EMAIL)

def fpc_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'FPC Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'FPC Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.FPC_EMAIL)

def pica_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'PICA Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'PICA Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.PICA_EMAIL)

def pica_sms(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    message = 'PICA SMS - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail('', message, settings.EMAIL_TO_SMS_FROMADDRESS, settings.MEDIA_ALERT_SMS_TOADDRESS)

def dfes_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    #import ipdb; ipdb.set_trace()
    subject = 'DFES Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'DFES Email - {}\n\n(Lat/Lon) {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, bushfire.origin_point, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.DFES_EMAIL)

def police_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'POLICE Email - Initial report submitted and an investigation is required- {}'.format(bushfire.fire_number)
    message = 'POLICE Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.POLICE_EMAIL)

def fssdrs_email(bushfire, url, status='final'):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    if status == 'final':
        subject = 'FSSDRS Email - Final Fire report has been authorised - {}'.format(bushfire.fire_number)
        message = 'FSSDRS Email - {}\n\nreport has been authorised. User {}, at {}.\n\nThe report is located at {}'.format(
            bushfire.fire_number, bushfire.authorised_by, bushfire.authorised_date, url
        )
    else:
        subject = 'FSSDRS Email - Final Fire report has been reviewed - {}'.format(bushfire.fire_number)
        message = 'FSSDRS Email - {}\n\nreport has been reviewed. User {}, at {}.\n\nThe report is located at {}'.format(
            bushfire.fire_number, bushfire.reviewed_by, bushfire.reviewed_date, url
        )

    return send_mail(subject, message, settings.FROM_EMAIL, settings.FSSDRS_EMAIL)

def create_view():
    """
    cursor.execute('''drop view bfrs_bushfire_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
    CREATE OR REPLACE VIEW bfrs_bushfire_v AS
    SELECT b.id,
    b.origin_point,
    CASE WHEN b.report_status >= 2 THEN ST_AsGeoJSON(st_envelope(b.fire_boundary))
     	 ELSE ST_AsGeoJSON(b.fire_boundary)
    END as fire_boundary,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.fire_level,
    CASE WHEN media_alert_req THEN 1
     	 ELSE 0
    END as media_alert_req,
    CASE WHEN park_trail_impacted THEN 1
     	 ELSE 0
    END as park_trail_impacted,
    b.cause_state,
    b.other_cause,
    b.other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN fire_position_override THEN 1
     	 ELSE 0
    END as fire_position_override,
    CASE WHEN fire_not_found THEN 1
     	 ELSE 0
    END as fire_not_found,
    b.assistance_req,
    b.assistance_details,
    b.communications,
    b.other_info,
    b.init_authorised_date,
    b.dispatch_pw,
    CASE WHEN dispatch_aerial THEN 1
     	 ELSE 0
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN arson_squad_notified THEN 1
     	 ELSE 0
    END as arson_squad_notified,
    CASE WHEN investigation_req THEN 1
     	 ELSE 0
    END as investigation_req,
    b.offence_no,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN area_unknown THEN 1
     	 ELSE 0
    END as area_unknown,
    b.time_to_control,
    CASE WHEN fire_behaviour_unknown THEN 1
     	 ELSE 0
    END as fire_behaviour_unknown,
    b.authorised_date,
    b.reviewed_date,
    b.report_status,
    CASE WHEN archive THEN 1
     	 ELSE 0
    END as archive,
    b.authorised_by_id,
    b.cause_id,
    b.creator_id,
    b.district_id,
    b.duty_officer_id,
    b.field_officer_id,
    b.final_control_id,
    b.first_attack_id,
    b.init_authorised_by_id,
    b.initial_control_id,
    b.modifier_id,
    b.region_id,
    b.reviewed_by_id,
    b.tenure_id
    FROM bfrs_bushfire b
    WHERE b.archive = false AND b.report_status < {};
    '''.format(Bushfire.STATUS_INVALIDATED))

def create_final_view():
    """
    cursor.execute('''drop view bfrs_bushfire_final_fireboundary_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
    CREATE OR REPLACE VIEW bfrs_bushfire_final_fireboundary_v AS
    SELECT b.id,
    b.fire_boundary,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.fire_level,
    CASE WHEN media_alert_req THEN 1
     	 ELSE 0
    END as media_alert_req,
    CASE WHEN park_trail_impacted THEN 1
     	 ELSE 0
    END as park_trail_impacted,
    b.cause_state,
    b.other_cause,
    b.other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN fire_position_override THEN 1
     	 ELSE 0
    END as fire_position_override,
    CASE WHEN fire_not_found THEN 1
     	 ELSE 0
    END as fire_not_found,
    b.assistance_req,
    b.assistance_details,
    b.communications,
    b.other_info,
    b.init_authorised_date,
    b.dispatch_pw,
    CASE WHEN dispatch_aerial THEN 1
     	 ELSE 0
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN arson_squad_notified THEN 1
     	 ELSE 0
    END as arson_squad_notified,
    CASE WHEN investigation_req THEN 1
     	 ELSE 0
    END as investigation_req,
    b.offence_no,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN area_unknown THEN 1
     	 ELSE 0
    END as area_unknown,
    b.time_to_control,
    CASE WHEN fire_behaviour_unknown THEN 1
     	 ELSE 0
    END as fire_behaviour_unknown,
    b.authorised_date,
    b.reviewed_date,
    b.report_status,
    CASE WHEN archive THEN 1
     	 ELSE 0
    END as archive,
    b.authorised_by_id,
    b.cause_id,
    b.creator_id,
    b.district_id,
    b.duty_officer_id,
    b.field_officer_id,
    b.final_control_id,
    b.first_attack_id,
    b.init_authorised_by_id,
    b.initial_control_id,
    b.modifier_id,
    b.region_id,
    b.reviewed_by_id,
    b.tenure_id
    FROM bfrs_bushfire b
    WHERE b.archive = false AND b.report_status >= {} AND b.report_status < {};
    '''.format(Bushfire.STATUS_INITIAL_AUTHORISED, Bushfire.STATUS_INVALIDATED))

def create_fireboundary_view():
    """
    cursor.execute('''drop view bfrs_bushfire_fireboundary_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
    CREATE OR REPLACE VIEW bfrs_bushfire_fireboundary_v AS
    SELECT b.id,
    b.fire_boundary,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.fire_level,
    CASE WHEN media_alert_req THEN 1
     	 ELSE 0
    END as media_alert_req,
    CASE WHEN park_trail_impacted THEN 1
     	 ELSE 0
    END as park_trail_impacted,
    b.cause_state,
    b.other_cause,
    b.other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN fire_position_override THEN 1
     	 ELSE 0
    END as fire_position_override,
    CASE WHEN fire_not_found THEN 1
     	 ELSE 0
    END as fire_not_found,
    b.assistance_req,
    b.assistance_details,
    b.communications,
    b.other_info,
    b.init_authorised_date,
    b.dispatch_pw,
    CASE WHEN dispatch_aerial THEN 1
     	 ELSE 0
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN arson_squad_notified THEN 1
     	 ELSE 0
    END as arson_squad_notified,
    CASE WHEN investigation_req THEN 1
     	 ELSE 0
    END as investigation_req,
    b.offence_no,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN area_unknown THEN 1
     	 ELSE 0
    END as area_unknown,
    b.time_to_control,
    CASE WHEN fire_behaviour_unknown THEN 1
     	 ELSE 0
    END as fire_behaviour_unknown,
    b.authorised_date,
    b.reviewed_date,
    b.report_status,
    CASE WHEN archive THEN 1
     	 ELSE 0
    END as archive,
    b.authorised_by_id,
    b.cause_id,
    b.creator_id,
    b.district_id,
    b.duty_officer_id,
    b.field_officer_id,
    b.final_control_id,
    b.first_attack_id,
    b.init_authorised_by_id,
    b.initial_control_id,
    b.modifier_id,
    b.region_id,
    b.reviewed_by_id,
    b.tenure_id
    FROM bfrs_bushfire b
    WHERE b.archive = false AND b.report_status < {};
    '''.format(Bushfire.STATUS_INVALIDATED))


def test_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_v''')
    return cursor.fetchall()

def test_final_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_final_fireboundary_v''')
    return cursor.fetchall()

def test_fireboundary_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_fireboundary_v''')
    return cursor.fetchall()

def drop_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''drop view bfrs_bushfire_v''')
    return cursor.fetchall()

def drop_final_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''drop view bfrs_bushfire_final_fireboundary_v''')
    return cursor.fetchall()

def drop_fireboundary_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''drop view bfrs_bushfire_fireboundary_v''')
    return cursor.fetchall()

def export_final_csv(request, queryset):
    #import csv
    filename = 'export_final-' + datetime.now().strftime('%Y-%m-%dT%H%M%S') + '.csv'
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=' + filename
    writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

    writer.writerow([
        "ID",
		"Region",
		"District",
		"Name",
		"Year",
		"Incident No",
		"DFES Incident No",
		"Job Code",
		"Fire Level",
		"Media Alert Req",
		"Investigation Req",
		"Fire Position",
		#"Origin Point",
		#"Fire Boundary",
		"Fire Not Found",
		"Assistance Req",
		"Communications",
		"Other Info",
		"Cause",
		"Other Cause",
		"Field Officer",
		"Duty Officer",
		"Init Authorised By",
		"Init Authorised Date",
		"Authorised By",
		"Authorised Date",
		"Reviewed By",
		"Reviewed Date",
		"Dispatch P&W",
		"Dispatch Aerial",
		"Fire Detected",
		"Fire Controlled",
		"Fire Contained",
		"Fire Safe",
		"Fuel Type",
		#"Initial Snapshot",
		"First Attack",
		"Other First Attack",
		"Initial Control",
		"Other Initial Control",
		"Final Control",
		"Other Final Control",
		"Arson Squad Notified",
		"Offence No",
		"Area",
		"Estimated Time to Control",
		"Authorised By",
		"Authorised Date",
		"Report Status",
    ]
	)
    for obj in queryset:
		writer.writerow([
			smart_str( obj.id),
			smart_str( obj.region.name),
			smart_str( obj.district.name),
			smart_str( obj.name),
			smart_str( obj.year),
			smart_str( obj.fire_number),
			smart_str( obj.dfes_incident_no),
			smart_str( obj.job_code),
			smart_str( obj.get_fire_level_display()),
			smart_str( obj.media_alert_req),
			smart_str( obj.investigation_req),
			smart_str( obj.fire_position),
			#row.write(col_no(), smart_str( obj.origin_point)),
			#row.write(col_no(), smart_str( obj.fire_boundary),
			smart_str( obj.fire_not_found),
			smart_str( obj.assistance_req),
			smart_str( obj.communications),
			smart_str( obj.other_info),
			smart_str( obj.cause),
			smart_str( obj.other_cause),
			smart_str( obj.field_officer.get_full_name() if obj.field_officer else None ),
			smart_str( obj.duty_officer.get_full_name() if obj.duty_officer else None ),
			smart_str( obj.init_authorised_by.get_full_name() if obj.init_authorised_by else None ),
			smart_str( obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else None),
			smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ),
			smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None),
			smart_str( obj.reviewed_by.get_full_name() if obj.reviewed_by else None ),
			smart_str( obj.reviewed_date.strftime('%Y-%m-%d %H:%M:%S') if obj.reviewed_date else None),
			smart_str( obj.dispatch_pw_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_pw_date else None),
			smart_str( obj.dispatch_aerial_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_aerial_date else None),
			smart_str( obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else None),
			smart_str( obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else None),
			smart_str( obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else None),
			smart_str( obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else None),
			smart_str( obj.fuel_type),
			#row.write(col_no(), smart_str( obj.initial_snapshot),
			smart_str( obj.first_attack),
			smart_str( obj.other_first_attack),
			smart_str( obj.initial_control),
			smart_str( obj.other_initial_control),
			smart_str( obj.final_control),
			smart_str( obj.other_final_control),
			smart_str( obj.arson_squad_notified),
			smart_str( obj.offence_no),
			smart_str( obj.area),
			smart_str( obj.time_to_control),
			smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ),
			smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ),
			smart_str( obj.get_report_status_display()),
        ])
    return response
export_final_csv.short_description = u"Export CSV (Final)"


def export_excel(request, queryset):

    filename = 'export_final-' + datetime.now().strftime('%Y-%m-%dT%H%M%S') + '.xls'
    response = HttpResponse(content_type='application/vnd.ms-excel; charset=utf-16')
    response['Content-Disposition'] = 'attachment; filename=' + filename
    writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)


    book = Workbook()
    sheet1 = book.add_sheet('Data')
    book.add_sheet('Sheet 2')

    col_no = lambda c=count(): next(c)
    row_no = lambda c=count(): next(c)
    sheet1 = book.get_sheet(0)
    hdr = sheet1.row(row_no())

    hdr.write(col_no(), "ID")
    hdr.write(col_no(), "Region")
    hdr.write(col_no(), "District")
    hdr.write(col_no(), "Name")
    hdr.write(col_no(), "Year")
    hdr.write(col_no(), "Fire Number")
    hdr.write(col_no(), "DFES Incident No")
    hdr.write(col_no(), "Job Code")
    hdr.write(col_no(), "Fire Level")
    hdr.write(col_no(), "Media Alert Req")
    hdr.write(col_no(), "Investigation Req")
    hdr.write(col_no(), "Fire Position")
    #"Origin Point",
    #"Fire Boundary",
    hdr.write(col_no(), "Fire Not Found")
    hdr.write(col_no(), "Assistance Req")
    hdr.write(col_no(), "Communications")
    hdr.write(col_no(), "Other Info")
    hdr.write(col_no(), "Cause")
    hdr.write(col_no(), "Other Cause")
    hdr.write(col_no(), "Field Officer")
    hdr.write(col_no(), "Duty Officer")
    hdr.write(col_no(), "Init Authorised By")
    hdr.write(col_no(), "Init Authorised Date")
    hdr.write(col_no(), "Authorised By")
    hdr.write(col_no(), "Authorised Date")
    hdr.write(col_no(), "Reviewed By")
    hdr.write(col_no(), "Reviewed Date")
    hdr.write(col_no(), "Dispatch P&W")
    hdr.write(col_no(), "Dispatch Aerial")
    hdr.write(col_no(), "Fire Detected")
    hdr.write(col_no(), "Fire Controlled")
    hdr.write(col_no(), "Fire Contained")
    hdr.write(col_no(), "Fire Safe")
    hdr.write(col_no(), "Fuel Type")
    hdr.write(col_no(), "First Attack")
    hdr.write(col_no(), "Other First Attack")
    hdr.write(col_no(), "Initial Control")
    hdr.write(col_no(), "Other Initial Control")
    hdr.write(col_no(), "Final Control")
    hdr.write(col_no(), "Other Final Control")
    hdr.write(col_no(), "Arson Squad Notified")
    hdr.write(col_no(), "Offence No")
    hdr.write(col_no(), "Area")
    hdr.write(col_no(), "Estimated Time to Control")
    hdr.write(col_no(), "Authorised By")
    hdr.write(col_no(), "Authorised Date")
    hdr.write(col_no(), "Report Status")
    hdr.write(col_no(), "Tenures of Area Burnt")
    hdr.write(col_no(), "Damage")
    hdr.write(col_no(), "Injuries and Fatalities")

    row_no = lambda c=count(1): next(c)
    for obj in queryset:
        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)

        row.write(col_no(), obj.id )
        row.write(col_no(), smart_str( obj.region.name) )
        row.write(col_no(), smart_str( obj.district.name) )
        row.write(col_no(), smart_str( obj.name) if obj.name else None)
        row.write(col_no(), smart_str( obj.year) )
        row.write(col_no(), obj.fire_number )
        row.write(col_no(), obj.dfes_incident_no if obj.dfes_incident_no else None)
        row.write(col_no(), obj.job_code if obj.job_code else None)
        row.write(col_no(), smart_str( obj.get_fire_level_display() if obj.fire_level else None))
        row.write(col_no(), smart_str( obj.media_alert_req if obj.media_alert_req else None))
        row.write(col_no(), smart_str( obj.investigation_req if obj.investigation_req else None))
        row.write(col_no(), smart_str( obj.fire_position if obj.fire_position else None))
        #row.write(col_no(), smart_str( obj.origin_point) )
        #row.write(col_no(), smart_str( obj.fire_boundary) )
        row.write(col_no(), smart_str( obj.fire_not_found if obj.fire_not_found else None))
        row.write(col_no(), smart_str( obj.assistance_req if obj.assistance_req else None))
        row.write(col_no(), smart_str( obj.communications if obj.communications else None))
        row.write(col_no(), smart_str( obj.other_info if obj.other_info else None))
        row.write(col_no(), smart_str( obj.cause if obj.cause else None))
        row.write(col_no(), smart_str( obj.other_cause if obj.other_cause else None))
        row.write(col_no(), smart_str( obj.field_officer.get_full_name() if obj.field_officer else None ) )
        row.write(col_no(), smart_str( obj.duty_officer.get_full_name() if obj.duty_officer else None ) )
        row.write(col_no(), smart_str( obj.init_authorised_by.get_full_name() if obj.init_authorised_by else None ) )
        row.write(col_no(), smart_str( obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else None) )
        row.write(col_no(), smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ) )
        row.write(col_no(), smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None) )
        row.write(col_no(), smart_str( obj.reviewed_by.get_full_name() if obj.reviewed_by else None ) )
        row.write(col_no(), smart_str( obj.reviewed_date.strftime('%Y-%m-%d %H:%M:%S') if obj.reviewed_date else None) )
        row.write(col_no(), smart_str( obj.dispatch_pw_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_pw_date else None) )
        row.write(col_no(), smart_str( obj.dispatch_aerial_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_aerial_date else None) )
        row.write(col_no(), smart_str( obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else None) )
        row.write(col_no(), smart_str( obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else None) )
        row.write(col_no(), smart_str( obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else None) )
        row.write(col_no(), smart_str( obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else None) )
        row.write(col_no(), smart_str( '; '.join(['(fuel_type={}, ros={}, flame_height={})'.format(i.fuel_type, i.ros, i.flame_height) for i in obj.fire_behaviour.all()])) if obj.fire_behaviour.all() else None )
        row.write(col_no(), smart_str( obj.first_attack if obj.first_attack else None))
        row.write(col_no(), smart_str( obj.other_first_attack if obj.other_first_attack else None))
        row.write(col_no(), smart_str( obj.initial_control if obj.initial_control else None))
        row.write(col_no(), smart_str( obj.other_initial_control if obj.other_initial_control else None))
        row.write(col_no(), smart_str( obj.final_control if obj.final_control else None))
        row.write(col_no(), smart_str( obj.other_final_control if obj.other_final_control else None))
        row.write(col_no(), smart_str( obj.arson_squad_notified if obj.arson_squad_notified else None))
        row.write(col_no(), obj.offence_no if obj.offence_no else None)
        row.write(col_no(), obj.area if obj.area else none)
        row.write(col_no(), smart_str( obj.time_to_control if obj.time_to_control else None))
        row.write(col_no(), smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ) )
        row.write(col_no(), smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ) )
        row.write(col_no(), smart_str( obj.get_report_status_display() if obj.report_status else None))
        row.write(col_no(), smart_str( '; '.join(['(name={}, area={})'.format(i.tenure.name, i.area) for i in obj.tenures_burnt.all()]) ))
        row.write(col_no(), smart_str( '; '.join(['(name={}, number={})'.format(i.damage_type.name, i.number) for i in obj.damages.all()]) if obj.damages.all() else None))
        row.write(col_no(), smart_str( '; '.join(['(name={}, number={})'.format(i.injury_type.name, i.number) for i in obj.injuries.all()]) if obj.injuries.all() else None ))

    book.save(response)

    return response
export_final_csv.short_description = u"Export Excel"


