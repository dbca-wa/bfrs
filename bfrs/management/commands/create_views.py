from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.sql_views import create_view, create_final_view, create_fireboundary_view, drop_view, drop_final_view, drop_fireboundary_view

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Drops and re-creates sql views \n \
\n \
        usage: ./manage.py create_views \n \
    '

    def handle(self, *args, **options):
        drop_view()
        drop_final_view()
        drop_fireboundary_view()
        create_view()
        create_final_view()
        create_fireboundary_view()
        self.stdout.write('Done')

