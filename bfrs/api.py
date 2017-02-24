from django.conf.urls import url
from tastypie.resources import ModelResource, Resource
from tastypie.authorization import Authorization, ReadOnlyAuthorization
from tastypie.resources import ModelResource, ALL, ALL_WITH_RELATIONS
from tastypie.api import Api
from tastypie import fields
from bfrs.models import Profile, Bushfire
from django.contrib.auth.models import User

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


#class ProfileResource(APIResource):
#    """ http://localhost:8000/api/v1/profile/?format=json
#    """
#
#    def field_values(self, request, **kwargs):
#        """
#        http://localhost:8000/api/v1/profile/fields/user/?format=json
#        """
#        # Get a dict of user profiles, together with their region/district
#        try:
#            if kwargs['field_name'] != 'user':
#                return super(ProfileResource, self).field_values(request, **kwargs)
#
#            #qs = self._meta.queryset.distinct()
#            qs = Profile.objects.all().distinct()
#        except FieldError as e:
#            return self.create_response(request, data={'error': str(e)}, response_class=HttpBadRequest)
#        # Prepare return the HttpResponse.
#        #import ipdb; ipdb.set_trace()
#        return self.create_response(request, data=([q.to_dict() for q in qs]))
#
#
##    Meta = generate_meta(Profile)
#    class Meta:
#        queryset = Profile.objects.all()
#        authorisation=ReadOnlyAuthorization()
#        resource_name = 'profile'


class UserResource(APIResource):
    userprofile = fields.ToManyField('ProfileResource', 'profile', full=True, null=False)
    Meta = generate_meta(User)


class ProfileResource(APIResource):
    user = fields.ToOneField(UserResource,'user')
    Meta = generate_meta(Profile)


class BushfireResource(APIResource):
    """ http://localhost:8000/api/v1/bushfire/?format=json
    """
    Meta = generate_meta(Bushfire)



v1_api = Api(api_name='v1')
v1_api.register(BushfireResource())
v1_api.register(ProfileResource())
v1_api.register(UserResource())
