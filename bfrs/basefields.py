import md5
import json
import inspect

from django import forms
from django.db import models
from django.dispatch import receiver
from django.core.exceptions import ValidationError

from . import basewidgets
from bfrs_project.signals import webserver_ready

class_id = 0
field_classes = {}

def getallargs(func):
    func_name = func.__name__
    if hasattr(func,"im_class") and getattr(func,"im_class"):
        #is a class method
        cls = func.im_class
        #it is a class method
        argspec = inspect.getargspec(func)
        func_args = []
        #get the args introduced by current method
        if argspec.args and func_name in cls.__dict__:
            for k in argspec.args if type(cls.__dict__[func_name]) == staticmethod else argspec.args[1:]:
                func_args.append(k)

        #get the args and kwargs introduced by parent class
        if argspec.varargs or argspec.keywords:
            for base_cls in cls.__bases__:
                if base_cls != object and hasattr(base_cls,func_name):
                    base_args = getallargs(getattr(base_cls,func_name))
                    if base_args :
                        for k in base_args:
                            if k not in func_args:
                                func_args.append(k)

        return func_args

    return inspect.getargspec(func).args




def hide_field(field):
    if field.widget.attrs:
        if field.widget.attrs.get("style"): 
            field.widget.attrs["style"]  = "{};{}".format(field.widget.attrs["style"],"display:none")
        else:
            field.widget.attrs["style"]  = "display:none"
        field.widget.attrs["disabled"]  = True
    else:
        field.widget.attrs = {"style":"display:none","disabled":True}

class _JSONEncoder(json.JSONEncoder):
    def default(self,obj):
        if isinstance(obj,models.Model):
            return obj.pk
        elif callable(obj) or isinstance(obj,staticmethod):
            return id(obj)
        try:
            return json.JSONEncoder.default(self,obj)
        except:
            return id(obj)

class FieldParametersMixin(object):
    field_params = None

    def __init__(self,*args,**kwargs):
        if self.field_params:
            for k,v in self.field_params.iteritems():
                kwargs[k] = v
        super(FieldParametersMixin,self).__init__(*args,**kwargs)


class AliasFieldMixin(object):
    field_name = None

def AliasFieldFactory(model,field_name,field_class=None,field_params=None):
    global class_id
    field_class = field_class or model._meta.get_field(field_name).formfield().__class__
    if field_params:
        class_key = md5.new("AliasField<{}.{}{}{}{}>".format(model.__module__,model.__name__,field_name,field_class,json.dumps(field_params,cls=_JSONEncoder))).hexdigest()
    else:
        class_key = md5.new("AliasField<{}.{}{}{}>".format(model.__module__,model.__name__,field_name,field_class)).hexdigest()

    if class_key not in field_classes:
        class_id += 1
        class_name = "{}_{}".format(field_class.__name__,class_id)
        if field_params:
            field_classes[class_key] = type(class_name,(FieldParametersMixin,AliasFieldMixin,field_class),{"field_name":field_name,"field_params":field_params})
        else:
            field_classes[class_key] = type(class_name,(AliasFieldMixin,field_class),{"field_name":field_name})
    return field_classes[class_key]

def OverrideFieldFactory(model,field_name,field_class=None,**field_params):
    """
    A factory method to create a field class to override some field parameters
    """
    global class_id

    field_params = field_params or {}
    field_class = field_class or model._meta.get_field(field_name).formfield().__class__
    class_key = md5.new("OverrideField<{}.{}.{}.{}.{}.{}>".format(model.__module__,model.__name__,field_name,field_class.__module__,field_class.__name__,json.dumps(field_params,cls=_JSONEncoder))).hexdigest()
    if class_key not in field_classes:
        class_id += 1
        class_name = "{}_{}".format(field_class.__name__,class_id)
        func_args= getallargs(field_class.__init__)
        extra_fields = {}
        for k,v in field_params.items():
            if k not in func_args:
                extra_fields[k] = v
        if extra_fields:
            for k in extra_fields.keys():
                del field_params[k]
        else:
            extra_fields = None
        field_classes[class_key] = type(class_name,(FieldParametersMixin,field_class),{"field_name":field_name,"field_params":field_params,"extra_fields":extra_fields})
        #print("{}.{}={}".format(field_name,field_classes[class_key],field_classes[class_key].get_layout))
    return field_classes[class_key]


