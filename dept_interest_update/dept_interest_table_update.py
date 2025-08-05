# Third-Party
from argparse import Namespace
import os
import logging
import json
from datetime import datetime

# Local
from django.db import connection
from django.contrib.gis.geos import GEOSGeometry

logger = logging.getLogger(__name__)


class DeptInterestTableUpdate:
    """Class to handle reporting_dept_interest table updates."""

    def __init__(self, settings, clean_up=False):
        self.geojson_dir = settings.LAYER_DOWNLOAD_DIR+"/dept_interest/"
        self.table_name = "reporting_dept_interest"
        self.clean_up = clean_up

    def run_sync(self):
        """Run the reporting_dept_interest table update."""
        if not os.path.exists(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " does not exist.")
            return
        if not os.listdir(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " is empty.")
            return

        success_populate = False
        success_tables_script = self.run_tables_script()

        if not success_tables_script:
            logger.error("Failed to update reporting_dept_interest table. Script execution failed.")
            return
        else:
            logger.info("reporting_dept_interest table updated successfully.")
            success_populate = self.populate_from_directory()

        if not success_populate:
            logger.error("Failed to populate reporting_dept_interest table from directory.")
            return
        else:
            logger.info("reporting_dept_interest table populated successfully from directory.")

        if self.clean_up:
            self.clean_up_directory()

    def run_tables_script(self):
        success = False
        current_datetime = datetime.now()
        seen_datetime = datetime.strftime(current_datetime, "%Y-%m-%d %H:%M:%S")
        db_suffix = datetime.strftime(current_datetime, "%Y_%m_%d__%H_%M_%S")
        logger.info("Running reporting reporting_dept_interest table update " + seen_datetime)
        csr = connection.cursor()
        try:
            table_name = self.table_name
            new_table_name = "{}_{}".format(
                table_name, datetime.strftime(current_datetime, "%Y_%m_%d__%H_%M_%S")
            )

            csr.execute(
                "ALTER TABLE {} RENAME TO {};".format(table_name, new_table_name)
            )
            logger.info("Renamed table " + table_name + " to " + new_table_name)

            csr.execute(
                """CREATE TABLE public.reporting_dept_interest (
                    ogc_fid integer NOT NULL,
                    loi_pin double precision,
                    loi_poly_area double precision,
                    loi_identifier character varying(64),
                    loi_regno character varying(50),
                    loi_tenure character varying(254),
                    loi_act character varying(254),
                    category character varying(40),
                    loi_notes character varying(254),
                    loi_prprietor character varying(120),
                    shape_length double precision,
                    shape_area double precision,
                    geometry public.geometry(MultiPolygon,4326)
                );"""
            )
            
            csr.execute("CREATE SEQUENCE public.reporting_dept_interest_ogc_fid_seq_"+db_suffix+" AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;")
            
            csr.execute("ALTER TABLE ONLY public.reporting_dept_interest ALTER COLUMN ogc_fid SET DEFAULT nextval('public.reporting_dept_interest_ogc_fid_seq_"+db_suffix+"'::regclass);")
                         
            csr.execute("ALTER TABLE ONLY public.reporting_dept_interest ADD CONSTRAINT reporting_dept_interest_pkey_"+db_suffix+" PRIMARY KEY (ogc_fid);")
                                
            csr.execute("CREATE INDEX idx_reporting_dept_interest_category_"+db_suffix+" ON public.reporting_dept_interest USING btree (category);")
                        
            
            csr.execute("CREATE INDEX reporting_dept_interest_geometry_geom_idx_"+db_suffix+" ON public.reporting_dept_interest USING gist (geometry);")                        



            logger.info(
                "Created new table {} with structure from {}".format(
                    table_name, new_table_name
                )
            )

            connection.commit()
            logger.info("Reporting_Legislated table created from schema.")
            success = True
        except Exception as e:
            logger.error("Error creating Reporting_Legislated table: {}".format(e))
            connection.rollback()
        finally:
            csr.close()

        return success

    def populate_from_directory(self):
        """Populate the Reporting_Legislated table from GeoJSON files in a directory."""
        success = False
        try:
            directory = self.geojson_dir
            logger.info(
                "Populating {} from directory {}".format(self.table_name, directory)
            )
            for filename in os.listdir(directory):
                if filename.endswith(".geojson"):
                    geojson_file = os.path.join(directory, filename)
                    self.populate_from_geojson_file(geojson_file)
            success = True
        except Exception as e:
            logger.error("Error populating Reporting_Legislated table from directory: {}".format(e))

        return success

    def populate_from_geojson_file(self, geojson_file):
        """Populate the Reporting_Legislated table from a GeoJSON file."""
        geojson_data = None
        csr = connection.cursor()
        counter = 0
        try:
            with open(geojson_file, "r") as file:
                geojson_data = json.load(file)
            if "features" not in geojson_data:
                logger.error("Invalid GeoJSON file: {}".format(geojson_file))
                return False
            for feature in geojson_data["features"]:
                properties = feature["properties"]
                geometry = feature["geometry"]
                loi_pin = properties.get("LOI_PIN", None)
                loi_poly_area = properties.get("LOI_POLY_AREA", None)                
                loi_identifier = properties.get("LOI_IDENTIFIER", None)
                loi_regno = properties.get("LOI_REGNO", None)
                loi_tenure = properties.get("LOI_TENURE", None)
                loi_act = properties.get("LOI_ACT", None)
                leg_cat = properties.get("LOI_CATEGORY", None)
                loi_notes = properties.get("LOI_NOTES", None)
                loi_prprietor = properties.get("LOI_PRPRIETOR", None)            
                shape_length = properties.get("SHAPE_Length", None)
                shape_area = properties.get("SHAPE_Area", None)                
                pnt = GEOSGeometry(json.dumps(geometry), srid=4326)

                csr.execute(
                    """
                    INSERT INTO {} (loi_pin, loi_poly_area, loi_identifier, loi_regno, loi_tenure,loi_act, category, loi_notes, loi_prprietor, shape_length, shape_area, geometry)
                    VALUES (%s, %s, %s, %s,%s, %s, %s, %s,%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                """.format(
                        self.table_name
                    ),
                    (
                        loi_pin,
                        loi_poly_area,
                        loi_identifier,
                        loi_regno,
                        loi_tenure,
                        loi_act,
                        leg_cat,
                        loi_notes,
                        loi_prprietor,
                        shape_length,
                        shape_area,
                        pnt.json,
                    ),
                )

                counter += 1
            connection.commit()
            logger.info(
                "Successfully populated {} with {} records from {}".format(
                    self.table_name, counter, geojson_file
                )
            )
        except Exception as e:
            logger.error(
                "Error populating reporting_dept_interest table from GeoJSON file {}: {}".format(
                    geojson_file, e
                )
            )
            connection.rollback()
        finally:
            csr.close()

        return True

    def clean_up_directory(self):
        """Clean up the GeoJSON directory by removing processed files."""
        try:
            logger.info("Cleaning up directory: {}".format(self.geojson_dir))
            for filename in os.listdir(self.geojson_dir):
                file_path = os.path.join(self.geojson_dir, filename)
                os.remove(file_path)
        except Exception as e:
            logger.error("Error cleaning up directory: {}".format(e))
        logger.info("Directory cleaned up successfully.")


def main():
    import django
    from django.conf import settings as django_settings
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    # Initialize Django settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bfrs_project.settings")
    django.setup()
    
    if not django_settings.configured:
        raise RuntimeError("Django settings are not configured.")

    settings = {
        "LAYER_DOWNLOAD_DIR": str(
            os.environ.get("LAYER_DOWNLOAD_DIR", "./geojson_dir")
        ),
    }
    settings = Namespace(**settings)  # Convert dict to Namespace for compatibility
    LegislatedTenureTableUpdate(
        settings=settings,
        clean_up=True,
    ).run_sync()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
