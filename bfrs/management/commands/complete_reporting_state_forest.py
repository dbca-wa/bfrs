"""BFRS Management Command."""

# Third-Party
import logging
from django.core.management import base
# Local
from state_forest_update.state_forest_layer_sync import ReportingStateForestTenureExtractGeojson
from state_forest_update.state_forest_table_update import StateForestTenureTableUpdate
from django.conf import settings
logger = logging.getLogger(__name__)


class Command(base.BaseCommand):
    help = "Updates the legislated tenure table."

    def handle(self, *args, **kwargs) -> None:
        """Handles the management command functionality."""
        self.stdout.write("Running complete_reporting_legislated_tenure")
        ReportingStateForestTenureExtractGeojson(settings=settings).run_sync()
        StateForestTenureTableUpdate(settings=settings, clean_up=True).run_sync()
