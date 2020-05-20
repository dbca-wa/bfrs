from __future__ import unicode_literals

from django.db import migrations
from django.conf import settings
from django.contrib.auth.models import Permission,Group

from bfrs import utils

def addGroups(from_state_apps, schema_editor):
    utils._add_users_to_fssdrs_group()
    utils._add_users_to_final_authorise_group()

    #add 'final_authorise_bushfire' permission if it is not added
    permission= Permission.objects.get(codename='final_authorise_bushfire')
    for name in (settings.FSSDRS_GROUP,settings.FINAL_AUTHORISE_GROUP):
        group = Group.objects.get(name=name)
        if not group.permissions.filter(codename=permission.codename).exists():
            group.permissions.add(permission)

class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0016_auto_20180914_1010'),
    ]

    operations = [
        migrations.RunPython(
            addGroups
        ),
    ]

