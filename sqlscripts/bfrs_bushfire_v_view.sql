CREATE VIEW public.bfrs_bushfire_v_2 AS
 SELECT b.id,
    b.origin_point,
    b.fb_validation_req,
    to_char(timezone('Australia/Perth'::text, b.created), 'DD/MM/YYYY HH24:MI:SS'::text) AS created,
    to_char(timezone('Australia/Perth'::text, b.modified), 'DD/MM/YYYY HH24:MI:SS'::text) AS modified,
    b.name,
    b.fire_number,
    (((b.year)::text || '/'::text) || ((b.year + 1))::text) AS financial_year,
    b.reporting_year,
    b.prob_fire_level,
    b.max_fire_level,
        CASE
            WHEN (b.media_alert_req IS NULL) THEN ''::text
            WHEN b.media_alert_req THEN 'Yes'::text
            ELSE 'No'::text
        END AS media_alert_req,
        CASE
            WHEN (b.park_trail_impacted IS NULL) THEN ''::text
            WHEN b.park_trail_impacted THEN 'Yes'::text
            ELSE 'No'::text
        END AS park_trail_impacted,
        CASE
            WHEN (b.cause_state IS NULL) THEN ''::text
            WHEN (b.cause_state = 1) THEN 'Known'::text
            WHEN (b.cause_state = 2) THEN 'Possible'::text
            ELSE (b.cause_state)::text
        END AS cause_state,
    b.other_cause,
    b.dfes_incident_no,
    b.job_code,
    b.fire_position,
        CASE
            WHEN (b.fire_position_override IS NULL) THEN ''::text
            WHEN b.fire_position_override THEN 'Yes'::text
            ELSE 'No'::text
        END AS fire_position_override,
        CASE
            WHEN (b.fire_not_found IS NULL) THEN ''::text
            WHEN b.fire_not_found THEN 'Yes'::text
            ELSE 'No'::text
        END AS fire_not_found,
    b.other_info,
    to_char(timezone('Australia/Perth'::text, b.init_authorised_date), 'DD/MM/YYYY HH24:MI:SS'::text) AS init_authorised_date,
        CASE
            WHEN (b.dispatch_pw IS NULL) THEN ''::text
            WHEN (b.dispatch_pw = 1) THEN 'Yes'::text
            WHEN (b.dispatch_pw = 2) THEN 'No'::text
            WHEN (b.dispatch_pw = 3) THEN 'Unknown'::text
            ELSE (b.dispatch_pw)::text
        END AS dispatch_pw,
        CASE
            WHEN (b.dispatch_aerial IS NULL) THEN ''::text
            WHEN b.dispatch_aerial THEN 'Yes'::text
            ELSE 'No'::text
        END AS dispatch_aerial,
        CASE
            WHEN (b.valid_bushfire_id IS NULL) THEN NULL::text
            ELSE ( SELECT
                    CASE
                        WHEN (lb.report_status = 1) THEN 'Initial Fire Report'::text
                        WHEN (lb.report_status = 2) THEN 'Notifications Submitted'::text
                        WHEN (lb.report_status = 3) THEN 'Report Authorised'::text
                        WHEN (lb.report_status = 4) THEN 'Reviewed'::text
                        WHEN (lb.report_status = 5) THEN 'Invalidated'::text
                        WHEN (lb.report_status = 6) THEN 'Outstanding Fires'::text
                        WHEN (lb.report_status = 100) THEN 'Merged Fires'::text
                        WHEN (lb.report_status = 101) THEN 'Duplicate Fires'::text
                        ELSE (lb.report_status)::text
                    END AS report_status
               FROM public.bfrs_bushfire lb
              WHERE (lb.id = b.valid_bushfire_id))
        END AS linked_bushfire_status,
        CASE
            WHEN (b.valid_bushfire_id IS NULL) THEN NULL::character varying
            ELSE ( SELECT bfrs_bushfire.fire_number
               FROM public.bfrs_bushfire
              WHERE (bfrs_bushfire.id = b.valid_bushfire_id))
        END AS linked_bushfire_number,
    to_char(timezone('Australia/Perth'::text, b.dispatch_pw_date), 'DD/MM/YYYY HH24:MI:SS'::text) AS dispatch_pw_date,
    to_char(timezone('Australia/Perth'::text, b.dispatch_aerial_date), 'DD/MM/YYYY HH24:MI:SS'::text) AS dispatch_aerial_date,
    to_char(timezone('Australia/Perth'::text, b.fire_detected_date), 'DD/MM/YYYY'::text) AS fire_detected_date,
    to_char(timezone('Australia/Perth'::text, b.fire_contained_date), 'DD/MM/YYYY HH24:MI'::text) AS fire_contained_date,
    to_char(timezone('Australia/Perth'::text, b.fire_controlled_date), 'DD/MM/YYYY HH24:MI'::text) AS fire_controlled_date,
    to_char(timezone('Australia/Perth'::text, b.fire_safe_date), 'DD/MM/YYYY HH24:MI'::text) AS fire_safe_date,
        CASE
            WHEN (b.fire_detected_date IS NULL) THEN b.created
            ELSE b.fire_detected_date
        END AS fire_detected_or_created,
    b.other_first_attack,
    b.other_initial_control,
    b.other_final_control,
        CASE
            WHEN (b.arson_squad_notified IS NULL) THEN ''::text
            WHEN b.arson_squad_notified THEN 'Yes'::text
            ELSE 'No'::text
        END AS arson_squad_notified,
        CASE
            WHEN (b.investigation_req IS NULL) THEN ''::text
            WHEN b.investigation_req THEN 'Yes'::text
            ELSE 'No'::text
        END AS investigation_req,
    b.offence_no,
    b.initial_area,
    b.area,
        CASE
            WHEN (b.area_limit IS NULL) THEN ''::text
            WHEN b.area_limit THEN 'Yes'::text
            ELSE 'No'::text
        END AS area_limit,
        CASE
            WHEN (b.initial_area_unknown IS NULL) THEN ''::text
            WHEN b.initial_area_unknown THEN 'Yes'::text
            ELSE 'No'::text
        END AS initial_area_unknown,
    to_char(timezone('Australia/Perth'::text, b.authorised_date), 'DD/MM/YYYY HH24:MI:SS'::text) AS authorised_date,
        CASE
            WHEN (b.report_status = 1) THEN 'Initial Fire Report'::text
            WHEN (b.report_status = 2) THEN 'Notifications Submitted'::text
            WHEN (b.report_status = 3) THEN 'Report Authorised'::text
            WHEN (b.report_status = 4) THEN 'Reviewed'::text
            WHEN (b.report_status = 5) THEN 'Invalidated'::text
            WHEN (b.report_status = 6) THEN 'Outstanding Fires'::text
            WHEN (b.report_status = 100) THEN 'Merged Fires'::text
            WHEN (b.report_status = 101) THEN 'Duplicate Fires'::text
            ELSE (b.report_status)::text
        END AS report_status,
        CASE
            WHEN (b.archive IS NULL) THEN ''::text
            WHEN b.archive THEN 'Yes'::text
            ELSE 'No'::text
        END AS archive,
    ( SELECT auth_user.username AS authorised_by
           FROM public.auth_user
          WHERE (auth_user.id = b.authorised_by_id)) AS authorised_by,
    ( SELECT bfrs_cause.name AS cause
           FROM public.bfrs_cause
          WHERE (bfrs_cause.id = b.cause_id)) AS cause,
    ( SELECT auth_user.username AS creator
           FROM public.auth_user
          WHERE (auth_user.id = b.creator_id)) AS creator,
    ( SELECT bfrs_district.name AS district
           FROM public.bfrs_district
          WHERE (bfrs_district.id = b.district_id)) AS district,
    ( SELECT auth_user.username AS duty_officer
           FROM public.auth_user
          WHERE (auth_user.id = b.duty_officer_id)) AS duty_officer,
    ( SELECT auth_user.username AS field_officer
           FROM public.auth_user
          WHERE (auth_user.id = b.field_officer_id)) AS field_officer,
    ( SELECT bfrs_agency.name AS final_control
           FROM public.bfrs_agency
          WHERE (bfrs_agency.id = b.final_control_id)) AS final_control,
    ( SELECT bfrs_agency.name AS first_attack
           FROM public.bfrs_agency
          WHERE (bfrs_agency.id = b.first_attack_id)) AS first_attack,
    ( SELECT auth_user.username AS init_authorised_by
           FROM public.auth_user
          WHERE (auth_user.id = b.init_authorised_by_id)) AS init_authorised_by,
    ( SELECT bfrs_agency.name AS initial_control
           FROM public.bfrs_agency
          WHERE (bfrs_agency.id = b.initial_control_id)) AS initial_control,
    ( SELECT auth_user.username AS modifier
           FROM public.auth_user
          WHERE (auth_user.id = b.modifier_id)) AS modifier,
    ( SELECT bfrs_region.name AS region
           FROM public.bfrs_region
          WHERE (bfrs_region.id = b.region_id)) AS region,
    ( SELECT bfrs_tenure.name AS tenure
           FROM public.bfrs_tenure
          WHERE (bfrs_tenure.id = b.tenure_id)) AS tenure
   FROM public.bfrs_bushfire b
  WHERE ((b.archive = false) AND ((b.report_status < 5) OR (b.report_status = 100)));