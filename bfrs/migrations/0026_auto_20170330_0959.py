# -*- coding: utf-8 -*-
# Generated by Django 1.10.2 on 2017-03-30 01:59
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('bfrs', '0025_auto_20170328_1414'),
    ]

    operations = [
        migrations.AddField(
            model_name='linkedbushfire',
            name='creator',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='bfrs_linkedbushfire_created', to=settings.AUTH_USER_MODEL),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='linkedbushfire',
            name='linked_fire_number',
            field=models.CharField(default=1, max_length=15, verbose_name=b'Linked fire Number'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='linkedbushfire',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='linkedbushfire',
            name='modifier',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.CASCADE, related_name='bfrs_linkedbushfire_modified', to=settings.AUTH_USER_MODEL),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='linkedbushfire',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, editable=False),
        ),
    ]