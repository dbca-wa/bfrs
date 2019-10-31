import json

from django.views.generic.edit import FormView
from django.http import HttpResponse
from django.db import models
try:
    from django.apps import apps
    get_model = apps.get_model
except ImportError:
    from django.db.models.loading import get_model

class ChainedModelChoicesView(FormView):
    """
    Return chained model choices
    the url  is 
        url(r'^options/js/(?P<chained_model_app>[a-zA-Z0-9\_\-]+)/(?P<chained_model_name>[a-zA-Z0-9\_\-]+)/(?P<model_app>[a-zA-Z0-9\_\-]+)/(?P<model_name>[a-zA-Z0-9\_\-]+)', ChainedModelChoicesView.as_view(),name="chained_model_choices")

    Support  two request parameters
    1. archived: support archived status.
        If a model doesn't support archived feature, this feature is ignored.
        If a model supports archived feature, can 
        A. Return all options if request dones not have 'archived' parameter. each option is a dict object with properties "value","display" and "archived"
        B. Return all archived options if request parameter 'archived' is true. each option is a dict object with properties "value" and "display"
        C. Return all non archived options if request parameter 'archived' is not true. each option is a dict object with properties "value" and "display"
    2. other_option or other_options: support other option or other options
        Other option will be returned at the bottom

    Response is a javascript object
    [model_name.lower()]_map = {
        chained_model_object_pk: list of model object with properties "value","display" and "archived" if archived is not present in request and archived feature supported.)
    }


    """
    next_url = "lastDocumentUrl"
    _cache = {}


    def add_option(self,option_map,option,archive_supported,archived):
        if archive_supported and archived is None:
            if option[2] not in option_map:
                option_map[option[2]] = [{"value":option[0],"display":option[1],"archived":option[3]}]
            else:
                option_map[option[2]].append({"value":option[0],"display":option[1],"archived":option[3]})
        else:
            if option[2] not in option_map:
                option_map[option[2]] = [{"value":option[0],"display":option[1]}]
            else:
                option_map[option[2]].append({"value":option[0],"display":option[1]})


    def get(self,request,chained_model_app,chained_model_name,model_app,model_name,*args,**kwargs):
        archived = request.GET.get('archived') or None
        other_option = request.GET.get('other_option') or None

        #get the function to check whether a option is an other option or not
        is_other_option = None
        if other_option:
            casesensitive = "caseinsensitive" not in request.GET
            if casesensitive:
                is_other_option = (lambda other_option:lambda val:(val or "") == other_option)( other_option)
            else:
                is_other_option = (lambda other_option:lambda val:(val or "").lower() == other_option)(other_option.lower())
        else:
            other_options = request.GET.get('other_options')
            if other_options:
                other_options = other_options.split(",")
                casesensitive = "casesensitive" in request.GET
                if casesensitive:
                    if len(other_options == 1):
                        is_other_option = (lambda other_option:lambda val:(val or "") == other_option)( other_options[0])
                    else:
                        is_other_option = (lambda other_options:lambda val:(val or "") in other_options)(other_options)
                else:
                    if len(other_options == 1):
                        is_other_option = (lambda other_option:lambda val:(val or "").lower() == other_option)(other_options[0].lower())
                    else:
                        is_other_option = (lambda other_options:lambda val:(val or "").lower() in other_options)([o.lower() for o in other_options])

        #set archived to None if not present in request, True if arvhived is true with case-insensitive, otherwise False
        if archived is not None:
            archived = archived.lower() in ("true")
        #get the meta function to return the model, archived_supported and an add_opiton fuction to populate the options list.
        if model_name not in self._cache:
            model = get_model(model_app,model_name)
            chained_model = get_model(chained_model_app,chained_model_name)
            get_chained_object = None
            get_model_value = None
            get_model_display = None 
            for field in model._meta.fields:
                if field.primary_key:
                    get_model_value = (lambda name:lambda obj:getattr(obj,name))(field.name)
                elif isinstance(field,models.ForeignKey):
                    if field.related_model == chained_model:
                        get_chained_object = (lambda name:lambda obj:getattr(obj,name))(field.name)
                elif isinstance(field,models.CharField):
                    get_model_display = (lambda name:lambda obj:getattr(obj,name))(field.name)
                elif isinstance(field,models.TextField):
                    if not get_model_display:
                        get_model_display = (lambda name:lambda obj:getattr(obj,name))(field.name)

            if hasattr(model,"display"):
                #has display property
                get_model_display = lambda obj:getattr(obj,"display")

            if not get_model_display:
                get_model_display = lambda obj:str(get_model_value(obj))

            archive_supported = True if (hasattr(chained_model,"archived") or hasattr(model,"archived"))  else False
            def add_option(get_model_value,get_model_display,archive_supported):
                def _add_option(options,obj,archived):
                    is_archived = False
                    chained_object = get_chained_object(obj)
                    if archive_supported:
                        is_archived = getattr(chained_object,"archived") if hasattr(chained_object,"archived") else False
                        if not is_archived:
                            is_archived = getattr(obj,"archived") if hasattr(obj,"archived") else False
                        if archived is None:
                            options.append((get_model_value(obj),get_model_display(obj),getattr(chained_object,"pk"),is_archived))
                        elif archived == is_archived:
                            options.append((get_model_value(obj),get_model_display(obj),getattr(chained_object,"pk")))
                    else:
                        options.append((get_model_value(obj),get_model_display(obj),getattr(chained_object,"pk")))
                return _add_option
            
            self._cache[model_name] = (model,archive_supported,add_option(get_model_value,get_model_display,archive_supported))

        #retrieve all model objects from db and converted them to a list of options
        model,archive_supported,add_option = self._cache[model_name]
        options = []
        for obj in model.objects.all():
            add_option(options,obj,archived)

        #convert the option list to a option list grouped by chained model. and also guarantee the other option will be in the end of the option list 
        option_map = {}
        if is_other_option:
            for option in options:
                if is_other_option(option[1]):
                    continue
                self.add_option(option_map,option,archive_supported,archived)

            for option in options:
                if not is_other_option(option[1]):
                    continue
                self.add_option(option_map,option,archive_supported,archived)
        else:
            for option in options:
                self.add_option(option_map,option,archive_supported,archived)

        #populate the javascipt string to decalre option map.
        #js = "{}_map = {}".format(model_name.lower(),json.dumps(option_map,indent=4))
        js = "{}_map = {}".format(model_name.lower(),json.dumps(option_map))


        return HttpResponse(js,content_type="application/x-javascript")

