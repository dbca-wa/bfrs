from bfrs.models import Bushfire


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
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.sss_id,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
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
    b.initial_area,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN initial_area_unknown THEN 1
     	 ELSE 0
    END as initial_area_unknown,
    b.authorised_date,
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
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
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
    b.initial_area,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN initial_area_unknown THEN 1
     	 ELSE 0
    END as initial_area_unknown,
    b.authorised_date,
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
    b.fb_validation_req,
    b.created,
    b.modified,
    b.name,
    b.fire_number,
    b.year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
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
    b.initial_area,
    b.area,
    CASE WHEN area_limit THEN 1
     	 ELSE 0
    END as area_limit,
    CASE WHEN initial_area_unknown THEN 1
     	 ELSE 0
    END as initial_area_unknown,
    b.authorised_date,
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


