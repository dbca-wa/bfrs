"""BFRS Management Command."""


# Third-Party
import logging
from django.core.management import base
# Local
from bfrs.cadastre_layer_sync import ReportingCadastreExtractGeojson
from cadastre_table_update import CadastreTableUpdate
from django.conf import settings
logger = logging.getLogger(__name__)


class Command(base.BaseCommand):
    help = "Updates the cadastre table."

    def handle(self, *args, **kwargs) -> None:
        """Handles the management command functionality."""
        self.stdout.write("Running complete_reporting_cadastre_update")
        ReportingCadastreExtractGeojson(settings=settings).run_sync()
        CadastreTableUpdate(settings=settings, clean_up=True).run_sync()

        
        

