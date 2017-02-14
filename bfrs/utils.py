from bfrs.models import (Bushfire, Activity, AreaBurnt, AttendingOrganisation, GroundForces,
        AerialForces, FireBehaviour, Legal, PrivateDamage, PublicDamage, Response, Comment,
        ActivityType,
    )
from django.db import IntegrityError, transaction
from django.http import HttpResponse
import json

import unicodecsv
from django.utils.encoding import smart_str
from datetime import datetime


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

def save_initial_snapshot(obj):
    initial_snapshot = dict(
        bushfire_id = obj.id,
        region = obj.region.name,
        district = obj.district.name,
        name = obj.name,
        year = obj.year,
        incident_no = obj.incident_no if obj.incident_no else '',
        job_code = obj.job_code if obj.job_code else '',
        field_officer = obj.field_officer.get_full_name() if obj.field_officer else '',
        duty_officer = obj.duty_officer.get_full_name() if obj.duty_officer else '',
        init_authorised_by = obj.init_authorised_by.get_full_name() if obj.init_authorised_by else '',
        init_authorised_date = obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else '',

        potential_fire_level = obj.get_potential_fire_level_display() if obj.potential_fire_level else '',
        media_alert_req = obj.media_alert_req,
        fire_position = obj.fire_position if obj.fire_position else '',

        # Point of Origin
        grid = obj.grid,
        arrival_area = float(obj.arrival_area) if obj.arrival_area else '',
        fire_not_found = obj.fire_not_found,
#        coord_type = obj.get_coord_type_display(), # if obj.coord_type else '',
#        lat_decimal = float(obj.lat_decimal) if obj.lat_decimal else '',
#        lat_degrees = float(obj.lat_degrees) if obj.lat_degrees else '',
#        lat_minutes = float(obj.lat_minutes) if obj.lat_minutes else '',
#        lon_decimal = float(obj.lon_decimal) if obj.lon_decimal else '',
#        lon_degrees = float(obj.lon_degrees) if obj.lon_degrees else '',
#        lon_minutes = float(obj.lon_minutes) if obj.lon_minutes else '',
#
#        mga_zone = float(obj.mga_zone) if obj.mga_zone else '',
#        mga_easting = float(obj.mga_easting) if obj.mga_easting else '',
#        mga_northing = float(obj.mga_northing) if obj.mga_northing else '',
#
#        fd_letter = float(obj.fd_letter) if obj.fd_letter else '',
#        fd_number = float(obj.fd_number) if obj.fd_number else '',
#        fd_tenths = float(obj.fd_tenths) if obj.fd_tenths else '',

        # Activities - Formset
        activities = [(i.to_dict()) for i in obj.activities.all()],

        # Tenure and Vegetation Affected - Formset
        tenures_burnt = [(i.to_dict()) for i in obj.tenures_burnt.all()],

        # Operation Details
        assistance_req = obj.assistance_req,
        communications = obj.communications if obj.communications else '',
        other_info = obj.other_info if obj.other_info else '',
        cause = obj.cause.name,
        other_cause = obj.other_cause if obj.other_cause else '',
        #tenure = obj.tenure if obj.tenure else '',
        #fuel = obj.fuel if obj.fuel else '',

    )
    obj.initial_snapshot = json.dumps(initial_snapshot)
    obj.save()


