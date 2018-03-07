from django.conf.urls import url
from django.conf import settings
from tastypie.resources import ModelResource, Resource
from tastypie.authorization import Authorization, ReadOnlyAuthorization, DjangoAuthorization
from tastypie.resources import ModelResource, ALL, ALL_WITH_RELATIONS
from tastypie.api import Api
from tastypie import fields
from bfrs.models import Profile, Region, District, Bushfire, Tenure, current_finyear
from bfrs.utils import update_areas_burnt, invalidate_bushfire, serialize_bushfire, is_external_user, can_maintain_data

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException
from tastypie.http import HttpBadRequest, HttpUnauthorized, HttpAccepted
from tastypie.exceptions import ImmediateHttpResponse, Unauthorized
import json


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

#class BFRSUserAuthorization(Authorization):
#    def create_detail(self, object_list, bundle):
#        import ipdb; ipdb.set_trace()
#        if is_external_user(bundle.request.user):
#            raise Unauthorized("Create Not Permitted.")
#        return True
#
#    def update_detail(self, object_list, bundle):
#        import ipdb; ipdb.set_trace()
#        if is_external_user(bundle.request.user):
#            raise Unauthorized("Update Not Permitted.")
#        return True
#
#    def delete_list(self, object_list, bundle):
#        # Sorry user, no deletes for you!
#        raise Unauthorized("Delete Not Permitted.")
#
#    def delete_detail(self, object_list, bundle):
#        raise Unauthorized("Delete Not Permitted.")


