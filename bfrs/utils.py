from bfrs.models import (Bushfire, AreaBurnt, Damage, Injury, FireBehaviour, Tenure, SpatialDataHistory, LinkedBushfire)
#from bfrs.forms import (BaseAreaBurntFormSet)
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.core.mail import send_mail
from django.conf import settings
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

def serialize_bushfire(auth_type, obj):
    "Serializes a Bushfire object"
    if auth_type == 'initial':
            obj.initial_snapshot = serializers.serialize('json', [obj])
    if auth_type == 'final':
            obj.final_snapshot = serializers.serialize('json', [obj])
    obj.save()

def deserialize_bushfire(auth_type, obj):
    "Returns a deserialized Bushfire object"
    if auth_type == 'initial':
            return serializers.deserialize("json", obj.initial_snapshot).next().object
    if auth_type == 'final':
            return serializers.deserialize("json", obj.final_snapshot).next().object


def calc_coords(obj):
    coord_type = obj.coord_type
    if coord_type == Bushfire.COORD_TYPE_MGAZONE:
        obj.lat_decimal = float(obj.mga_zone)/2.0
        obj.lat_degrees = float(obj.mga_zone)/2.0
        obj.lat_minutes = float(obj.mga_zone)/2.0

        obj.lon_decimal = float(obj.mga_zone)/2.0
        obj.lon_degrees = float(obj.mga_zone)/2.0
        obj.lon_minutes = float(obj.mga_zone)/2.0

    elif coord_type == Bushfire.COORD_TYPE_LATLONG:
        obj.mga_zone = float(obj.lat_decimal) * 2.0
        obj.mga_easting = float(obj.lat_decimal) * 2.0
        obj.mga_northing = float(obj.lat_decimal) * 2.0


def archive_spatial_data(obj):
        """ if origin point of fire boundary has changed, archive existing """
        qs_bushfire = Bushfire.objects.filter(pk=obj.id)
        if qs_bushfire:
            bushfire = qs_bushfire[0]
            if bushfire.fire_boundary != obj.fire_boundary or bushfire.origin_point != obj.origin_point:
                SpatialDataHistory.objects.create(
                    creator = obj.modifier,
                    modifier = obj.modifier,
                    origin_point = obj.origin_point,
                    tenure = obj.tenure,
                    fire_boundary = obj.fire_boundary,
                    area_burnt = serializers.serialize('json', obj.tenures_burnt.all()),
                    bushfire_id = obj.id
                )

def invalidate_bushfire(obj, new_district, user):
    """ Invalidate the current bushfire, create new bushfire and update links, including historical links """
    #cur_obj = Bushfire.objects.get(pk=obj.id)
    if obj.district == new_district:
        return None

    with transaction.atomic():
        #obj.invalid = True
        old_rpt_status = obj.report_status
        obj.report_status = Bushfire.STATUS_INVALIDATED
