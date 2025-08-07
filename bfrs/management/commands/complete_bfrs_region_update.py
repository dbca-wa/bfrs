"""BFRS Management Command."""

# Third-Party
import logging
from django.core.management import base
# Local
from bfrs_region_update.bfrs_region_layer_sync import ReportingBurnRegionTenureExtractGeojson
from bfrs_region_update.bfrs_region_table_update import BurnRegionTableUpdate
from django.conf import settings
logger = logging.getLogger(__name__)


class Command(base.BaseCommand):
    help = "Updates the legislated tenure table."

    def handle(self, *args, **kwargs) -> None:
        """Handles the management command functionality."""
        self.stdout.write("Running complete_reporting_legislated_tenure")
        ReportingBurnRegionTenureExtractGeojson(settings=settings).run_sync()
        BurnRegionTableUpdate(settings=settings, clean_up=True).run_sync()