class APIResource(ModelResource):
    class Meta:
        pass

    def prepend_urls(self):
        return [
            url(
                r"^(?P<resource_name>{})/fields/(?P<field_name>[\w\d_.-]+)/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def determine_format(self, request):
        """
        Used to determine the desired format.

        Largely relies on ``tastypie.utils.mime.determine_format`` but here
        as a point of extension.
        """
        if request.GET.get('format'):
            return determine_format(request, self._meta.serializer, default_format=self._meta.default_format)
        else:
            return self._meta.serializer.get_mime_for_format("json")

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
        allowed_methods=[]
        list_allowed_methods=[]

    @property
    def urls(self):
        return [
            url(
                r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def field_values(self, request, **kwargs):
        try:
            if hasattr(request.user, 'profile'):
                qs = self._meta.queryset.filter(id=request.user.profile.id)
                data = qs[0].to_dict() if len(qs)>0 else None
            else:
                data = {'username': request.user.username, 'user_id': request.user.id, 'region_id': None, 'district': None, 'region': None, 'district_id': None}
        except FieldError as e:
            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
        return self.create_response(request, data=data)

class RegionResource(APIResource):
    class Meta:
        queryset = Region.objects.all()
        resource_name = 'region'
        authorization= ReadOnlyAuthorization()
        allowed_methods=[]
        list_allowed_methods=[]

    @property
    def urls(self):
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

class TenureResource(APIResource):
    class Meta:
        queryset = Tenure.objects.all()
        resource_name = 'tenure'
        authorization= ReadOnlyAuthorization()
        #fields = ['origin_point', 'fire_boundary', 'area', 'fire_position', 'tenure_id']
        allowed_methods=['get']
        list_allowed_methods=['get']


class BushfireResource(APIResource):
    """ http://localhost:8000/api/v1/bushfire/?format=json
        curl --dump-header - -H "Content-Type: application/json" -X PATCH --data '{"origin_point":[11,-12], "area":12347, "fire_boundary": [[[[115.6528663436689,-31.177579372720448],[116.20507608972612,-31.386375097597803],[116.36167288338414,-31.009993330384674],[115.77374807912422,-30.999004081706918],[115.6528663436689,-31.177579372720448]]]]}' http://localhost:8000/api/v1/bushfire/1/?format=json
    """

    class Meta:
        queryset = Bushfire.objects.all()
        resource_name = 'bushfire'
        authorization= DjangoAuthorization()
        #fields = ['origin_point', 'fire_boundary', 'area', 'fire_position']
        fields = ['origin_point', 'fire_boundary']
        allowed_methods=['patch']
        list_allowed_methods=[]

    def field_values(self, request, **kwargs):
        # Get a list of unique values for the field passed in kwargs.
        if kwargs['field_name'] == 'year':
            qs = Bushfire.objects.all().distinct().order_by('year').values_list('year', flat=True)[::1]
            year_list = qs if current_finyear() in qs else qs + [current_finyear()]
            return self.create_response(request, data=year_list)
        elif kwargs['field_name'] == 'fire_number':
        # Get a list of fire_numbers and names for the field passed in kwargs and request.GET params.
            qs = Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED)
            if request.GET.get('region_id'):
                qs = qs.filter(region_id=request.GET.get('region_id'))
            if request.GET.get('district_id'):
                qs = qs.filter(district_id=request.GET.get('district_id'))
            if request.GET.get('year'):
                qs = qs.filter(year=request.GET.get('year'))

            qs = qs.order_by('fire_number').values('fire_number', 'name', 'tenure__name', 'other_tenure')

            for i in qs:
                if i['other_tenure']:
                    if i['other_tenure'] == Bushfire.IGNITION_POINT_CROWN:
                        i['other_tenure'] = 'Other - Crown'
                    elif i['other_tenure'] == Bushfire.IGNITION_POINT_PRIVATE:
                        i['other_tenure'] = 'Other - Private'
                    else:
                        i['other_tenure'] = 'Other'

            return self.create_response(request, data=list(qs))


        return super(BushfireResource, self).field_values(request, **kwargs)

    def hydrate_origin_point(self, bundle):
        """
        Converts the json string format to the one required by tastypie's full_hydrate() method
        converts the string: [11,-12] --> POINT (11 -12)
        """
        if bundle.data.has_key('origin_point') and isinstance(bundle.data['origin_point'], list):
            bundle.data['origin_point'] = Point(bundle.data['origin_point']).__str__()

        if bundle.data.has_key('origin_point_mga'):
            bundle.data['origin_point_mga'] = bundle.data['origin_point_mga']
        return bundle

    def hydrate_fire_boundary(self, bundle):
        if bundle.data.has_key('fire_boundary') and isinstance(bundle.data['fire_boundary'], list):
            bundle.data['fire_boundary'] = MultiPolygon([Polygon(*p) for p in bundle.data['fire_boundary']]).__str__()

            #if bundle.data.has_key('area') and bundle.data['area'].has_key('total_area') and bundle.data['area']['total_area']:
            if bundle.data.has_key('area') and bundle.data['area'].has_key('total_area'):
                bundle.obj.tenures_burnt.all().delete()

            if bundle.obj.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED:
                bundle.obj.final_fire_boundary = True

            if bundle.obj.is_reviewed:
                bundle.obj.reviewed_by = None
                bundle.obj.reviewed_date = None
                bundle.obj.report_status = Bushfire.STATUS_FINAL_AUTHORISED

        if not ( bundle.data.has_key('fire_boundary') and isinstance(bundle.data['fire_boundary'], (str, unicode)) ):
            # bundle.data['fire_boundary'] is a string/unicode, therefore spatial data not changed, probably origin has moved only
            bundle.obj.fire_boundary = None
            bundle.obj.final_fire_boundary = False

        if bundle.data.has_key('fb_validation_req'):
            bundle.data['fb_validation_req'] = bundle.data['fb_validation_req']

        return bundle

    def obj_update(self, bundle, **kwargs):

        if bundle.request.GET.has_key('checkpermission') and bundle.request.GET['checkpermission'] == 'true':
            # Allows SSS to perform permission check
            if is_external_user(bundle.request.user) or \
               (not can_maintain_data(bundle.request.user) and bundle.obj.report_status >= Bushfire.STATUS_FINAL_AUTHORISED):
                raise ImmediateHttpResponse(response=HttpUnauthorized())
            else:
                raise ImmediateHttpResponse(response=HttpAccepted())
    
        # Allows BFRS and SSS to perform update only if permitted
        if is_external_user(bundle.request.user):
            return bundle

        if not can_maintain_data(bundle.request.user) and bundle.obj.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
            raise ImmediateHttpResponse(response=HttpUnauthorized())

        self.full_hydrate(bundle)
        #bundle.obj.sss_data = json.dumps(bundle.data)
        sss_data = bundle.data
        #import ipdb; ipdb.set_trace()
        if sss_data.has_key('fire_boundary'):
            sss_data.pop('fire_boundary')
        #if sss_data.has_key('area') and sss_data.get('area').has_key('tenure_area'):
        #    sss_data.get('area').pop('tenure_area') # necessary for the initial create stagei for display in form, since object not yet saved
        bundle.obj.sss_data = json.dumps(sss_data)

        if bundle.data.has_key('tenure_ignition_point') and bundle.data['tenure_ignition_point'] and \
            bundle.data['tenure_ignition_point'].has_key('category') and bundle.data['tenure_ignition_point']['category']:
            try:
                bundle.obj.tenure = Tenure.objects.get(name__istartswith=bundle.data['tenure_ignition_point']['category'])
            except:
                bundle.obj.tenure = Tenure.objects.get(name__iendswith='other')
        elif bundle.data.has_key('tenure_ignition_point') and not bundle.data['tenure_ignition_point']:
            bundle.obj.tenure = Tenure.objects.get(name__iendswith='other')

        if bundle.data.has_key('area') and bundle.data['area'].has_key('layers') and bundle.data['area']['layers']:
            update_areas_burnt(bundle.obj, bundle.data['area']['layers'])


        if bundle.data.has_key('area') and bundle.data['area'].has_key('total_area') and bundle.data['area']['total_area']:
            if bundle.obj.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                bundle.obj.area_unknown = False
                initial_area = round(float(bundle.data['area']['total_area']), 2)
                bundle.obj.initial_area = initial_area if initial_area > 0 else 0.01
            else:
                bundle.obj.area_limit = False
                area = round(float(bundle.data['area']['total_area']), 2)
                bundle.obj.area = area if area > 0 else 0.01

        if bundle.data.has_key('area') and bundle.data['area'].has_key('other_area') and bundle.data['area']['other_area']:
            other_area = round(float(bundle.data['area']['other_area']), 2)
            bundle.obj.other_area = other_area if other_area > 0 else 0.01

        if bundle.data.has_key('fire_position') and bundle.data['fire_position']:
            # only update if user has not over-ridden
            if not bundle.obj.fire_position_override:
                bundle.obj.fire_position = bundle.data['fire_position']

        if bundle.data.has_key('region_id') and bundle.data.has_key('district_id') and bundle.data['region_id'] and bundle.data['district_id']:
            if bundle.data['district_id'] != bundle.obj.district.id and bundle.obj.report_status == Bushfire.STATUS_INITIAL:
                district = District.objects.get(id=bundle.data['district_id'])
                invalidate_bushfire(bundle.obj, district, bundle.request.user)

        if bundle.obj.report_status >=  Bushfire.STATUS_FINAL_AUTHORISED:
            # if bushfire has been authorised, update snapshot and archive old snapshot
            serialize_bushfire('final', 'SSS Update', bundle.obj)

        bundle.obj.save()
        return bundle


v1_api = Api(api_name='v1')
v1_api.register(BushfireResource())
v1_api.register(ProfileResource())
v1_api.register(RegionResource())
v1_api.register(TenureResource())
