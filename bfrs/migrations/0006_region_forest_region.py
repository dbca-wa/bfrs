# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-09-22 03:54
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0005_auto_20170919_1340'),
    ]

    operations = [
        migrations.AddField(
            model_name='region',
            name='forest_region',
            field=models.BooleanField(default=False),
        ),
    ]