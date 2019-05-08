# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2019-03-19 00:37
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0017_add_final_authorise_group_and_permission'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenureMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name=b'Tenure sub category')),
                ('tenure', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bfrs.Tenure')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]