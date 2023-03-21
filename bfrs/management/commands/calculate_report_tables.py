from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
import os
import sys
from django.db import connection
import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):

    def handle(self, *args, **options):
        print ('Started calculate report tables')
        csr = connection.cursor()

        csr.execute("""               
--------------------------------------------------------------------
--reporting_bushfire and reporting_areaburnt CREATION AND INDEXES
---------------------------------------------------------------------
DROP TABLE IF EXISTS reporting_bushfire;
CREATE TABLE reporting_bushfire AS SELECT * FROM bfrs_bushfire;
--CREATE INDEX idx_reporting_bushfire_origin ON reporting_bushfire USING GIST(origin_point);
DROP INDEX IF EXISTS idx_reporting_bushfire_tenure;
CREATE INDEX idx_reporting_bushfire_tenure ON reporting_bushfire (tenure_id);
DROP INDEX IF EXISTS idx_reporting_bushfire_region;
CREATE INDEX idx_reporting_bushfire_region ON reporting_bushfire (region_id);
DROP INDEX IF EXISTS idx_reporting_bushfire_rpt_status;
CREATE INDEX idx_reporting_bushfire_rpt_status ON reporting_bushfire (report_status);
DROP INDEX IF EXISTS idx_reporting_bushfire_rpt_year;
CREATE INDEX idx_reporting_bushfire_rpt_year ON reporting_bushfire (reporting_year);
DROP TABLE IF EXISTS reporting_areaburnt;
CREATE TABLE reporting_areaburnt AS SELECT * FROM bfrs_areaburnt;
ALTER TABLE reporting_areaburnt DROP CONSTRAINT IF EXISTS reporting_areaburnt_bushfire_id_tenure_id_key;
ALTER TABLE reporting_areaburnt ADD COLUMN region_id Integer;
ALTER TABLE reporting_areaburnt ADD COLUMN has_fire_boundary Boolean;
CREATE INDEX idx_reporting_areaburnt_tenure ON reporting_areaburnt(tenure_id);
CREATE INDEX idx_reporting_areaburnt_bushfire ON reporting_areaburnt(bushfire_id);
CREATE INDEX idx_reporting_areaburnt_region ON reporting_areaburnt(region_id);
DELETE FROM reporting_areaburnt WHERE bushfire_id IN
    (SELECT id FROM reporting_bushfire WHERE fire_boundary IS NOT NULL);
UPDATE reporting_areaburnt ab SET region_id = (SELECT bf.region_id FROM reporting_bushfire bf WHERE ab.bushfire_id = bf.id);
UPDATE reporting_areaburnt SET has_fire_boundary = False;
--make valid geometries (NB checked cadastre_for_bfrs and no invalid geometries
UPDATE reporting_bushfire SET fire_boundary = ST_CollectionExtract(ST_MakeValid(fire_boundary), 3) WHERE NOT ST_IsValid(fire_boundary);
UPDATE reporting_state_forest SET shape = ST_CollectionExtract(ST_MakeValid(shape), 3) WHERE NOT ST_IsValid(shape);
UPDATE reporting_cadastre SET shape = ST_CollectionExtract(ST_MakeValid(shape), 3) WHERE NOT ST_IsValid(shape);
UPDATE reporting_dept_managed SET geometry = ST_CollectionExtract(ST_MakeValid(geometry), 3) WHERE NOT ST_IsValid(geometry);
UPDATE reporting_dept_interest SET geometry = ST_CollectionExtract(ST_MakeValid(geometry), 3) WHERE NOT ST_IsValid(geometry);
----------------------------------------
--GET REGION-CROSSING FIRES
----------------------------------------
DROP TABLE IF EXISTS reporting_crossregion_fires;
CREATE TABLE reporting_crossregion_fires AS SELECT DISTINCT bf.id FROM reporting_bushfire bf JOIN bfrs_region r ON ST_Overlaps(bf.fire_boundary, r.geometry);
DROP INDEX IF EXISTS idx_reporting_crossregion_fires;
CREATE INDEX idx_reporting_crossregion_fires ON reporting_crossregion_fires(id);
---------------------------------------    
--UCL/Other Crown/Private Property 13 min
---------------------------------------
--insert recalculated 'other crown' / UCL / Freehold 
--Other Crown 5min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 19, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'Other Crown Land' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
    
--UCL 5min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 25, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'UCL' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
    
--Freehold 15s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 18, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'Freehold' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
--UPDATE tenure_id FOR IGNITION POINTS IN UCL, FREEHOLD AND OTHER CROWN
UPDATE reporting_bushfire bf SET tenure_id = 19 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'Other Crown Land');
UPDATE reporting_bushfire bf SET tenure_id = 18 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'Freehold');
UPDATE reporting_bushfire bf SET tenure_id = 25 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'UCL');
-------------------------------------------
--DEPT LAND
---------------------------------------------
--INTEREST 20s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, di.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_dept_interest di ON ST_Intersects(bf.fire_boundary, di.geometry) JOIN bfrs_tenure t ON di.category = t.name
    WHERE bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
--MANAGED 3min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, dm.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_dept_managed dm ON ST_Intersects(bf.fire_boundary, dm.geometry) JOIN bfrs_tenure t ON dm.category = t.name
    WHERE dm.category <> 'State Forest' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
--UPDATE tenure_id FOR OLD 'Other' TENURE IN DEPT-MANAGED LAND
UPDATE reporting_bushfire
SET tenure_id = t_id
FROM (SELECT bf.id AS bf_id, t.id AS t_id FROM reporting_bushfire bf, reporting_dept_managed dm 
JOIN bfrs_tenure t ON dm.category = t.name
WHERE tenure_id = 20
AND st_within(bf.origin_point, dm.geometry)) AS sqry
WHERE id = bf_id;
--------------------------------------------------
--STATE FOREST 20s
--------------------------------------------------
--Hardwood 4s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, sf.shape), 900914))/10000)::numeric,2), bf.id, 26, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape)
    WHERE fbr_fire_report_classification = 'Native Hardwood' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
--Softwood 1s    
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, sf.shape), 900914))/10000)::numeric,2), bf.id, 27, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape)
    WHERE fbr_fire_report_classification = 'State - Coniferous' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
--where NOT has_fire_boundary
UPDATE reporting_areaburnt
SET tenure_id = 27 WHERE id IN
(SELECT ab.id
FROM reporting_areaburnt ab JOIN reporting_bushfire bf ON ab.bushfire_id = bf.id 
JOIN reporting_state_forest sf ON ST_Within(bf.origin_point, sf.shape)
WHERE ab.tenure_id = 3 AND NOT has_fire_boundary AND sf.fbr_fire_report_classification = 'State - Coniferous');
--remaining '3's should be 26
UPDATE reporting_areaburnt
SET tenure_id = 26 WHERE id IN
(SELECT ab.id
FROM reporting_areaburnt ab JOIN reporting_bushfire bf ON ab.bushfire_id = bf.id 
JOIN reporting_state_forest sf ON ST_Within(bf.origin_point, sf.shape)
WHERE ab.tenure_id = 3 AND NOT has_fire_boundary AND sf.fbr_fire_report_classification = 'Native Hardwood');
DELETE FROM reporting_areaburnt WHERE tenure_id = 3;
--UPDATE STATE FOREST IGNITION POINTS
UPDATE reporting_bushfire bf SET tenure_id = 26 WHERE bf.tenure_id = 3 AND bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_state_forest sf WHERE ST_Within(bf.origin_point, sf.shape) AND sf.fbr_fire_report_classification = 'Native Hardwood');
UPDATE reporting_bushfire bf SET tenure_id = 27 WHERE bf.tenure_id = 3 AND bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_state_forest sf WHERE ST_Within(bf.origin_point, sf.shape) AND sf.fbr_fire_report_classification = 'State - Coniferous');
---------------------------------------
--ADD IN INFO FOR REGION-CROSSING FIRES 20min in total
---------------------------------------
--SA/NT: insert into reporting_areaburnt the SA/NT components of trans-state fires (this is done USING r.name = t.name) 1 min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, r.geometry), 900914))/10000)::numeric,2),
bf.id, t.id, r.id, True
FROM reporting_bushfire bf JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON r.name = t.name;
    
--insert into reporting_areaburnt the Prvt Prpty / UCL / Other Crown Land components of trans-region fires (13 min)
--Other Crown Land
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 19, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'Other Crown Land' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) AND r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--UCL 3 min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 25, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'UCL' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) AND r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--Private Property (Freehold)   30s OK
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 18, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'Freehold' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--State Forest (Hardwood) (4s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 26, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, sf.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE fbr_fire_report_classification = 'Native Hardwood' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;
--State Forest (Softwood) (4s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 27, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, sf.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE fbr_fire_report_classification = 'State - Coniferous' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--insert into reporting_areaburnt the Interest Tenure components of trans-region fires (8s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, di.geometry), r.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, r.id
    FROM reporting_bushfire bf JOIN reporting_dept_interest di ON ST_Intersects(bf.fire_boundary, di.geometry) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON di.category = t.name
    WHERE bf.id IN (SELECT id FROM reporting_crossregion_fires);
--insert into reporting_areaburnt the Managed Tenure components of trans-region fires (1:19)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, dm.geometry), r.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, r.id
    FROM reporting_bushfire bf JOIN reporting_dept_managed dm ON ST_Intersects(bf.fire_boundary, dm.geometry) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON dm.category = t.name
    WHERE dm.category <> 'State Forest'  AND bf.id IN (SELECT id FROM reporting_crossregion_fires);
    """)
    print ("finished calculate report tables")
        
