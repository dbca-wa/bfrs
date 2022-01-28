from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update @ sign with . in User.username field \n \
    \n \
            usage: ./manage.py update_at_sign_with_dot_in_user \n \
        '

    def handle(self, *args, **options):
        self.copy_email_to_username()
        self.replace_at_by_dot()

    def replace_at_by_dot(self):
        users_with_at = User.objects.filter(username__contains='@')
        for user in users_with_at:
            user.username = user.username.replace('@', '.')
            user.save()

    def copy_email_to_username(self):
        users = User.objects.all()
        for user in users:
            user.username = user.email
            user.save()

