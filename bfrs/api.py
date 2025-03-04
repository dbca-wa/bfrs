import traceback
# from django.conf.urls import url
from django.urls import include, path, re_path
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from tastypie.resources import ModelResource, Resource
from tastypie.authorization import Authorization, ReadOnlyAuthorization, DjangoAuthorization
from tastypie.resources import ModelResource, ALL, ALL_WITH_RELATIONS
from tastypie.utils.mime import determine_format
from tastypie.api import Api
from tastypie import fields
from bfrs.models import Profile, Region, District, Bushfire, Tenure, current_finyear,BushfireProperty,CaptureMethod
from bfrs.utils import update_areas_burnt, invalidate_bushfire, serialize_bushfire, is_external_user, can_maintain_data,get_tenure,update_status

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
        abstract = True
        # pass

    def prepend_urls(self):
        return [
            # url(
            #     r"^(?P<resource_name>{})/fields/(?P<field_name>[\w\d_.-]+)/$".format(self._meta.resource_name),
            #     self.wrap_view('field_values'), name="api_field_values"),
            re_path(
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
            # url(
            #     r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
            #     self.wrap_view('field_values'), name="api_field_values"),
            re_path(
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

class CaptureMethodResource(APIResource):
    class Meta:
        queryset = CaptureMethod.objects.all()
        resource_name = 'capturemethod'
        authorization= ReadOnlyAuthorization()
        allowed_methods=[]
        list_allowed_methods=[]

    @property
    def urls(self):
        return [
            # url(
            #     r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
            #     self.wrap_view('field_values'), name="api_field_values"),
            re_path(
                r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
                self.wrap_view('field_values'), name="api_field_values"),
        ]

    def field_values(self, request, **kwargs):
        try:
            qs = CaptureMethod.objects.all()
        except FieldError as e:
            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
        return self.create_response(request, data=([q.to_dict() for q in qs]))

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
            # url(
            #     r"^(?P<resource_name>{})/$".format(self._meta.resource_name),
            #     self.wrap_view('field_values'), name="api_field_values"),
            re_path(
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
    class Meta:
        queryset = Bushfire.objects.all()
        resource_name = 'bushfire'
        authorization= ReadOnlyAuthorization()
        allowed_methods=[]
        list_allowed_methods=[]

    @property
    def urls(self):
        return self.prepend_urls()

    def field_values(self, request, **kwargs):
        # Get a list of unique values for the field passed in kwargs.
        if kwargs['field_name'] == 'year':
            qs = Bushfire.objects.all().distinct().order_by('year').values_list('year', flat=True)[::1]
            year_list = qs if current_finyear() in qs else qs + [current_finyear()]
            return self.create_response(request, data=year_list)
        elif kwargs['field_name'] == 'fire_number':
        # Get a list of fire_numbers and names for the field passed in kwargs and request.GET params.
            if request.GET.get('include_final_report') == 'true':
                qs = Bushfire.objects.filter(report_status__in=(Bushfire.STATUS_INITIAL_AUTHORISED,Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED))
            else:
                qs = Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED)
            if request.GET.get('region_id'):
                qs = qs.filter(region_id=request.GET.get('region_id'))
            if request.GET.get('district_id'):
                qs = qs.filter(district_id=request.GET.get('district_id'))
            if request.GET.get('year'):
                qs = qs.filter(year=request.GET.get('year'))

            qs = qs.order_by('fire_number').values('fire_number', 'name', 'tenure__name')


            return self.create_response(request, data=list(qs))


        return super(BushfireResource, self).field_values(request, **kwargs)

class BushfireSpatialResource(ModelResource):
    """ http://localhost:8000/api/v1/bushfire/?format=json
        curl --dump-header - -H "Content-Type: application/json" -X PATCH --data '{"origin_point":[11,-12], "area":12347, "fire_boundary": [[[[115.6528663436689,-31.177579372720448],[116.20507608972612,-31.386375097597803],[116.36167288338414,-31.009993330384674],[115.77374807912422,-30.999004081706918],[115.6528663436689,-31.177579372720448]]]]}' http://localhost:8000/api/v1/bushfire/1/?format=json
    """
    class Meta:
        queryset = Bushfire.objects.all()
        resource_name = 'bushfirespatial'
        authorization = Authorization()
        #fields = ['origin_point', 'fire_boundary', 'area', 'fire_position']
        fields = ['origin_point', 'fire_boundary','origin_point_mga','origin_point_grid','fb_validation_req']
        #using extra fields to process some complex or related fields
        extra_fields = ['district','area','tenure_ignition_point','fire_position','plantations','sss_data','capturemethod']
        allowed_methods=['patch']
        list_allowed_methods=[]

    def hydrate(self, bundle):
        for field_name in self._meta.extra_fields:
            m = getattr(self,"hydrate_{}".format(field_name)) if hasattr(self,"hydrate_{}".format(field_name)) else None
            if m:
                m(bundle)
        bundle.obj.modifier = bundle.request.user
        return super(BushfireSpatialResource,self).hydrate(bundle)
        
    def hydrate_origin_point(self, bundle):
        """
        Converts the json string format to the one required by tastypie's full_hydrate() method
        converts the string: [11,-12] --> POINT (11 -12)
        """
        # if bundle.data.has_key('origin_point') and isinstance(bundle.data['origin_point'], list):
        if 'origin_point' in bundle.data and isinstance(bundle.data['origin_point'], list):
            bundle.data['origin_point'] = Point(bundle.data['origin_point'])

        #print("processing origin point,set origin_point to {}".format(bundle.data["origin_point"]))
        return bundle

    def hydrate_fire_boundary(self, bundle):
        if not 'fire_boundary' in bundle.data:
            #fire_boundary is not passed in
            return

        if bundle.data['fire_boundary'] == None:
            #bushfire has no fire boundaries
            bundle.obj.final_fire_boundary = False
            bundle.obj.fireboundary_uploaded_by = None
            bundle.obj.fireboundary_uploaded_date = None
        elif isinstance(bundle.data['fire_boundary'], list):
            #bushfire has fire boundaries
            bundle.data['fire_boundary'] = MultiPolygon([Polygon(*p) for p in bundle.data['fire_boundary']])
            bundle.obj.fireboundary_uploaded_by = bundle.request.user
            bundle.obj.fireboundary_uploaded_date = timezone.now()

            if bundle.obj.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED:
                bundle.obj.final_fire_boundary = True
            else:
                bundle.obj.final_fire_boundary = False

            if bundle.obj.is_reviewed:
                bundle.obj.reviewed_by = None
                bundle.obj.reviewed_date = None
                bundle.obj.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        #print("processing fire boundary,set fire_boundary to {}".format(bundle.data["fire_boundary"]))
        return bundle

    def hydrate_tenure_ignition_point(self,bundle):
        # if not bundle.data.has_key('tenure_ignition_point'):
        if not 'tenure_ignition_point' in bundle.data:
            #tenure_ignition_point is not passed in
            return

        if bundle.data['tenure_ignition_point'] and bundle.data['tenure_ignition_point'].get('category'):
            #origin point is within dpaw_tenure
            try:
                bundle.obj.tenure = get_tenure(bundle.data['tenure_ignition_point']['category'])
            except:
                bundle.obj.tenure = Tenure.OTHER
        else:
            #origin point is not within dpaw_tenure
            bundle.obj.tenure = Tenure.OTHER
        #print("processing tenure_ignition_point,set tenure = {}".format(bundle.obj.tenure))


    def hydrate_area(self,bundle):
        # if not bundle.data.has_key('area'):
        if not 'area' in bundle.data:
            #area is not passed in
            return
        #print("processing area")

        if (bundle.data.get('area') or {}).get('total_area') == None:
            #bushfire has no fire boundary
            if bundle.obj.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                if bundle.obj.fire_boundary:
                    #before inital fire report has fire boundary
                    bundle.obj.initial_area_unknown = False
                    bundle.obj.initial_area = None
                    bundle.obj.other_area = None
                    #print("processing area, set inital_area_unkown to false, inital_area to null,other_area to null for initial report")
            elif bundle.obj.final_fire_boundary:
                #before submitted fire report has fire boundary
                bundle.obj.area_limit = False
                bundle.obj.area = None
                bundle.obj.other_area = None
                #print("processing area, set area_limit to false, area to null,other_area to null for submitted report")
        else:
            #bushfire has fire boundary
            if (bundle.data.get('area') or {}).get('other_area'):
                bundle.obj.other_area = round(float(bundle.data['area']['other_area']), 2)
                """
                let user choose whether saving the data or not in sss side.
                if bundle.obj.other_area < -0.1:
                    raise ValidationError("The sum({}) of burning area({}) is larger than the total burning area ({}).\r\nPleace check the three layers ('cddp:legislated_lands_and_waters','cddp:dept_interest_lands_and_waters','cddp:other_tenures')".format(round(bundle.data["area"]["total_area"] - bundle.data["area"]["other_area"],2) ,dict([(name,round(layer["total_area"],2)) for name,layer in bundle.data["area"]["layers"].iteritems()]),round(bundle.data["area"]["total_area"],2)))
                """
            else:
                bundle.obj.other_area = 0

            if bundle.obj.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                bundle.obj.initial_area_unknown = False
                bundle.obj.initial_area = round(float(bundle.data['area']['total_area']), 2)
                #print("processing area, set inital_area_unkown to false, inital_area to {},other_area to {} for initial report".format(bundle.obj.initial_area,bundle.obj.other_area))
            else:
                bundle.obj.area_limit = False
                bundle.obj.area = round(float(bundle.data['area']['total_area']), 2)
                #print("processing area, set area_limit to false, area to {},other_area to {} for submitted report".format(bundle.obj.area,bundle.obj.other_area))

    def hydrate_capturemethod(self,bundle):
        # if not bundle.data.has_key('capturemethod'):
        if not 'capturemethod' in bundle.data:
            #capturemethod is not passed in
            return
        if bundle.data.get('capturemethod'):
            bundle.obj.capturemethod = CaptureMethod.objects.get(id=bundle.data.get('capturemethod'))
            if bundle.obj.capturemethod.code == CaptureMethod.OTHER_CODE:
                #other capture method
                bundle.obj.other_capturemethod = bundle.data.get('other_capturemethod') or ""
            else:
                #not other capture method
                bundle.obj.other_capturemethod = None
        else:
            bundle.obj.capturemethod = None
            bundle.obj.other_capturemethod = None

    def hydrate_fire_position(self,bundle):
        # if not bundle.data.has_key('fire_position'):
        if not 'fire_position' in bundle.data:
            #fire_position is not passed in
            return
        if bundle.obj.fire_position_override:
            #user override the fire position, ignore the fire_position 
            #print("processing fire position, fire position is overriden by user, ignore the new fire position")
            return

        #print("processing fire position, set value to {}".format(bundle.data['fire_position']) )
        bundle.obj.fire_position = bundle.data['fire_position']


    def hydrate_district(self,bundle):
        if not bundle.data.get('region_id') or not bundle.data.get('district_id'):
            #region_id or district_id is not passed in
            return

        if bundle.obj.report_status != Bushfire.STATUS_INITIAL:
            #normal user can't move a submitted bushfire from one district to another district. 
            #only the user in the group "Fire Information Management" can do it from bfrs web application
            return

        bundle.obj.district = District.objects.get(id=bundle.data['district_id'])
        bundle.obj.region = bundle.obj.district.region
        #print("processing district, set district to {}".format(bundle.obj.district) )

    def hydrate_sss_data(self,bundle):
        #print("processing sss data" )
        sss_data = bundle.data
        
        datas = []
        for key in ["fire_boundary","plantations"]:
            # if sss_data.has_key(key):
            if key in sss_data:
                datas.append((key,sss_data.pop(key)))

        bundle.obj.sss_data = json.dumps(sss_data)
        for data in datas:
            sss_data[data[0]] = data[1]


    def obj_update(self, bundle, **kwargs):
        try:
            # Allows BFRS and SSS to perform update only if permitted
            if is_external_user(bundle.request.user):
                raise ImmediateHttpResponse(response=HttpUnauthorized())
    
            if not can_maintain_data(bundle.request.user) and bundle.obj.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
                raise ImmediateHttpResponse(response=HttpUnauthorized())
    
            # if bundle.request.GET.has_key('checkpermission') and bundle.request.GET['checkpermission'] == 'true':
            if 'checkpermission' in bundle.request.GET and bundle.request.GET['checkpermission'] == 'true':
                #this is a permission checking request,return directly.
                raise ImmediateHttpResponse(response=HttpAccepted())
    
            self.full_hydrate(bundle)
            #invalidate current bushfire if required.
            bundle.obj,invalidated = invalidate_bushfire(bundle.obj, bundle.request.user) or (bundle.obj,False)
    
            if not invalidated:
                bundle.obj.save()
    
            # if bundle.data.has_key('area'):
            if 'area' in bundle.data:
                if (bundle.data.get('area') or {}).get('total_area') == None:
                    #no burning area,
                    bundle.obj.tenures_burnt.all().delete()
                else:
                    #print("Clear tenure burnt data")
                    if bundle.obj.report_status != Bushfire.STATUS_INITIAL and bundle.data['area'].get('layers'):
                        #report is not a initial report, and has area burnt data, save it.
                        #print("Populate new tenure burnt data")
                        update_areas_burnt(bundle.obj, bundle.data['area'])
                    else:
                        #report is a initial report,or has no area burnt data. clear the existing area burnt data
                        #area burnt data is unavailable for initial report
                        bundle.obj.tenures_burnt.all().delete()
    
            #save plantations
            if "plantations" in bundle.data:
                #need to update plantations
                if bundle.data.get("plantations"):
                    #has plantation data
                    BushfireProperty.objects.update_or_create(bushfire=bundle.obj,name="plantations",defaults={"value":json.dumps(bundle.data.get("plantations"))})
                else:
                    #no plantation data,remove the plantations data from table
                    BushfireProperty.objects.filter(bushfire=bundle.obj,name="plantations").delete()
    
            if bundle.obj.report_status >=  Bushfire.STATUS_FINAL_AUTHORISED:
                if bundle.obj.fire_boundary.contains(bundle.obj.origin_point):
                    # if bushfire has been authorised, update snapshot and archive old snapshot
                    serialize_bushfire('final', 'SSS Update', bundle.obj)
                else:
                    if bundle.obj.is_reviewed:
                        update_status(bundle.request, bundle.obj, "delete_review",action_desc="Delete review because origin point is outside of fire boundary after uploading from SSS",action_name="Upload")

                    if bundle.obj.is_final_authorised:
                        update_status(bundle.request, bundle.obj, "delete_final_authorisation",action_desc="Delete final auth because origin point is outside of fire boundary after uploading from SSS",action_name="Upload")

                #print("serizlie bushfire")
    
            if invalidated:
                raise ImmediateHttpResponse(response=JsonResponse({"id":bundle.obj.id,"fire_number":bundle.obj.fire_number},status=280))
            else:
                return bundle
        except:
            # if bundle.request.GET.has_key('checkpermission') and bundle.request.GET['checkpermission'] == 'true':
            if 'checkpermission' in bundle.request.GET and bundle.request.GET['checkpermission'] == 'true':
                #for permission checking purpose, don't log the exception in log file.
                pass
            else:
                traceback.print_exc()
            raise

v1_api = Api(api_name='v1')
v1_api.register(BushfireResource())
v1_api.register(BushfireSpatialResource())
v1_api.register(ProfileResource())
v1_api.register(RegionResource())
v1_api.register(TenureResource())
v1_api.register(CaptureMethodResource())