class CompoundField(AliasFieldMixin,FieldParametersMixin):
    field_name = None
    related_field_names = []
    field_mixin = None
    hidden_layout = None
    editmode = None

    def  get_layout(self,f):
        if self.editmode == True:
            return self._edit_layout(f)
        elif isinstance(self.widget,basewidgets.DisplayWidget):
            return self._view_layout(f)
        else:
            return self._edit_layout(f)

    def _view_layout(self,f):
        raise Exception("Not implemented")

    def _edit_layout(self,f):
        raise Exception("Not implemented")

    @classmethod
    def _initialize_class(cls):
        pass

def CompoundFieldFactory(compoundfield_class,model,field_name,related_field_names=None,field_class=None,**kwargs):
    global class_id

    kwargs = kwargs or {}
    if not related_field_names:
        related_field_names = compoundfield_class.related_field_names
    if hasattr(compoundfield_class,"init_kwargs") and callable(compoundfield_class.init_kwargs):
        kwargs = compoundfield_class.init_kwargs(model,field_name,related_field_names,kwargs)

    hidden_layout="{}" * (len(related_field_names) + 1)
    field_class = field_class or model._meta.get_field(field_name).formfield().__class__
    class_key = md5.new("CompoundField<{}.{}.{}{}{}{}>".format(compoundfield_class.__name__,field_class.__module__,field_class.__name__,field_name,json.dumps(related_field_names),json.dumps(kwargs,cls=_JSONEncoder))).hexdigest()
    if class_key not in field_classes:
        class_id += 1
        class_name = "{}_{}".format(field_class.__name__,class_id)
        kwargs.update({"field_name":field_name,"related_field_names":related_field_names,"hidden_layout":hidden_layout})
        field_classes[class_key] = type(class_name,(compoundfield_class,field_class),kwargs)
        #print("{}.{}={}".format(field_name,field_classes[class_key],field_classes[class_key].get_layout))
    return field_classes[class_key]

def SwitchFieldFactory(model,field_name,related_field_names,field_class=None,**kwargs):
    return CompoundFieldFactory(SwitchField,model,field_name,related_field_names,field_class,**kwargs)

def OtherOptionFieldFactory(model,field_name,related_field_names,field_class=None,**kwargs):
    return CompoundFieldFactory(OtherOptionField,model,field_name,related_field_names,field_class,**kwargs)

class ChoiceFieldMixin(object):
    def __init__(self,*args,**kwargs):
        kwargs["choices"] = self.CHOICES
        if "min_value" in kwargs:
            del kwargs["min_value"]
        super(ChoiceFieldMixin,self).__init__(*args,**kwargs)

def ChoiceFieldFactory(choices,choice_class=forms.TypedChoiceField,field_params=None):
    global class_id
    class_key = md5.new("ChoiceField<{}.{}{}{}>".format(choice_class.__module__,choice_class.__name__,json.dumps(choices),json.dumps(field_params,cls=_JSONEncoder))).hexdigest()
    if class_key not in field_classes:
        class_id += 1
        class_name = "{}_{}".format(choice_class.__name__,class_id)
        field_classes[class_key] = type(class_name,(FieldParametersMixin,ChoiceFieldMixin,choice_class),{"CHOICES":choices,"field_params":field_params})
    return field_classes[class_key]


