from bfrs.models import Bushfire
from django.db import connection

def create_bushfirelist_view():
    """
    cursor.execute('''drop view bfrs_bushfirelist_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
    CREATE OR REPLACE VIEW bfrs_bushfirelist_v AS
    SELECT b.id,
    b.origin_point,
    CASE WHEN b.report_status >= 2 THEN ST_AsGeoJSON(st_envelope(b.fire_boundary))
         ELSE ST_AsGeoJSON(b.fire_boundary)
    END as fire_boundary,
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
    CASE WHEN b.media_alert_req IS NULL THEN NULL
         WHEN b.media_alert_req THEN 1
         ELSE 0
    END as media_alert_req,
    CASE WHEN b.park_trail_impacted IS NULL THEN NULL
         WHEN b.park_trail_impacted THEN 1
         ELSE 0
    END as park_trail_impacted,
    b.cause_state,
    b.other_cause,
    b.other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN b.fire_position_override IS NULL THEN NULL
         WHEN b.fire_position_override THEN 1
         ELSE 0
    END as fire_position_override,
    CASE WHEN b.fire_not_found IS NULL THEN NULL
         WHEN b.fire_not_found THEN 1
         ELSE 0
    END as fire_not_found,
    b.other_info,
    b.init_authorised_date,
    b.dispatch_pw,
    CASE WHEN b.dispatch_aerial IS NULL THEN NULL
         WHEN b.dispatch_aerial THEN 1
         ELSE 0
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    CASE WHEN fire_detected_date IS NULL THEN created
         ELSE fire_detected_date
    END as fire_detected_or_created,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN b.arson_squad_notified IS NULL THEN NULL
         WHEN b.arson_squad_notified THEN 1
         ELSE 0
    END as arson_squad_notified,
    CASE WHEN b.investigation_req IS NULL THEN NULL
         WHEN b.investigation_req THEN 1
         ELSE 0
    END as investigation_req,
    b.offence_no,
    b.initial_area,
    b.area,
    CASE WHEN b.area_limit IS NULL THEN NULL
         WHEN b.area_limit THEN 1
         ELSE 0
    END as area_limit,
    CASE WHEN b.initial_area_unknown IS NULL THEN NULL
         WHEN b.initial_area_unknown THEN 1
         ELSE 0
    END as initial_area_unknown,
    b.authorised_date,
    b.report_status,
    CASE WHEN b.archive IS NULL THEN NULL
         WHEN b.archive THEN 1
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
    b.tenure_id
    FROM bfrs_bushfire b
    WHERE b.archive = false AND b.report_status < {};
    '''.format(Bushfire.STATUS_INVALIDATED))

def create_bushfire_view():
    """
    cursor.execute('''drop view bfrs_bushfire_v''')
    """
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute('''
    CREATE OR REPLACE VIEW bfrs_bushfire_v AS
    SELECT b.id,
    b.origin_point,
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
    CASE WHEN media_alert_req IS NULL THEN ''
         WHEN media_alert_req THEN 'Yes'
         ELSE 'No'
    END as media_alert_req,
    CASE WHEN park_trail_impacted IS NULL THEN ''
         WHEN park_trail_impacted THEN 'Yes'
         ELSE 'No'
    END as park_trail_impacted,
    CASE WHEN b.cause_state IS NULL THEN ''
         WHEN b.cause_state = 1 THEN 'Known'
         WHEN b.cause_state = 2 THEN 'Possible'
         ELSE b.cause_state::text
    END as cause_state,
    b.other_cause,
    CASE WHEN b.other_tenure IS NULL THEN ''
         WHEN b.other_tenure = 1 THEN 'Private'
         WHEN b.other_tenure = 2 THEN 'Crown'
         ELSE b.other_tenure::text
    END as other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN b.fire_position_override IS NULL THEN ''
         WHEN b.fire_position_override THEN 'Yes'
         ELSE 'No'
    END as fire_position_override,
    CASE WHEN fire_not_found IS NULL THEN ''
         WHEN fire_not_found THEN 'Yes'
         ELSE 'No'
    END as fire_not_found,
    b.other_info,
    b.init_authorised_date,
    CASE WHEN b.dispatch_pw IS NULL THEN ''
         WHEN b.dispatch_pw = 1 THEN 'Yes'
         WHEN b.dispatch_pw = 2 THEN 'No'
         WHEN b.dispatch_pw = 3 THEN 'Unknown'
         ELSE b.dispatch_pw::text
    END as dispatch_pw,
    CASE WHEN b.dispatch_aerial IS NULL THEN ''
         WHEN b.dispatch_aerial THEN 'Yes'
         ELSE 'No'
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    CASE WHEN b.fire_detected_date IS NULL THEN b.created
         ELSE b.fire_detected_date
    END as fire_detected_or_created,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN b.arson_squad_notified IS NULL THEN ''
         WHEN b.arson_squad_notified THEN 'Yes'
         ELSE 'No'
    END as arson_squad_notified,
    CASE WHEN b.investigation_req IS NULL THEN ''
         WHEN b.investigation_req THEN 'Yes'
         ELSE 'No'
    END as investigation_req,
    b.offence_no,
    b.initial_area,
    b.area,
    CASE WHEN b.area_limit IS NULL THEN ''
         WHEN b.area_limit THEN 'Yes'
         ELSE 'No'
    END as area_limit,
    CASE WHEN initial_area_unknown IS NULL THEN ''
         WHEN initial_area_unknown THEN 'Yes'
         ELSE 'No'
    END as initial_area_unknown,
    b.authorised_date,
    CASE WHEN b.report_status = 1 THEN 'Initial Fire Report'
         WHEN b.report_status = 2 THEN 'Notifications Submitted'
         WHEN b.report_status = 3 THEN 'Report Authorised'
         WHEN b.report_status = 4 THEN 'Reviewed'
         WHEN b.report_status = 5 THEN 'Invalidated'
         WHEN b.report_status = 6 THEN 'Outstanding Fires'
         ELSE b.report_status::text
    END as report_status,
    CASE WHEN b.archive IS NULL THEN ''
         WHEN b.archive THEN 'Yes'
         ELSE 'No'
    END as archive,
    (SELECT username AS authorised_by FROM auth_user WHERE id = b.authorised_by_id),
    (SELECT name AS cause FROM bfrs_cause WHERE id = b.cause_id),
    (SELECT username AS creator FROM auth_user WHERE id = b.creator_id),
    (SELECT name AS district FROM bfrs_district WHERE id = b.district_id),
    (SELECT username AS duty_officer FROM auth_user WHERE id = b.duty_officer_id),
    (SELECT username AS field_officer FROM auth_user WHERE id = b.field_officer_id),
    (SELECT name AS final_control FROM bfrs_agency WHERE id = b.final_control_id),
    (SELECT name AS first_attack FROM bfrs_agency WHERE id = b.first_attack_id),
    (SELECT username AS init_authorised_by FROM auth_user WHERE id = b.init_authorised_by_id),
    (SELECT name AS initial_control FROM bfrs_agency WHERE id = b.initial_control_id),
    (SELECT username AS modifier FROM auth_user WHERE id = b.modifier_id),
    (SELECT name AS region FROM bfrs_region WHERE id = b.region_id),
    (SELECT name AS tenure FROM bfrs_tenure WHERE id = b.tenure_id)
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
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
    CASE WHEN media_alert_req IS NULL THEN ''
         WHEN media_alert_req THEN 'Yes'
         ELSE 'No'
    END as media_alert_req,
    CASE WHEN park_trail_impacted IS NULL THEN ''
         WHEN park_trail_impacted THEN 'Yes'
         ELSE 'No'
    END as park_trail_impacted,
    CASE WHEN b.cause_state IS NULL THEN ''
         WHEN b.cause_state = 1 THEN 'Known'
         WHEN b.cause_state = 2 THEN 'Possible'
         ELSE b.cause_state::text
    END as cause_state,
    b.other_cause,
    CASE WHEN b.other_tenure IS NULL THEN ''
         WHEN b.other_tenure = 1 THEN 'Private'
         WHEN b.other_tenure = 2 THEN 'Crown'
         ELSE b.other_tenure::text
    END as other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN b.fire_position_override IS NULL THEN ''
         WHEN b.fire_position_override THEN 'Yes'
         ELSE 'No'
    END as fire_position_override,
    CASE WHEN fire_not_found IS NULL THEN ''
         WHEN fire_not_found THEN 'Yes'
         ELSE 'No'
    END as fire_not_found,
    b.other_info,
    b.init_authorised_date,
    CASE WHEN b.dispatch_pw IS NULL THEN ''
         WHEN b.dispatch_pw = 1 THEN 'Yes'
         WHEN b.dispatch_pw = 2 THEN 'No'
         WHEN b.dispatch_pw = 3 THEN 'Unknown'
         ELSE b.dispatch_pw::text
    END as dispatch_pw,
    CASE WHEN b.dispatch_aerial IS NULL THEN ''
         WHEN b.dispatch_aerial THEN 'Yes'
         ELSE 'No'
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    CASE WHEN b.fire_detected_date IS NULL THEN b.created
         ELSE b.fire_detected_date
    END as fire_detected_or_created,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN b.arson_squad_notified IS NULL THEN ''
         WHEN b.arson_squad_notified THEN 'Yes'
         ELSE 'No'
    END as arson_squad_notified,
    CASE WHEN b.investigation_req IS NULL THEN ''
         WHEN b.investigation_req THEN 'Yes'
         ELSE 'No'
    END as investigation_req,
    b.offence_no,
    b.initial_area,
    b.area,
    CASE WHEN b.area_limit IS NULL THEN ''
         WHEN b.area_limit THEN 'Yes'
         ELSE 'No'
    END as area_limit,
    CASE WHEN initial_area_unknown IS NULL THEN ''
         WHEN initial_area_unknown THEN 'Yes'
         ELSE 'No'
    END as initial_area_unknown,
    b.authorised_date,
    CASE WHEN b.report_status = 1 THEN 'Initial Fire Report'
         WHEN b.report_status = 2 THEN 'Notifications Submitted'
         WHEN b.report_status = 3 THEN 'Report Authorised'
         WHEN b.report_status = 4 THEN 'Reviewed'
         WHEN b.report_status = 5 THEN 'Invalidated'
         WHEN b.report_status = 6 THEN 'Outstanding Fires'
         ELSE b.report_status::text
    END as report_status,
    CASE WHEN b.archive IS NULL THEN ''
         WHEN b.archive THEN 'Yes'
         ELSE 'No'
    END as archive,
    (SELECT username AS authorised_by FROM auth_user WHERE id = b.authorised_by_id),
    (SELECT name AS cause FROM bfrs_cause WHERE id = b.cause_id),
    (SELECT username AS creator FROM auth_user WHERE id = b.creator_id),
    (SELECT name AS district FROM bfrs_district WHERE id = b.district_id),
    (SELECT username AS duty_officer FROM auth_user WHERE id = b.duty_officer_id),
    (SELECT username AS field_officer FROM auth_user WHERE id = b.field_officer_id),
    (SELECT name AS final_control FROM bfrs_agency WHERE id = b.final_control_id),
    (SELECT name AS first_attack FROM bfrs_agency WHERE id = b.first_attack_id),
    (SELECT username AS init_authorised_by FROM auth_user WHERE id = b.init_authorised_by_id),
    (SELECT name AS initial_control FROM bfrs_agency WHERE id = b.initial_control_id),
    (SELECT username AS modifier FROM auth_user WHERE id = b.modifier_id),
    (SELECT name AS region FROM bfrs_region WHERE id = b.region_id),
    (SELECT name AS tenure FROM bfrs_tenure WHERE id = b.tenure_id)
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
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
    CASE WHEN media_alert_req IS NULL THEN ''
         WHEN media_alert_req THEN 'Yes'
         ELSE 'No'
    END as media_alert_req,
    CASE WHEN park_trail_impacted IS NULL THEN ''
         WHEN park_trail_impacted THEN 'Yes'
         ELSE 'No'
    END as park_trail_impacted,
    CASE WHEN b.cause_state IS NULL THEN ''
         WHEN b.cause_state = 1 THEN 'Known'
         WHEN b.cause_state = 2 THEN 'Possible'
         ELSE b.cause_state::text
    END as cause_state,
    b.other_cause,
    CASE WHEN b.other_tenure IS NULL THEN ''
         WHEN b.other_tenure = 1 THEN 'Private'
         WHEN b.other_tenure = 2 THEN 'Crown'
         ELSE b.other_tenure::text
    END as other_tenure,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
    CASE WHEN b.fire_position_override IS NULL THEN ''
         WHEN b.fire_position_override THEN 'Yes'
         ELSE 'No'
    END as fire_position_override,
    CASE WHEN fire_not_found IS NULL THEN ''
         WHEN fire_not_found THEN 'Yes'
         ELSE 'No'
    END as fire_not_found,
    b.other_info,
    b.init_authorised_date,
    CASE WHEN b.dispatch_pw IS NULL THEN ''
         WHEN b.dispatch_pw = 1 THEN 'Yes'
         WHEN b.dispatch_pw = 2 THEN 'No'
         WHEN b.dispatch_pw = 3 THEN 'Unknown'
         ELSE b.dispatch_pw::text
    END as dispatch_pw,
    CASE WHEN b.dispatch_aerial IS NULL THEN ''
         WHEN b.dispatch_aerial THEN 'Yes'
         ELSE 'No'
    END as dispatch_aerial,
    b.dispatch_pw_date,
    b.dispatch_aerial_date,
    b.fire_detected_date,
    CASE WHEN b.fire_detected_date IS NULL THEN b.created
         ELSE b.fire_detected_date
    END as fire_detected_or_created,
    b.fire_contained_date,
    b.fire_controlled_date,
    b.fire_safe_date,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
    CASE WHEN b.arson_squad_notified IS NULL THEN ''
         WHEN b.arson_squad_notified THEN 'Yes'
         ELSE 'No'
    END as arson_squad_notified,
    CASE WHEN b.investigation_req IS NULL THEN ''
         WHEN b.investigation_req THEN 'Yes'
         ELSE 'No'
    END as investigation_req,
    b.offence_no,
    b.initial_area,
    b.area,
    CASE WHEN b.area_limit IS NULL THEN ''
         WHEN b.area_limit THEN 'Yes'
         ELSE 'No'
    END as area_limit,
    CASE WHEN initial_area_unknown IS NULL THEN ''
         WHEN initial_area_unknown THEN 'Yes'
         ELSE 'No'
    END as initial_area_unknown,
    b.authorised_date,
    CASE WHEN b.report_status = 1 THEN 'Initial Fire Report'
         WHEN b.report_status = 2 THEN 'Notifications Submitted'
         WHEN b.report_status = 3 THEN 'Report Authorised'
         WHEN b.report_status = 4 THEN 'Reviewed'
         WHEN b.report_status = 5 THEN 'Invalidated'
         WHEN b.report_status = 6 THEN 'Outstanding Fires'
         ELSE b.report_status::text
    END as report_status,
    CASE WHEN b.archive IS NULL THEN ''
         WHEN b.archive THEN 'Yes'
         ELSE 'No'
    END as archive,
    (SELECT username AS authorised_by FROM auth_user WHERE id = b.authorised_by_id),
    (SELECT name AS cause FROM bfrs_cause WHERE id = b.cause_id),
    (SELECT username AS creator FROM auth_user WHERE id = b.creator_id),
    (SELECT name AS district FROM bfrs_district WHERE id = b.district_id),
    (SELECT username AS duty_officer FROM auth_user WHERE id = b.duty_officer_id),
    (SELECT username AS field_officer FROM auth_user WHERE id = b.field_officer_id),
    (SELECT name AS final_control FROM bfrs_agency WHERE id = b.final_control_id),
    (SELECT name AS first_attack FROM bfrs_agency WHERE id = b.first_attack_id),
    (SELECT username AS init_authorised_by FROM auth_user WHERE id = b.init_authorised_by_id),
    (SELECT name AS initial_control FROM bfrs_agency WHERE id = b.initial_control_id),
    (SELECT username AS modifier FROM auth_user WHERE id = b.modifier_id),
    (SELECT name AS region FROM bfrs_region WHERE id = b.region_id),
    (SELECT name AS tenure FROM bfrs_tenure WHERE id = b.tenure_id)
    FROM bfrs_bushfire b
    WHERE b.archive = false AND b.report_status < {};
    '''.format(Bushfire.STATUS_INVALIDATED))


def test_view():
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_v''')
    return cursor.fetchall()

def test_final_view():
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_final_fireboundary_v''')
    return cursor.fetchall()

def test_fireboundary_view():
    cursor=connection.cursor()
    cursor.execute('''select fire_number, year, district_id from bfrs_bushfire_fireboundary_v''')
    return cursor.fetchall()

def drop_view():
    try:
        cursor=connection.cursor()
        cursor.execute('''drop view bfrs_bushfire_v''')
        return cursor.fetchall()
    except:
        pass

def drop_final_view():
    try:
        cursor=connection.cursor()
        cursor.execute('''drop view bfrs_bushfire_final_fireboundary_v''')
        return cursor.fetchall()
    except:
        pass

def drop_fireboundary_view():
    try:
        cursor=connection.cursor()
        cursor.execute('''drop view bfrs_bushfire_fireboundary_v''')
        return cursor.fetchall()
    except:
        pass



