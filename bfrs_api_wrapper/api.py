from django.http import Http404, HttpResponse, JsonResponse, HttpResponseRedirect
import requests
import json

def create_dfes_incident(request):
    print (request)
    
    url = "{}/api/v1/incidents".format(settings.P1CAD_ENDPOINT)
    if settings.P1CAD_USER:
        resp = requests.post(url,data=payload,auth=HttpNtlmAuth(settings.P1CAD_USER,settings.P1CAD_PASSWORD),verify=settings.P1CAD_SSL_VERIFY,headers=headers)
    else:
        resp = requests.post(url,data=payload,verify=settings.P1CAD_SSL_VERIFY,headers=headers)

    return HttpResponse(resp)
