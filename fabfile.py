#!/usr/bin/env python
"""
Module: fabfile.py
Package: Bushfire Reporting System
Description: Automate some tasks.

"""
from __future__ import print_function
### Imports
from datetime import datetime
import os, sys
import os.path as osp
from fabric.api import *


### Functions
@task
def email_outstanding_fires():
    """ Emails the Outstanding Fires report to the RDO recipients """

#honcho run python manage.py backtest_db Scenario-LOB_1 Backtest_1 2013-01-13 2013-01-16
#python manage.py backtest_db Scenario-LOB_1 Backtest_1 2013-01-13 2013-02-01
    cmds = """\
python manage.py email_outstanding_fires
    """.split("\n")
    with settings(warn_only=True):
        map(local, cmds)