#        obj.fire_number = None
        obj.save()
        old_obj = deepcopy(obj)
        #old_id = obj.pk
        #old_fire_number = obj.fire_number
        old_linked = old_obj.linked.all()

        # create a new object as a copy of existing
        obj.pk = None

        #import ipdb; ipdb.set_trace()
        # check if we have this district already in the list of invalidated linked bushfires, and re-use fire_number if so
        linked_objs = [linked_obj for linked_obj in old_linked if linked_obj.linked_bushfire.district==new_district]
        #if linked_objs and linked_objs[0].linked_bushfire.invalid:
        if linked_objs and linked_objs[0].linked_bushfire.report_status==Bushfire.STATUS_INVALIDATED:
            # re-use previous fire_number
            #import ipdb; ipdb.set_trace()
            linked_bushfire = linked_objs[0].linked_bushfire
            obj.fire_number = linked_bushfire.fire_number
            #LinkedBushfire.objects.filter(linked_id=linked_bushfire[0].id).delete()
            LinkedBushfire.objects.filter(linked_bushfire=linked_bushfire).delete()
            linked_bushfire.delete() # to avoid integrity constraint
        else:
            # create new fire_number
            obj.fire_number = ' '.join(['BF', new_district.code, str(obj.year), '{0:03d}'.format(obj.next_id(new_district))])

        #obj.pk = None
        #obj.invalid = False
        obj.report_status = old_rpt_status
        obj.district = new_district
        obj.region = new_district.region
        #obj.fire_number = ' '.join(['BF', obj.district.code, str(obj.year), '{0:03d}'.format(obj.next_id)])
        obj.save()

        # link the new bushfire to the old invalidated bushfire
        created = datetime.now(tz=pytz.utc)
        #LinkedBushfire.objects.create(bushfire=obj, linked_bushfire=creator=user, modifier=user, linked_id=old_id, linked_fire_number=old_fire_number)
        LinkedBushfire.objects.create(bushfire=obj, linked_bushfire=old_obj, creator=user, modifier=user)

        #import ipdb; ipdb.set_trace()
        # copy all links from the above invalidated bushfire to the new bushfire
        if old_linked:
            for linked in old_linked:
                #linked.pk = None # uncomment this for a two-way link
                #linked.save()
                obj.linked.add(linked)

        # link the old invalidate bushfire to the new (valid) bushfire - fwd link
        #LinkedBushfire.objects.create(bushfire_id=old_id, creator=user, modifier=user, linked_id=obj.pk, linked_fire_number=obj.fire_number)
        LinkedBushfire.objects.create(bushfire=old_obj, linked_bushfire=obj, creator=user, modifier=user)

        #for linked in LinkedBushfire.objects.filter(bushfire=obj):
        #    linked.update(linked_bushfire=obj)


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
                #'other': ''
            })

        elif area:
            area_other += area

    if area_other > 0:
        #new_area_burnt_list.append({'tenure': Tenure.objects.get(name__icontains='other'), 'area': round(area_other, 2), 'other': ''})
        new_area_burnt_list.append({'tenure': Tenure.objects.get(name__icontains='other'), 'area': round(area_other, 2)})

#    import ipdb; ipdb.set_trace()
    #AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=len(new_area_burnt_list), exclude=())
    #AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, formset=BaseAreaBurntFormSet, extra=len(new_area_burnt_list), min_num=1, validate_min=True, exclude=())
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

    #import ipdb; ipdb.set_trace()
    try:
        with transaction.atomic():
            archive_spatial_data(bushfire)
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_area_burnt_object)
    except IntegrityError:
        return 0

def update_areas_burnt_fs(bushfire, area_burnt_formset):
    """
    Updates the AreaBurnt FormSet from BushfireInitUpdateView
    """
    new_fs_object = []
    #import ipdb; ipdb.set_trace()
    for form in area_burnt_formset:
        if form.is_valid():
            tenure = form.cleaned_data.get('tenure')
            area = form.cleaned_data.get('area')
            #other = form.cleaned_data.get('other')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (tenure):
                #new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, area=area, other=other))
                new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, area=area))

    try:
        with transaction.atomic():
            archive_spatial_data(bushfire)
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

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

            if not remove and (fuel_type and ros and flame_height):
                new_fs_object.append(FireBehaviour(bushfire=bushfire, fuel_type=fuel_type, ros=ros, flame_height=flame_height))

    try:
        with transaction.atomic():
            FireBehaviour.objects.filter(bushfire=bushfire).delete()
            FireBehaviour.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1


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
    message = 'DFES Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.POLICE_EMAIL)

def police_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'POLICE Email - Initial report submitted and an investigation is required- {}'.format(bushfire.fire_number)
    message = 'POLICE Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.FSSDRS_EMAIL)

def fssdrs_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'FSSDRS Email - Final Fire report has been authorised - {}'.format(bushfire.fire_number)
    message = 'FSSDRS Email - {}\n\nFinal Fire report has been authorised. User {}, at {}.\n\nThe report is located at {}'.format(
        bushfire.fire_number, bushfire.authorised_by, bushfire.authorised_date, url
    )

    return send_mail(subject, message, settings.FROM_EMAIL, settings.POLICE_EMAIL)

