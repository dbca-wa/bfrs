from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.sql_views import create_all_views

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Creates sql views \n \
\n \
        usage: ./manage.py create_views \n \
    '

    def handle(self, *args, **options):
        create_all_views()
        self.stdout.write('Done')

