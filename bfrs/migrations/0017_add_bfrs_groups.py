from __future__ import unicode_literals

from django.db import migrations

from bfrs import utils

def addGroups(from_state_apps, schema_editor):
    utils._add_users_to_fssdrs_group()
    utils._add_users_to_final_authorise_group()

class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0016_auto_20180914_1010'),
    ]

    operations = [
        migrations.RunPython(
            addGroups
        ),
    ]