#def save_initial_snapshot(obj):
#    initial_snapshot = dict(
#        bushfire_id = obj.id,
#        region = obj.region.name,
#        district = obj.district.name,
#        name = obj.name,
#        incident_no = obj.incident_no if obj.incident_no else '',
#        season = obj.season if obj.season else '',
#        job_code = obj.job_code if obj.job_code else '',
#        potential_fire_level = obj.potential_fire_level if obj.potential_fire_level else '',
#        field_officer = obj.field_officer.get_full_name() if obj.field_officer else '',
#        init_authorised_by = obj.init_authorised_by.get_full_name() if obj.init_authorised_by else '',
#        init_authorised_date = obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else '',
#        cause = obj.cause.name,
#        known_possible = Bushfire.CAUSE_CHOICES[0][1] if obj.known_possible==Bushfire.CAUSE_CHOICES[0][0] else Bushfire.CAUSE_CHOICES[1][1],
#        other_cause = obj.other_cause if obj.other_cause else '',
#        investigation_req = 'Yes' if obj.investigation_req else 'No',
#        first_attack = obj.first_attack.name,
#        other_first_attack = obj.other_first_attack if obj.other_first_attack else '',
#
#        # Point of Origin
#        coord_type = obj.coord_type if obj.coord_type else '',
#        fire_not_found = 'Not Found' if obj.fire_not_found else '',
#        lat_decimal = float(obj.lat_decimal) if obj.lat_decimal else '',
#        lat_degrees = float(obj.lat_degrees) if obj.lat_degrees else '',
#        lat_minutes = float(obj.lat_minutes) if obj.lat_minutes else '',
#        lon_decimal = float(obj.lon_decimal) if obj.lon_decimal else '',
#        lon_degrees = float(obj.lon_degrees) if obj.lon_degrees else '',
#        lon_minutes = float(obj.lon_minutes) if obj.lon_minutes else '',
#
#        mga_zone = float(obj.mga_zone) if obj.mga_zone else '',
#        mga_easting = float(obj.mga_easting) if obj.mga_easting else '',
#        mga_northing = float(obj.mga_northing) if obj.mga_northing else '',
#
#        fd_letter = float(obj.fd_letter) if obj.fd_letter else '',
#        fd_number = float(obj.fd_number) if obj.fd_number else '',
#        fd_tenths = float(obj.fd_tenths) if obj.fd_tenths else '',
#
#        # Activities - Formset
#        activities = [(i.to_dict()) for i in obj.activities.all()],
#
#        # Tenure and Vegetation Affected - Formset
#        areas_burnt = [(i.to_dict()) for i in obj.areas_burnt.all()],
#
#        # Location
#        distance = float(obj.distance) if obj.distance else '',
#        direction = obj.direction if obj.direction else '',
#        place = obj.place if obj.place else '',
#        lot_no = obj.lot_no if obj.lot_no else '',
#        street = obj.street if obj.street else '',
#        town = obj.town if obj.town else '',
#
#        # Forces in Attendance - Formset
#
#        # Operation Details
#        fuel = obj.fuel if obj.fuel else '',
#        ros = obj.ros if obj.ros else '',
#        flame_height = obj.flame_height if obj.flame_height else '',
#        assistance_required = 'Yes' if obj.assistance_required else 'No',
#        fire_contained = 'Yes' if obj.fire_contained else 'No',
#        containment_time = obj.containment_time if obj.containment_time else '',
#        ops_point = obj.ops_point if obj.ops_point else '',
#        communications = obj.communications if obj.communications else '',
#        weather = obj.weather if obj.weather else ''
#
#    )
#    obj.initial_snapshot = json.dumps(initial_snapshot)

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

# init methods
def update_activity_fs(bushfire, activity_formset):
    new_fs_object = []
    for form in activity_formset:
        if form.is_valid():
            activity = form.cleaned_data.get('activity')
            dt = form.cleaned_data.get('date')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (activity and dt):
                new_fs_object.append(Activity(bushfire=bushfire, activity=activity, date=dt))

    try:
        with transaction.atomic():
            #Replace the old with the new
            Activity.objects.filter(bushfire=bushfire).delete()
            Activity.objects.bulk_create(new_fs_object)
    except IntegrityError: #If the transaction failed
        return 0

    return 1


def update_areas_burnt_fs(bushfire, area_burnt_formset):
    new_fs_object = []
    for form in area_burnt_formset:
        if form.is_valid():
            tenure = form.cleaned_data.get('tenure')
            #fuel_type = form.cleaned_data.get('fuel_type')
            #area = form.cleaned_data.get('area')
            #origin = form.cleaned_data.get('origin')
            remove = form.cleaned_data.get('DELETE')

            #if not remove and (tenure and fuel_type and area):
            #if not remove and (tenure and fuel_type):
            if not remove and tenure:
                #new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, fuel_type=fuel_type, area=area, origin=origin))
                #new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, fuel_type=fuel_type))
                new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure))

    try:
        with transaction.atomic():
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_attending_org_fs(bushfire, attending_org_formset):
    new_fs_object = []
    for form in attending_org_formset:
        if form.is_valid():
            name = form.cleaned_data.get('name')
            other = form.cleaned_data.get('other')
            remove = form.cleaned_data.get('DELETE')

            #if not remove and (name and other):
            if not remove and name:
                new_fs_object.append(AttendingOrganisation(bushfire=bushfire, name=name, other=other))

    try:
        with transaction.atomic():
            AttendingOrganisation.objects.filter(bushfire=bushfire).delete()
            AttendingOrganisation.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

