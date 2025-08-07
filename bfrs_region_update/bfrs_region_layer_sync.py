# Third-Party
import os
import logging
from math import ceil
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path
from argparse import Namespace
from datetime import datetime


# Local
from geojsplit import cli as geojsplit_cli

logger = logging.getLogger(__name__)


class ReportingBurnRegionTenureExtractGeojson:

    def __init__(self, settings):
        self.auth_user = settings.KB_AUTH_USER
        self.auth_pass = settings.KB_AUTH_PASS
        self.KB_LAYER_URL = settings.KB_BFRS_REGION_LAYER_URL
        self.geojson_split_geometry_count = settings.GEOJSON_SPLIT_GEOMETRY_COUNT
        self.download_dir = settings.LAYER_DOWNLOAD_DIR+"/bfrs_region/"
        self.max_geojson_split_size = settings.MAX_GEOJSPLIT_SIZE

    def run_sync(self):

        current_datetime = datetime.now().astimezone()
        seen_datetime = datetime.strftime(current_datetime, "%Y-%m-%d %H:%M:%S")
        logger.info(f"Syncing Burn Region enure KB Layer for BFRS {seen_datetime}")
        try:
            layers = [self.KB_LAYER_URL]
            print (layers)
            logger.info(f"Layers to be processed: {len(layers)}")
            for layer_url in layers:
                layer_filename, error = self.download_layer(
                    layer_url, (self.auth_user, self.auth_pass), stream=True
                )
                if error:
                    logger.error(f"Error downloading layer {layer_url}: {error}")
                    continue
                self.split_geojson_file(
                    layer_filename, geometry_count=self.geojson_split_geometry_count
                )
        except Exception as e:
            logger.error(e)

    def download_layer(self, url: str, auth: tuple = None, stream: bool = False):
        authentication = HTTPBasicAuth(auth[0], auth[1]) if auth else None
        print (self.download_dir)
        try:
            if not Path(self.download_dir).exists():
                Path(self.download_dir).mkdir(parents=True, exist_ok=True)
            else:
                for file in Path(self.download_dir).glob("*.geojson"):
                    file.unlink()

            with requests.get(url, auth=authentication, stream=stream) as r:
                r.raise_for_status()
                filename = f"{self.download_dir}/burnregion_layer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.geojson"
                with open(filename, "wb") as f:
                    f.write(r.content)

                logger.info(f"Layer downloaded and saved as {filename}")
            return filename, None
        except Exception as e:
            return None, f"Error downloading layer: {str(e)}"

    def split_geojson_file(
        self, filename, file_prefix=None, round=0, geometry_count=2000
    ):
        """
        Splits a GeoJSON file into smaller files with a specified number of geometries.
        If the resulting file is larger than the max size, it will recursively split it further.
        """
        if round > 30 or geometry_count <= 1:
            logger.info(
                f"Max split rounds reached for file {filename}. Skipping further splits."
            )
            return
        try:
            file_path = Path(filename)
            args = Namespace(
                geojson=file_path,
                geometry_count=geometry_count,
                suffix_length=None,
                output=None,
                limit=None,
                verbose=False,
                dry_run=False,
            )
            logger.info(
                f"Splitting GeoJSON file {file_path} into smaller files with {geometry_count} geometries each."
            )
            geojsplit_cli.input_geojson(args=args)
            logger.info(f"GeoJSON file {file_path} split successfully.")
            try:
                file_path.unlink()
                logger.info(f"Removed original file {file_path}")
            except Exception as e:
                logger.error(f"Error removing original file {file_path}: {str(e)}")
                raise Exception(f"Error removing original file {file_path}: {str(e)}")

            # directory
            output_dir = file_path.parent
            for file in output_dir.glob(
                "*.geojson" if file_prefix is None else f"{file_prefix}*.geojson"
            ):
                file_size = file.stat().st_size
                file_size_str = (
                    f"{file_size / (1024 * 1024):.2f} MB"
                    if file_size > 1024 * 1024
                    else f"{file_size / 1024:.2f} KB"
                )
                logger.info(f"Created split file: {file.name} ({file_size_str})")
                # rename
                if (
                    self.max_geojson_split_size
                    and file_size > self.max_geojson_split_size
                ):
                    suffix = file.suffix
                    new_name = f"split_round_{round}_size_{geometry_count}_{file.stem.split('_')[-1]}"
                    new_full_name = f"{new_name}{suffix}"
                    logger.info(f"Renaming file {file.name} to {new_full_name}")
                    os.rename(file, output_dir / f"{new_full_name}")

                    geometry_count = ceil(geometry_count / 4)
                    self.split_geojson_file(
                        output_dir / new_full_name,
                        new_name,
                        round=round + 1,
                        geometry_count=geometry_count,
                    )
                else:
                    file_rename = file.with_name(
                        f"{file.stem}_round_{round}_size_{file_size_str}.geojson"
                    )
                    file.rename(file_rename)
        except Exception as e:
            err_msg = f"Error splitting geojson to smaller files\n{str(e)}"
            logger.error(err_msg)


def main():
    settings = {
        "KB_AUTH_USER": os.environ.get("KB_AUTH_USER", None),
        "KB_AUTH_PASS": os.environ.get("KB_AUTH_PASS", None),
        "KB_LAYER_URL": os.environ.get("KB_BURN_REGION_LAYER_URL", None),
        "GEOJSON_SPLIT_GEOMETRY_COUNT": int(
            os.environ.get("GEOJSON_SPLIT_GEOMETRY_COUNT", 5000)
        ),
        "LAYER_DOWNLOAD_DIR": str(
            os.environ.get("LAYER_DOWNLOAD_DIR", "./geojson_dir")
        ),
        "MAX_GEOJSPLIT_SIZE": int(
            os.environ.get("MAX_GEOJSPLIT_SIZE", 50 * 1024 * 1024)
        ),  # 50 MB
    }

    settings = Namespace(**settings)  # Convert dict to Namespace for compatibility
    ReportingBurnRegionTenureExtractGeojson(
        settings=settings,
    ).run_sync()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
