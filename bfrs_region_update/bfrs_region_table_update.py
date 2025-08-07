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


class BurnRegionTableUpdate:
    """Class to handle bfrs_region table updates."""

    def __init__(self, settings, clean_up=False):
        self.geojson_dir = settings.LAYER_DOWNLOAD_DIR+"/bfrs_region/"
        self.table_name = "bfrs_region"
        self.clean_up = clean_up

    def run_sync(self):
        """Run the bfrs_region table update."""
        if not os.path.exists(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " does not exist.")
            return
        if not os.listdir(self.geojson_dir):
            logger.error("Directory " + self.geojson_dir + " is empty.")
            return

        success_populate = False
        success_tables_script = self.run_tables_script()

        if not success_tables_script:
            logger.error("Failed to update bfrs_region table. Script execution failed.")
            return
        else:
            logger.info("bfrs_region table updated successfully.")
            success_populate = self.populate_from_directory()

        if not success_populate:
            logger.error("Failed to populate bfrs_region table from directory.")
            return
        else:
            logger.info("bfrs_region table populated successfully from directory.")

        if self.clean_up:
            self.clean_up_directory()

    def run_tables_script(self):
        success = False
        current_datetime = datetime.now()
        seen_datetime = datetime.strftime(current_datetime, "%Y-%m-%d %H:%M:%S")
        db_suffix = datetime.strftime(current_datetime, "%Y_%m_%d__%H_%M_%S")
        logger.info("Running reporting bfrs_region table update " + seen_datetime)
        csr = connection.cursor()
        try:
            table_name = self.table_name
            new_table_name = "{}_{}".format(
                table_name, datetime.strftime(current_datetime, "%Y_%m_%d__%H_%M_%S")
            )

            csr.execute(
                "CREATE TABLE {} AS SELECT * FROM {};".format(new_table_name, table_name)
            )
            logger.info("Create copy of table " + table_name + " to " + new_table_name)

            # csr.execute("DELETE FROM {};".format(table_name));
                        
            # logger.info(
            #     "Deleted rows in table {} with structure from {}".format(
            #         table_name, new_table_name
            #     )
            # )

            connection.commit()
            logger.info("bfrs_region table created from schema.")
            success = True
        except Exception as e:
            logger.error("Error creating bfrs_region table: {}".format(e))
            connection.rollback()
        finally:
            csr.close()

        return success

    def populate_from_directory(self):
        """Populate the bfrs_region table from GeoJSON files in a directory."""
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
            logger.error("Error populating bfrs_region table from directory: {}".format(e))

        return success

    def populate_from_geojson_file(self, geojson_file):
        """Populate the bfrs_region table from a GeoJSON file."""
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
                id = properties.get("id", None)
                name = properties.get("name", None)
                forest_region = properties.get("forest_region", None)            
                dbca = properties.get("dbca", None)                              
                pnt = GEOSGeometry(json.dumps(geometry), srid=4326)


                csr.execute("select count(*) as row_found from {} WHERE id = {}".format(self.table_name, id))
                rows = csr.fetchone()
                if rows[0] > 0:
                    print("Update Record {}".format(id))
                    csr.execute(
                        """
                        UPDATE {} set name = %s , forest_region = %s, dbca = %s, geometry = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) WHERE id = %s;
            
                    """.format(
                            self.table_name
                        ),
                        (                            
                            name,
                            forest_region,
                            dbca,
                            pnt.json,
                            id
                        ),
                    )
                else:
                    print("Creating Record {}".format(id))
                    csr.execute(
                        """
                        INSERT INTO {} (id, name, forest_region, dbca, geometry)
                        VALUES (%s, %s, %s,%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                    """.format(
                            self.table_name
                        ),
                        (
                            id,
                            name,
                            forest_region,
                            dbca,
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
                "Error populating bfrs_region table from GeoJSON file {}: {}".format(
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
    BurnRegionTableUpdate(
        settings=settings,
        clean_up=True,
    ).run_sync()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
