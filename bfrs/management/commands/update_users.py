from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from django.conf import settings
from bfrs.utils import update_users

import os
import sys

import logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Updates the Django DB with users from Windows Active Directory \n \
\n \
        usage: ./manage.py update_users \n \
    '

    def handle(self, *args, **options):
        update_users()
        self.stdout.write('Done')

