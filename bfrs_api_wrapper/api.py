from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.conf import settings
from requests_ntlm import HttpNtlmAuth

import requests
import json

def create_dfes_incident(request):
    headers = request.POST.get('headers', {})
    payload = request.POST.get('payload', {})
    
    url = "{}/api/v1/incidents".format(settings.P1CAD_ENDPOINT)
    if settings.P1CAD_USER:
        resp = requests.post(url,data=payload,auth=HttpNtlmAuth(settings.P1CAD_USER,settings.P1CAD_PASSWORD),verify=settings.P1CAD_SSL_VERIFY,headers=headers)
    else:
        resp = requests.post(url,data=payload,verify=settings.P1CAD_SSL_VERIFY,headers=headers)
    print (resp)
    return HttpResponse(resp)