# final methods
def update_groundforces_fs(bushfire, groundforces_formset):
    new_fs_object = []
    #groundforces_formset.cleaned_data # hack - form.cleaned_data is unavailable unless this is called
    for form in groundforces_formset:
        if form.is_valid():
            name = form.cleaned_data.get('name')
            persons = form.cleaned_data.get('persons')
            pumpers = form.cleaned_data.get('pumpers')
            plant = form.cleaned_data.get('plant')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (name and persons and pumpers and plant):
                new_fs_object.append(GroundForces(bushfire=bushfire, name=name, persons=persons, pumpers=persons, plant=plant))

    try:
        with transaction.atomic():
            GroundForces.objects.filter(bushfire=bushfire).delete()
            GroundForces.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_aerialforces_fs(bushfire, aerialforces_formset):
    new_fs_object = []
    #aerialforces_formset.cleaned_data # hack - form.cleaned_data is unavailable unless this is called
    for form in aerialforces_formset:
        if form.is_valid():
            name = form.cleaned_data.get('name')
            observer = form.cleaned_data.get('observer')
            transporter = form.cleaned_data.get('transporter')
            ignition = form.cleaned_data.get('ignition')
            water_bomber = form.cleaned_data.get('water_bomber')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (name and observer and transporter and ignition and water_bomber):
                new_fs_object.append(AerialForces(bushfire=bushfire, name=name, observer=observer, transporter=transporter, ignition=ignition, water_bomber=water_bomber))

    try:
        with transaction.atomic():
            AerialForces.objects.filter(bushfire=bushfire).delete()
            AerialForces.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_fire_behaviour_fs(bushfire, fire_behaviour_formset):
    new_fs_object = []
    for form in fire_behaviour_formset:
        if form.is_valid():
            name = form.cleaned_data.get('name')
            fuel_type = form.cleaned_data.get('fuel_type')
            fuel_weight = form.cleaned_data.get('fuel_weight')
            fdi = form.cleaned_data.get('fdi')
            ros = form.cleaned_data.get('ros')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (name and fuel_type and fuel_weight and fdi and ros):
                new_fs_object.append(FireBehaviour(bushfire=bushfire, name=name, fuel_type=fuel_type, fuel_weight=fuel_weight, fdi=fdi, ros=ros))

    try:
        with transaction.atomic():
            FireBehaviour.objects.filter(bushfire=bushfire).delete()
            FireBehaviour.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_legal_fs(bushfire, legal_formset):
    new_fs_object = []
    for form in legal_formset:
        if form.is_valid():
            protection = form.cleaned_data.get('protection')
            cost = form.cleaned_data.get('cost')
            restricted_period = form.cleaned_data.get('restricted_period')
            prohibited_period = form.cleaned_data.get('prohibited_period')
            inv_undertaken = form.cleaned_data.get('inv_undertaken')
            legal_result = form.cleaned_data.get('legal_result')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (protection and cost and inv_undertaken and legal_result):
                new_fs_object.append(
                    Legal(bushfire=bushfire, protection=protection, cost=cost, restricted_period=restricted_period,
                        prohibited_period=prohibited_period, inv_undertaken=inv_undertaken, legal_result=legal_result
                    )
                )

    try:
        with transaction.atomic():
            Legal.objects.filter(bushfire=bushfire).delete()
            Legal.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_private_damage_fs(bushfire, private_damage_formset):
    new_fs_object = []
    for form in private_damage_formset:
        if form.is_valid():
            damage_type = form.cleaned_data.get('damage_type')
            number = form.cleaned_data.get('number')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (damage_type and number):
                new_fs_object.append(PrivateDamage(bushfire=bushfire, damage_type=damage_type, number=number))

    try:
        with transaction.atomic():
            PrivateDamage.objects.filter(bushfire=bushfire).delete()
            PrivateDamage.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_public_damage_fs(bushfire, public_damage_formset):
    new_fs_object = []
    for form in public_damage_formset:
        if form.is_valid():
            damage_type = form.cleaned_data.get('damage_type')
            fuel_type = form.cleaned_data.get('fuel_type')
            area = form.cleaned_data.get('area')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (damage_type and fuel_type and area):
                new_fs_object.append(PublicDamage(bushfire=bushfire, damage_type=damage_type, fuel_type=fuel_type, area=area))

    try:
        with transaction.atomic():
            PublicDamage.objects.filter(bushfire=bushfire).delete()
            PublicDamage.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_response_fs(bushfire, response_formset):
    new_fs_object = []
    for form in response_formset:
        if form.is_valid():
            response = form.cleaned_data.get('response')
            remove = form.cleaned_data.get('DELETE')

            if not remove and response:
                new_fs_object.append(Response(bushfire=bushfire, response=response))

    try:
        with transaction.atomic():
            Response.objects.filter(bushfire=bushfire).delete()
            Response.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_comment_fs(bushfire, request, comment_formset):
    new_fs_object = []
    for form in comment_formset:
        if form.is_valid():
            comment = form.cleaned_data.get('comment')
            remove = form.cleaned_data.get('DELETE')

            if not remove and comment:
                if request.user.id:
                    new_fs_object.append(Comment(bushfire=bushfire, comment=comment, creator_id=request.user.id, modifier_id=request.user.id))
                else:
                    new_fs_object.append(Comment(bushfire=bushfire, comment=comment, creator_id=1, modifier_id=1))

    try:
        with transaction.atomic():
            Comment.objects.filter(bushfire=bushfire).delete()
            Comment.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

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
		"DFES Incident Nno",
		"Job Ccode",
		"Potential Fire Level",
		"Media Alert Req",
		"Fire Position",
		#"Origin Point",
		#"Fire Boundary",
		"Grid",
		"Arrival Area",
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
		#"Initial Snapshot",
		"First Attack",
		"Other First Attack",
		"Initial Control",
		"Other Initial Ctrl",
		"Final Control",
		"Other Final Ctrl",
		"Max Fire Level",
		"Arson Squad Notified",
		"Offence No",
		"Final Area",
		"Authorised By",
		"Authorised Date",
		"Report Status",
    ] #+