def create_view():
    """
    cursor.execute('''drop view bfrs_bushfire_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
        create or replace view bfrs_bushfire_v as
        select
            b.id,
            b.region_id,
            b.district_id,
            b.name,
            b.fire_number,
            b.year,
            b.fire_level,
            b.media_alert_req,
            b.park_trail_impacted,
            b.cause_id,
            b.cause_state,
            b.other_cause,
            b.tenure_id,
            b.other_tenure,
            b.dfes_incident_no,
            b.job_code,
            b.fire_position,
            b.fire_position_override,
            b.origin_point,
            b.fire_boundary,
            b.assistance_req,
            b.assistance_details,
            b.communications,
            b.other_info,
            b.field_officer_id,
            b.duty_officer_id,
            b.init_authorised_by_id,
            b.init_authorised_date,
            b.dispatch_pw,
            b.dispatch_aerial,
            b.dispatch_pw_date,
            b.dispatch_aerial_date,
            b.fire_detected_date,
            b.fire_contained_date,
            b.fire_controlled_date,
            b.fire_safe_date,
            b.first_attack_id,
            b.other_first_attack,
            b.initial_control_id,
            b.other_initial_control,
            b.final_control_id,
            b.other_final_control,
            b.arson_squad_notified,
            b.investigation_req,
            b.offence_no,
            b.area,
            b.area_limit,
            b.area_unknown,
            b.time_to_control,
            b.authorised_by_id,
            b.authorised_date,
            b.reviewed_by_id,
            b.reviewed_date,
            b.report_status,
            b.archive
	from bfrs_bushfire AS b
        where
           b.archive=false AND
           b.report_status<>{}
    '''.format(Bushfire.STATUS_INVALIDATED))

def test_view():
    from django.db import connection
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_v''')
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
    #response = HttpResponse(content_type='text/csv')
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
    hdr.write(col_no(), "Incident Number")
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
    #"Initial Snpshot",
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

    row_no = lambda c=count(1): next(c)
    for obj in queryset:
        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)

        row.write(col_no(), obj.id )
        row.write(col_no(), smart_str( obj.region.name) )
        row.write(col_no(), smart_str( obj.district.name) )
        row.write(col_no(), smart_str( obj.name) )
        row.write(col_no(), smart_str( obj.year) )
        row.write(col_no(), obj.fire_number )
        row.write(col_no(), obj.dfes_incident_no )
        row.write(col_no(), obj.job_code )
        row.write(col_no(), smart_str( obj.get_fire_level_display() ))
        row.write(col_no(), smart_str( obj.media_alert_req) )
        row.write(col_no(), smart_str( obj.investigation_req) )
        row.write(col_no(), smart_str( obj.fire_position) )
        #row.write(col_no(), smart_str( obj.origin_point) )
        #row.write(col_no(), smart_str( obj.fire_boundary) )
        row.write(col_no(), smart_str( obj.assistance_req) )
        row.write(col_no(), smart_str( obj.communications) )
        row.write(col_no(), smart_str( obj.other_info) )
        row.write(col_no(), smart_str( obj.cause) )
        row.write(col_no(), smart_str( obj.other_cause) )
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
        row.write(col_no(), smart_str( obj.fuel_type) )
        #row.write(col_no(), smart_str( obj.initial_snapshot) )
        row.write(col_no(), smart_str( obj.first_attack) )
        row.write(col_no(), smart_str( obj.other_first_attack) )
        row.write(col_no(), smart_str( obj.initial_control) )
        row.write(col_no(), smart_str( obj.other_initial_control) )
        row.write(col_no(), smart_str( obj.final_control) )
        row.write(col_no(), smart_str( obj.other_final_control) )
        row.write(col_no(), smart_str( obj.arson_squad_notified) )
        row.write(col_no(), obj.offence_no )
        row.write(col_no(), obj.area )
        row.write(col_no(), smart_str( obj.time_to_control) )
        row.write(col_no(), smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ) )
        row.write(col_no(), smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ) )
        row.write(col_no(), smart_str( obj.get_report_status_display()) )

    book.save(response)

    return response
export_final_csv.short_description = u"Export Excel"


#def activity_names():
#	return [i['name'] for i in ActivityType.objects.all().order_by('id').values()]
#
#def activity_map(obj):
#	bools = []
#	for activity_name in activity_names():
#		if len(obj.activities.all().filter(activity__name__contains=activity_name)) > 0:
#			dt = obj.activities.get(activity__name__contains=activity_name).date.strftime('%Y-%m-%d %H:%M:%S')
#			bools.append([activity_name, row.write(col_no(), smart_str( dt)])
#		else:
#			bools.append([activity_name, row.write(col_no(), smart_str( None)])
#	return bools