NOT_NONE=1
HAS_DATA=2
ALWAYS=3
DATA_MAP=4
class SwitchField(CompoundField):
    """
    suitable for compound fields which include a boolean primary field and one or more related field or a html section
    normally, when the primary feild is false, all related field will be disabled; when primary field is true, all related field will be enabled

    policy: the policy to view the related field when primary field if false.
    reverse: if reverse is true; the behaviour will be reversed; that means: all related field will be disabled when the primary field is true
    on_layout: the view layout when the primary field is true
    off_layout: the view layout when the primary field is false
    edit_layout: the edit layout
    """
    policy = HAS_DATA
    reverse = False
    on_layout = None
    off_layout = None
    edit_layout = None
    true_value = 'True'

    @classmethod
    def init_kwargs(cls,model,field_name,related_field_names,kwargs):
        if not kwargs.get("on_layout"):
            kwargs["on_layout"] = u"{{}}{}".format("<br>{}" * len(related_field_names))

        if not kwargs.get("off_layout"):
            kwargs["off_layout"] = None

        if not kwargs.get("edit_layout"):
            kwargs["edit_layout"] = u"{{0}}<div id='id_{}_body'>{{1}}{}</div>".format("{{{}}}".format(len(related_field_names) + 1),"".join(["<br>{{{}}}".format(i) for i in range(2,len(related_field_names) + 1)]))

        kwargs["true_value"] = (str(kwargs['true_value']) if kwargs['true_value'] is not None else "" ) if "true_value" in kwargs else 'True'

        return kwargs

    def _view_layout(self,f):
        """
        return a tuple(layout,enable related field list) for view
        """
        val1 = f.value()
        val1_str = str(val1) if val1 is not None else ""
        if (not self.reverse and val1_str == self.true_value) or (self.reverse and not val1_str == self.true_value):
            if self.policy == ALWAYS:
                return (self.off_layout if self.reverse else self.on_layout,f.field.related_field_names)
            else:
                val2 = f.related_fields[0].value()
                if self.policy == NOT_NONE and val2 is not None:
                    return (self.off_layout if self.reverse else self.on_layout,f.field.related_field_names)
                elif self.policy == HAS_DATA and val2:
                    return (self.off_layout if self.reverse else self.on_layout,f.field.related_field_names)
                
        return (self.on_layout if self.reverse else self.off_layout,None)

        
    def _edit_layout(self,f):
        """
        return a tuple(layout,enable related field list) for edit
        """
        val1 = f.value()
        val1_str = str(val1) if val1 is not None else ""
            
        f.field.widget.attrs = f.field.widget.attrs or {}
        show_fields = "$('#id_{}_body').show();{}".format(f.auto_id,";".join(["$('#{0}').prop('disabled',false)".format(field.auto_id) for field in f.related_fields]))
        hide_fields = "$('#id_{}_body').hide();{}".format(f.auto_id,";".join(["$('#{0}').prop('disabled',true)".format(field.auto_id) for field in f.related_fields]))

        if isinstance(f.field.widget,forms.widgets.RadioSelect):
            f.field.widget.attrs["onclick"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(self.true_value),hide_fields if self.reverse else show_fields,show_fields if self.reverse else hide_fields)
        elif isinstance(f.field.widget,forms.widgets.CheckboxInput):
            f.field.widget.attrs["onclick"]="""
                if (this.checked) {{
                    {0}
                }} else {{
                    {1}
                }}
            """.format(hide_fields if self.reverse else show_fields,show_fields if self.reverse else hide_fields)
        elif isinstance(f.field.widget,forms.widgets.Select):
            f.field.widget.attrs["onchange"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(self.true_value),hide_fields if self.reverse else show_fields,show_fields if self.reverse else hide_fields)
        else:
            raise Exception("Not implemented")

        if (not self.reverse and val1_str != self.true_value) or (self.reverse and val1_str == self.true_value):
            return (u"{}<script type='text/javascript'>{}</script>".format(self.edit_layout,hide_fields),f.field.related_field_names)
        else:
            return (self.edit_layout,f.field.related_field_names)
    
