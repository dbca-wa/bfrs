import tempfile
import os
import shutil
import subprocess

from django.test import TestCase
from django.template.loader import render_to_string
from django.conf import settings

from bfrs.models import Bushfire
from bfrs import utils

# Create your tests here.

def test_fire_bombing(bushfire=None):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,basestring):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    foldername,pdf_filename = utils.generate_pdf("latex/fire_bombing_request_form.tex",context={"bushfire":bushfire,"graphic_folder":settings.LATEX_GRAPHIC_FOLDER})

    print("pdf_filename = {}".format(pdf_filename))


