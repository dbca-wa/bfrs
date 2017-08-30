from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.sql_views import drop_view, drop_final_view, drop_fireboundary_view

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Drops sql views \n \
\n \
        usage: ./manage.py drop_views \n \
    '

    def handle(self, *args, **options):
        drop_view()
        drop_final_view()
        drop_fireboundary_view()
        self.stdout.write('Done')