#		[i for i in activity_names()]
	)
    for obj in queryset:
		writer.writerow([
			smart_str(obj.id),
			smart_str(obj.region.name),
			smart_str(obj.district.name),
			smart_str(obj.name),
			smart_str(obj.year),
			smart_str(obj.incident_no),
			smart_str(obj.dfes_incident_no),
			smart_str(obj.job_code),
			smart_str(obj.get_potential_fire_level_display()),
			smart_str(obj.media_alert_req),
			smart_str(obj.fire_position),
			#smart_str(obj.origin_point),
			#smart_str(obj.fire_boundary),
			smart_str(obj.grid),
			smart_str(obj.arrival_area),
			smart_str(obj.fire_not_found),
			smart_str(obj.assistance_req),
			smart_str(obj.communications),
			smart_str(obj.other_info),
			smart_str(obj.cause),
			smart_str(obj.other_cause),
			smart_str(obj.field_officer.get_full_name() if obj.field_officer else None ),
			smart_str(obj.duty_officer.get_full_name() if obj.duty_officer else None ),
			smart_str(obj.init_authorised_by.get_full_name() if obj.init_authorised_by else None ),
			smart_str(obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else None),
			#smart_str(obj.initial_snapshot),
			smart_str(obj.first_attack),
			smart_str(obj.other_first_attack),
			smart_str(obj.initial_control),
			smart_str(obj.other_initial_ctrl),
			smart_str(obj.final_control),
			smart_str(obj.other_final_ctrl),
			smart_str(obj.max_fire_level),
			smart_str(obj.arson_squad_notified),
			smart_str(obj.offence_no),
			smart_str(obj.final_area),
			smart_str(obj.authorised_by.get_full_name() if obj.authorised_by else None ),
			smart_str(obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ),
			smart_str(obj.get_report_status_display()),
        ] #+
#			[i[1] for i in activity_map(obj)]
	)
    return response
export_final_csv.short_description = u"Export CSV (Final)"

def activity_names():
	return [i['name'] for i in ActivityType.objects.all().order_by('id').values()]

#def activity_bools(obj):
#	bools = []
#	[bools.append([name, True if len(obj.activities.all().filter(activity__name__contains=name))>0 else False]) for name in activity_names()]
#	return [smart_str(activity[1]) for activity in bools]

def activity_map(obj):
	bools = []
	for activity_name in activity_names():
		if len(obj.activities.all().filter(activity__name__contains=activity_name)) > 0:
			dt = obj.activities.get(activity__name__contains=activity_name).date.strftime('%Y-%m-%d %H:%M:%S')
			bools.append([activity_name, smart_str(dt)])
		else:
			bools.append([activity_name, smart_str(None)])
	return bools