class OtherOptionField(CompoundField):
    """
    suitable for compound fields which include a choice primary field with other options and one or more related field

    other_layout: is used when other option is chosen
    layout: is used when other option is not chosen
    edit_layout: is used for editing
    """
    policy = HAS_DATA
    other_layout = None
    layout = None
    edit_layout = None

    is_other_value = None
    is_other_value_js = None
    is_other_option = None

    @classmethod
    def _initialize_other_option(cls,other_option,edit=True):
        if isinstance(other_option,(list,tuple)):
            if len(other_option) == 0:
                other_option = None
            elif len(other_option) == 1:
                other_option = other_option[0]

        is_other_value_js = None
        if other_option is None:
            if edit:
                is_other_value = None
                is_other_value_js = None
            else:
                is_other_value = None
        elif isinstance(other_option,(list,tuple)):
            if edit:
                other_value = [o.id for o in other_option] if hasattr(other_option[0],"id") else other_option
                is_other_value = (lambda other_value:lambda val: val in other_value)(other_value)
                is_other_value_js = (lambda other_value:"['{}'].indexOf(this.value) >= 0".format("','".join([str(o) for o in other_value])))(other_value)
            else:
                is_other_value = (lambda other_value:lambda val: val in other_value)(other_option)
        else:
            if edit:
                other_value = other_option.id if hasattr(other_option,"id") else other_option
                is_other_value = (lambda other_value:lambda val: val == other_value)(other_value)
                is_other_value_js = (lambda other_value:"this.value === '{}'".format(other_value))(other_value)
            else:
                is_other_value = (lambda other_value:lambda val: val == other_value)(other_option)

        return is_other_value,is_other_value_js

    @classmethod
    def _initialize_class(cls):
        if cls.other_option and callable(cls.other_option):
            other_option = cls.other_option()
            if callable(other_option):
                cls.other_option = staticmethod(other_option)
            else:
                cls.other_option = other_option
                is_other_value,is_other_value_js = cls._initialize_other_option(cls.other_option,edit=True)
                is_other_option = cls._initialize_other_option(cls.other_option,edit=False)[0]
                cls.is_other_value = staticmethod(is_other_value) if is_other_value else is_other_value
                cls.is_other_value_js = staticmethod(is_other_value_js) if is_other_value_js else is_other_value_js
                cls.is_other_option = staticmethod(is_other_option) if is_other_option else is_other_option


    @classmethod
    def init_kwargs(cls,model,field_name,related_field_names,kwargs):
        if not kwargs.get("other_option"):
            raise Exception("Missing 'other_option' keyword parameter")
        elif callable(kwargs.get("other_option")):
            kwargs["other_option"] = staticmethod(kwargs["other_option"])

        if not kwargs.get("other_layout"):
            kwargs["other_layout"] = u"{{}}{}".format("<br>{}" * len(related_field_names))

        if not kwargs.get("layout"):
            kwargs["layout"] = None

        if not kwargs.get("edit_layout"):
            kwargs["edit_layout"] = u"{{0}}<div id='id_{}_body'>{{1}}{}</div>".format("{{{}}}".format(len(related_field_names) + 1),"".join(["<br>{{{}}}".format(i) for i in range(2,len(related_field_names) + 1)]))

        return kwargs

    def _view_layout(self,f):
        val1 = f.value()
        if callable(self.other_option):
            try:
                is_other_option = self._initialize_other_option(self.other_option(val1),edit=False)[0]
            except:
                is_other_option = None

        else:
            is_other_option = self.is_other_option

        if not is_other_option:
            return (self.layout,None)

        if is_other_option(val1):
            val2 = f.related_fields[0].value()
            if self.policy == ALWAYS:
                return (self.other_layout,f.field.related_field_names)
            elif self.policy == NOT_NONE and val2 is not None:
                return (self.other_layout,f.field.related_field_names)
            elif self.policy == HAS_DATA and val2:
                return (self.other_layout,f.field.related_field_names)
            elif self.policy == DATA_MAP and val2 in self.other_layout:
                return (self.other_layout[val2],f.field.related_field_names)
                
        return (self.layout,None)

    def _edit_layout(self,f):
        """
        return a tuple(layout,enable related field list) for edit
        """
        val1 = f.value()
        if isinstance(val1,basestring):
            val1 = int(val1) if val1 else None
        #if f.name == "field_officer":
        #    import ipdb;ipdb.set_trace()
        if callable(self.other_option):
            try:
                is_other_value,is_other_value_js = self._initialize_other_option(self.other_option(val1),edit=True)
            except:
                is_other_value = None
                is_other_value_js = None
        else:
            is_other_value = self.is_other_value
            is_other_value_js = self.is_other_value_js

        if is_other_value is None:
            #no other option
            return (u"{}<script type='text/javascript'>{}</script>".format(self.edit_layout,hide_fields),f.field.related_field_names)

        f.field.widget.attrs = f.field.widget.attrs or {}
        show_fields = "$('#id_{}_body').show();{}".format(f.auto_id,";".join(["$('#{0}').prop('disabled',false)".format(field.auto_id) for field in f.related_fields]))
        hide_fields = "$('#id_{}_body').hide();{}".format(f.auto_id,";".join(["$('#{0}').prop('disabled',true)".format(field.auto_id) for field in f.related_fields]))

        if isinstance(f.field.widget,forms.widgets.RadioSelect):
            f.field.widget.attrs["onclick"]="""
                if ({0}) {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(is_other_value_js,show_fields,hide_fields)
        elif isinstance(f.field.widget,forms.widgets.Select):
            f.field.widget.attrs["onchange"]="""
                if ({0}) {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(is_other_value_js,show_fields,hide_fields)
        else:
            raise Exception("Not  implemented")

        if is_other_value(val1):
            return (self.edit_layout,f.field.related_field_names)
        else:
            return (u"{}<script type='text/javascript'>{}</script>".format(self.edit_layout,hide_fields),f.field.related_field_names)


class FileField(forms.FileField):
    """
    content_types: content type list, for example. 'application/pdf', 'image/tiff', 'image/tif', 'image/jpeg', 'image/jpg', 'image/gif', 'image/png','application/zip', 'application/x-zip-compressed',
        help_text='Acceptable file types: pdf, tiff, jpg, gif, png, zip')

    """
    def __init__(self,max_size=None,content_types=None,*args,**kwargs):
        if "error_messages" not in kwargs:
            kwargs["error_messages"] = {}

        if "max_size" not in kwargs["error_messages"]:
            kwargs["error_messages"]["max_size"] = "The uploaded file size is %(max_size)d, which is exceed the maximum file size %(file_size)d."

        if "unsupported_content_type" not in kwargs["error_messages"]:
            kwargs["error_messages"]["unsupported_content_type"] = "The content type(%(file_content_type)s) of the uploaded file is not supported, The Acceptable file types are pdf,tiff,jpg,gif,png and zip."
        super(FileField,self).__init__(*args,**kwargs)
        self.max_size = max_size
        self.content_types = content_types

    def validate(self,value):
        super(FileField,self).validate(value)
        if self.content_types:
            if value.content_type not in self.content_types:
                raise ValidationError(self.error_messages["unsupported_content_type"], code='unsupported_content_type', params={'file_content_type':value.content_type})

        if self.max_size:
            if value.size > self.max_size:
                raise ValidationError(self.error_messages["max_size"], code='max_size', params={'file_size':value.size,'max_size':self.max_size})

@receiver(webserver_ready)
def initialize(sender,**kwargs):
    for cls in field_classes.values():
        if hasattr(cls,"_initialize_class"):
            cls._initialize_class()
