from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

import logging

from django.db.models.functions import Length

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update @ sign with . in User.username field \n \
    \n \
            usage: ./manage.py update_at_sign_with_dot_in_user \n \
        '

    def handle(self, *args, **options):
        #self.copy_email_to_username()
        self.correct_username()
        # self.replace_at_by_dot()

    # def replace_at_by_dot(self):
    #     users_with_at = User.objects.filter(username__contains='@')
    #     for user in users_with_at:
    #         user.username = user.username.replace('@', '.')
    #         user.save()

    def copy_email_to_username(self):
        users = User.objects.all()
        for user in users:
            user.username = user.email
            user.save()

    def correct_username(self):
        users = User.objects.all()
        for user in users:
            username_split_at = user.email.split('@')  # username_split_at[0]: email_address_before_at, username_split_at[1]: dbca.wa.gov.au
            if len(username_split_at) == 2:
                try:
                    domain_split_dot = username_split_at[1].split('.')  # domain_split_dot[0]: dbca,  domain_split_dot[1]:wa.gov.au
                    full_username = username_split_at[0] + '.' + domain_split_dot[0]
                    user.username = full_username[0:30]  # Take first 30 characters
                    print (user.username)
                    user.save()
                except Exception as e:
                    print (e)
                    
                    
