CREATE OR REPLACE FUNCTION to_status(IN bushfireid INTEGER,IN status INT) RETURNS SMALLINT
AS $$
DECLARE reportstatus SMALLINT;
DECLARE snapshotid INTEGER;
DECLARE snapshottype SMALLINT;
--snapshot_type:1 initial, 2 final
DECLARE snapshotcursor CURSOR (bushfireid INTEGER,snapshottype SMALLINT) IS SELECT id FROM bfrs_bushfiresnapshot WHERE bushfire_id = bushfireid and snapshot_type >= snapshottype;
BEGIN
    SELECT report_status INTO reportstatus FROM bfrs_bushfire WHERE id = bushfireid;
    IF reportstatus IS NULL THEN
        RAISE EXCEPTION 'Bushfire (%) not found',bushfireid;
    ELSIF reportstatus = status THEN
        RAISE NOTICE 'Bushfire is already at target status %',status;
    ELSIF reportstatus >= 5 THEN
        RAISE EXCEPTION 'Report status % not support',reportstatus;
    ELSIF reportstatus < status THEN
        RAISE EXCEPTION 'Report is at a previous status';
    ELSE
        IF status = 1 THEN
            snapshottype := 1;
        ELSIF status = 2 THEN
            snapshottype := 2;
        ELSE
            snapshottype := 10;
        END IF;
        --to initial report
        FOR snapshot IN snapshotcursor(bushfireid,snapshottype) LOOP
            snapshotid := snapshot.id;
            DELETE FROM bfrs_bushfirepropertysnapshot WHERE snapshot_id = snapshotid;
            DELETE FROM bfrs_areaburntsnapshot WHERE snapshot_id = snapshotid;
            DELETE FROM bfrs_damagesnapshot WHERE snapshot_id = snapshotid;
            DELETE FROM bfrs_injurysnapshot WHERE snapshot_id = snapshotid;
        END LOOP;
        DELETE FROM bfrs_bushfiresnapshot WHERE bushfire_id = bushfireid and snapshot_type >= snapshottype;
        IF status = 1 THEN
            UPDATE bfrs_bushfire SET report_status = status,init_authorised_date=null,init_authorised_by_id=null,authorised_date=null,authorised_by_id=null,reviewed_date=null,reviewed_by_id=null WHERE id = bushfireid;
        ELSIF status = 2 THEN
            UPDATE bfrs_bushfire SET report_status = status,authorised_date=null,authorised_by_id=null,reviewed_date=null,reviewed_by_id=null WHERE id = bushfireid;
        ELSIF status = 3 THEN
            UPDATE bfrs_bushfire SET report_status = status,reviewed_date=null,reviewed_by_id=null WHERE id = bushfireid;
        ELSE
            UPDATE bfrs_bushfire SET report_status = status WHERE id = bushfireid;
        END IF;
    END IF;

    RETURN reportstatus;
    
END;
$$ LANGUAGE plpgsql
