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
    elif isinstance(bushfire,str):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    foldername,pdf_filename = utils.generate_pdf("latex/fire_bombing_request_form.tex",context={"bushfire":bushfire,"graphic_folder":settings.LATEX_GRAPHIC_FOLDER})

    print("pdf_filename = {}".format(pdf_filename))

def test_send_fire_bomging_req_email(bushfire=None,user_email=None):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,str):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    utils.send_fire_bomging_req_email({
        "bushfire":bushfire, 
        "user_email":user_email,
        "request":None,
    })



