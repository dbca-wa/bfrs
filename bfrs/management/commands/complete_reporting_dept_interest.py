"""BFRS Management Command."""

# Third-Party
import logging
from django.core.management import base
# Local
from dept_interest_update.dept_interest_layer_sync import ReportingDeptInterestExtractGeojson
from dept_interest_update.dept_interest_table_update import DeptInterestTableUpdate
from django.conf import settings
logger = logging.getLogger(__name__)


class Command(base.BaseCommand):
    help = "Updates the legislated tenure table."

    def handle(self, *args, **kwargs) -> None:
        """Handles the management command functionality."""
        self.stdout.write("Running complete_reporting_legislated_tenure")
        ReportingDeptInterestExtractGeojson(settings=settings).run_sync()
        DeptInterestTableUpdate(settings=settings, clean_up=True).run_sync()
