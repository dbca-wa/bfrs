# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-07-13 08:02
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0014_auto_20170713_1510'),
    ]

    operations = [
        migrations.CreateModel(
            name='DamageSnapshot',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
        ),
        migrations.RemoveField(
            model_name='bushfiresnapshot',
            name='json_data',
        ),
        migrations.AddField(
            model_name='damagesnapshot',
            name='snapshot',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='damage_snapshots', to='bfrs.BushfireSnapshot'),
        ),
    ]