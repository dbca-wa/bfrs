from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
from django.conf import settings
from requests_ntlm import HttpNtlmAuth
from django.views.decorators.csrf import csrf_exempt

import requests
import json

@csrf_exempt
def create_dfes_incident(request):
    
    # headers = request.POST.get('headers', {})
    # payload = request.POST.get('payload', {})
    # api_key = request.POST.get('api_key', '')
    request_body = json.loads(request.body.decode())
    # print (request_body)
    headers = request_body['headers']
    payload = request_body['payload']
    api_key = request_body['api_key']

    if api_key == settings.DFES_WRAPPER_KEY:
        print ("Key Verified")
        url = "{}/api/v1/incidents".format(settings.P1CAD_ENDPOINT)
        print (url)
        if settings.P1CAD_USER:
            resp = requests.post(url,data=payload,auth=HttpNtlmAuth(settings.P1CAD_USER,settings.P1CAD_PASSWORD),verify=settings.P1CAD_SSL_VERIFY,headers=headers)
        else:
            resp = requests.post(url,data=payload,verify=settings.P1CAD_SSL_VERIFY,headers=headers)

        print (resp)
        return HttpResponse(resp)
    else:
        return HttpResponse("Incorrect Key", status=401)

