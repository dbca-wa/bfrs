from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.harvest import cron

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Scans the Inbox for emails from DFES for dfes_incident_no and inserts into the bushfire records \n \
\n \
        usage:   ./manage.py dfes_harvest \n \
        To Test: respond to the DFES Notification Email with test `Incident: MyNum 12345` \n \
    '

    def handle(self, *args, **options):
        cron()
        self.stdout.write('Done')

