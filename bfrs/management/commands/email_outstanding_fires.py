from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.reports import email_outstanding_fires

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Emails the Outstanding Fires iReport to the RDOs \n \
\n \
        usage: ./manage.py email_outstanding_fires \n \
    '

    def handle(self, *args, **options):
        email_outstanding_fires()
        self.stdout.write('Done')

