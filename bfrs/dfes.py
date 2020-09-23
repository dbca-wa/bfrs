import requests
import traceback
import HTMLParser

from requests_ntlm import HttpNtlmAuth

from django.conf import settings
from django.core.urlresolvers import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape

from .models import Bushfire


class P1CAD(object):
    create_incident_template = "bfrs/dfes/create_incident.xml"
    @classmethod
    def create_incident(cls,bushfire,request=None):
        """
        Create a dfes incident no for bushfire report.
        bushfire can be a bushfire report object or report id or fire number
        """
        if not request:
            build_absolute_uri = lambda uri:uri
        else:
            build_absolute_uri = request.build_absolute_uri

        if isinstance(bushfire,int):
            bushfire = Bushfire.objects.get(id=bushfire)
        elif isinstance(bushfire,basestring):
            bushfire = Bushfire.objects.get(fire_number=bushfire)
        elif not isinstance(bushfire,Bushfire):
            raise Exception("Must pass in bushfire report id or bushfire report fire number or bushfire report object.")


        if bushfire.dfes_incident_no:
            raise Exception("Bushfire report({}) already has dfes incident no ({})".format(bushfire.fire_number,bushfire.dfes_incident_no))

        subject = None
        response = None
        incident_no = None
        url = None
        try:
            initial_snapshot_url = build_absolute_uri(reverse('bushfire:initial_snapshot', kwargs={'pk':bushfire.id}))
            payload = render_to_string(cls.create_incident_template,context={"bushfire":bushfire,"now":timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),"initial_snapshot_url":initial_snapshot_url})
            payload = payload.strip()

            headers = {'Content-Type':'application/xml'}

            url = "{}/api/v1/incidents".format(settings.P1CAD_ENDPOINT)
            if settings.P1CAD_USER:
                resp = requests.post(url,data=payload,auth=HttpNtlmAuth(settings.P1CAD_USER,settings.P1CAD_PASSWORD),verify=settings.P1CAD_SSL_VERIFY,headers=headers)
            else:
                resp = requests.post(url,data=payload,verify=settings.P1CAD_SSL_VERIFY,headers=headers)
    
            resp.raise_for_status()
            result = resp.json()
            incident_no = result.get("DFESIncidentID") or result.get("IncidentId")
            if not incident_no:
                raise Exception("Can't get the incident no from the response ({})".format(result))
            response = resp.text

            subject = "Create dfes incident no '{1}' for bushfire report '{0}'".format(bushfire.fire_number,incident_no)

            return incident_no

        except Exception as e:
            traceback.print_exc()
            subject = "Failed to create dfes incident no for bushfire report '{0}'".format(bushfire.fire_number)
            response = traceback.format_exc()
            raise Exception("Failed to create dfes incident no for bushfire ({}). {}".format(bushfire.fire_number,str(e)))
        finally:
            previous_incident_no = bushfire.dfes_incident_no
            try:
                bushfire.dfes_incident_no = incident_no
                user_email = request.user.email if request and settings.CC_TO_LOGIN_USER else None
                from .utils import send_email
                resp = send_email({
                    "bushfire":bushfire, 
                    "user_email":user_email,
                    "to_email":settings.P1CAD_NOTIFY_EMAIL,
                    "request":request,
                    "external_email":False,
                    "subject":subject,
                    "p1cad_endpoint":url,
                    "payload":escape(payload),
                    "response":response,
                    "template":"bfrs/email/create_incident_no_notify_email.html"
                })
            finally:
                #recover the previous incident no
                bushfire.dfes_incident_no = previous_incident_no
    
    @classmethod
    def test_create_incident(cls,bushfire = None):
        if settings.ENV_TYPE == 'prod':
            raise Exception("You can't call this method in prod environment.")
        if bushfire is None:
            bushfire = Bushfire.objects.all().first()
            bushfire.dfes_incident_no = None
        elif isinstance(bushfire,int):
            bushfire = Bushfire.objects.get(id=bushfire)
        elif isinstance(bushfire,basestring):
            bushfire = Bushfire.objects.get(fire_number=bushfire)
        elif not isinstance(bushfire,Bushfire):
            raise Exception("Must pass in bushfire report id or bushfire report fire number or bushfire report object.")

        bushfire.dfes_incident_no = None

        print("dfes_incident_no of bushfire report '{}' is {}".format(bushfire.fire_number,cls.create_incident(bushfire)))

        



