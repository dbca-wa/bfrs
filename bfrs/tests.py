from django.test import TestCase
from django.template.loader import render_to_string
from django.conf import settings

from bfrs.models import Bushfire

# Create your tests here.

def test_fire_bombing(bushfire=None):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,basestring):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    tex_file = render_to_string("latex/fire_bombing_request_form.tex",context={"bushfire":bushfire,"graphic_folder":settings.LATEX_GRAPHIC_FOLDER})
    tex_file = tex_file.encode('utf-8')
    with open("/home/rockyc/Downloads/fire_bombing_request_form.tex","wb") as f:
        f.write(tex_file)


