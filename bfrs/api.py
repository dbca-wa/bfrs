from django.conf.urls import url
from tastypie.resources import ModelResource, Resource
from tastypie.authorization import Authorization, ReadOnlyAuthorization, DjangoAuthorization
from tastypie.resources import ModelResource, ALL, ALL_WITH_RELATIONS
from tastypie.api import Api
from tastypie import fields
from bfrs.models import Profile, Region, District, Bushfire
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException
from tastypie.http import HttpBadRequest
from tastypie.exceptions import ImmediateHttpResponse

"""
The two helper methods below allow to replace class like:

class BushfireResource(ModelResource):
    class Meta:
        queryset = Bushfire.objects.all()
        resource_name = 'bushfire'
        filtering = {
            'regions': ALL_WITH_RELATIONS,
            'incident_no': ALL_WITH_RELATIONS,
            'name': ALL_WITH_RELATIONS,
        }
        authorization= Authorization()

with:

class BushfireResource(ModelResource):
    Meta = generate_meta(Bushfire)

"""

def generate_filtering(mdl):
    """Utility function to add all model fields to filtering whitelist.
    See: http://django-tastypie.readthedocs.org/en/latest/resources.html#basic-filtering
    """
    filtering = {}
    for field in mdl._meta.fields:
        filtering.update({field.name: ALL_WITH_RELATIONS})
    return filtering


def generate_meta(klass):
    return type('Meta', (object,), {
        'queryset': klass.objects.all(),
        'resource_name': klass._meta.model_name,
        'filtering': generate_filtering(klass),
        'authorization': Authorization(),
        'always_return_data': True
    })


class APIResource(ModelResource):
    class Meta:
        pass

    def prepend_urls(self):
        return [
            url(
                r"^(?P<resource_name>{})/fields/(?P<field_name>[\w\d_.-]+)/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def field_values(self, request, **kwargs):
        # Get a list of unique values for the field passed in kwargs.
        try:
            qs = self._meta.queryset.values_list(kwargs['field_name'], flat=True).distinct()
        except FieldError as e:
            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
        # Prepare return the HttpResponse.
        return self.create_response(request, data=list(qs))


class ProfileResource(APIResource):
    class Meta:
        queryset = Profile.objects.all()
        resource_name = 'profile'
        authorization= ReadOnlyAuthorization()

    def prepend_urls(self):
        return [
            url(
                r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def field_values(self, request, **kwargs):
        try:
            qs = self._meta.queryset.filter(id=request.user.profile.id)
            data = qs[0].to_dict() if len(qs)>0 else None
        except FieldError as e:
            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
        return self.create_response(request, data=data)

class RegionResource(APIResource):
    class Meta:
        queryset = Region.objects.all()
        resource_name = 'region'
        authorization= ReadOnlyAuthorization()

    def prepend_urls(self):
        return [
            url(
                r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def field_values(self, request, **kwargs):
        try:
            qs = Region.objects.all().distinct()
        except FieldError as e:
            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
        return self.create_response(request, data=([q.to_dict() for q in qs]))


class BushfireResource(APIResource):
    """ http://localhost:8000/api/v1/bushfire/?format=json
        curl --dump-header - -H "Content-Type: application/json" -X PATCH --data '{"area":12348, "origin_point":"POINT (11 -12.5)", "fire_boundary":"MULTIPOLYGON (((115.6528663436689 -31.17757937272045, 116.2050760897261 -31.3863750975978, 116.3616728833841 -31.00999333038467, 115.7737480791242 -30.99900408170692, 115.6528663436689 -31.17757937272045)))"}' http://localhost:8000/api/v1/bushfire/1/?format=json

    """
    class Meta:
        queryset = Bushfire.objects.all()
        resource_name = 'bushfire'
        authorization= Authorization()
        #allowed_methods = ['get', 'post', 'put', 'delete', 'patch']
        fields = ['id', 'name', 'origin_point', 'fire_boundary', 'area']

#    def hydrate(self, bundle):
#        import ipdb; ipdb.set_trace()
#        request_method=bundle.request.META['REQUEST_METHOD']
#
#        if request_method=='PATCH':
#            try:
#                if bundle.obj.has_restapi_write_perms:
#                    if bundle.data.has_key('area'):
#                        bundle.obj.area = float(bundle.data['area'])
#
#                    if bundle.data.has_key('origin_point'):
#                        #bundle.obj.origin_point = Point(bundle.data['origin_point'])
#                        bundle.obj.origin_point = GEOSGeometry(bundle.data['origin_point'])
#
#                    if bundle.data.has_key('fire_boundary'):
#                        arr = bundle.data['fire_boundary']
#                        #bundle.obj.fire_boundary = MultiPolygon(Polygon(arr[0][0]))
#                        bundle.obj.fire_boundary = GEOSGeometry(bundle.data['fire_boundary'])
#
#                    bundle.obj.save()
#                return bundle
#
#            except Exception as e:
#                raise ImmediateHttpResponse(response=HttpBadRequest(e))
#
#        return bundle


v1_api = Api(api_name='v1')
v1_api.register(BushfireResource())
v1_api.register(ProfileResource())
v1_api.register(RegionResource())
