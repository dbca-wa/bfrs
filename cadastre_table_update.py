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


class CadastreTableUpdate:
    """Class to handle cadastre table updates."""

    def __init__(self, settings):
        self.geojson_dir = settings.LAYER_DOWNLOAD_DIR
        self.table_name = "reporting_cadastre"
        self.clean_up = settings.clean_up if hasattr(settings, "clean_up") else False

    def run_sync(self):
        """Run the cadastre table update."""
        if not os.path.exists(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " does not exist.")
            return
        if not os.listdir(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " is empty.")
            return

        success_populate = False
        success_tables_script = self.run_tables_script()

        if not success_tables_script:
            logger.error("Failed to update cadastre table. Script execution failed.")
            return
        else:
            logger.info("Cadastre table updated successfully.")
            success_populate = self.populate_from_directory()

        if not success_populate:
            logger.error("Failed to populate cadastre table from directory.")
            return
        else:
            logger.info("Cadastre table populated successfully from directory.")

        if self.clean_up:
            self.clean_up_directory()

    def run_tables_script(self):
        success = False
        current_datetime = datetime.now()
        seen_datetime = datetime.strftime(current_datetime, "%Y-%m-%d %H:%M:%S")
        logger.info("Running reporting cadastre table update " + seen_datetime)
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
                """CREATE TABLE public.reporting_cadastre (
                            objectid integer NOT NULL,
                            brc_cad_legend character varying(50),
                            brc_fms_legend character varying(50),
                            shape_length double precision,
                            shape_area double precision,
                            shape public.geometry(MultiPolygon,4326)
                        );"""
            )
            csr.execute(
                "ALTER TABLE ONLY public.reporting_cadastre ALTER COLUMN objectid SET DEFAULT nextval('public.reporting_cadastre_objectid_seq2'::regclass);"
            )
            logger.info(
                "Created new table {} with structure from {}".format(
                    table_name, new_table_name
                )
            )

            connection.commit()
            logger.info("Reporting_Cadastre table created from schema.")
            success = True
        except Exception as e:
            logger.error("Error creating Reporting_Cadastre table: {}".format(e))
            connection.rollback()
        finally:
            csr.close()

        return success

    def populate_from_directory(self):
        """Populate the cadastre table from GeoJSON files in a directory."""
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
            logger.error("Error populating cadastre table from directory: {}".format(e))

        return success

    def populate_from_geojson_file(self, geojson_file):
        """Populate the cadastre table from a GeoJSON file."""
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
                brc_fms_legend = properties.get("BRC_FMS_Legend", None)
                brc_cad_legend = properties.get("BRC_CAD_LEGEND", None)
                shape_lenght = properties.get("SHAPE_Length", None)
                shape_area = properties.get("SHAPE_Area", None)

                pnt = GEOSGeometry(json.dumps(geometry), srid=4326)
                csr.execute(
                    """
                    INSERT INTO {} (brc_cad_legend, brc_fms_legend, shape_length, shape_area, shape)
                    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                """.format(
                        self.table_name
                    ),
                    (
                        brc_cad_legend,
                        brc_fms_legend,
                        shape_lenght,
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
                "Error populating cadastre table from GeoJSON file {}: {}".format(
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
    # Initialize Django settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bfrs_project.settings")
    django.setup()
    # Ensure the settings are loaded
    if not django_settings.configured:
        raise RuntimeError("Django settings are not configured.")
    settings = {
        "LAYER_DOWNLOAD_DIR": str(
            os.environ.get("LAYER_DOWNLOAD_DIR", "./geojson_dir")
        ),
    }
    settings = Namespace(**settings)  # Convert dict to Namespace for compatibility
    CadastreTableUpdate(
        settings=settings,
        clean_up=True,
    ).run_sync()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
