"""BFRS Management Command."""

# Third-Party
import logging
from django.core.management import base
# Local
from legislated_tenure_update.legislated_tenure_layer_sync import ReportingLegislatedTenureExtractGeojson
from legislated_tenure_update.legislated_tenure_table_update import LegislatedTenureTableUpdate
from django.conf import settings
logger = logging.getLogger(__name__)


class Command(base.BaseCommand):
    help = "Updates the legislated tenure table."

    def handle(self, *args, **kwargs) -> None:
        """Handles the management command functionality."""
        self.stdout.write("Running complete_reporting_legislated_tenure")
        ReportingLegislatedTenureExtractGeojson(settings=settings).run_sync()
        LegislatedTenureTableUpdate(settings=settings, clean_up=True).run_sync()
