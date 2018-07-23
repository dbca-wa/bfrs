import md5
import json

from django import forms
from django.db import models

from . import basewidgets

def hide_field(field):
    if field.widget.attrs:
        if field.widget.attrs.get("style"): 
            field.widget.attrs["style"]  = "{};{}".format(field.widget.attrs["style"],"display:none")
        else:
            field.widget.attrs["style"]  = "display:none"
        field.widget.attrs["disabled"]  = True
    else:
        field.widget.attrs = {"style":"display:none","disabled":True}


class CompoundField(object):
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

class _JSONEncoder(json.JSONEncoder):
    def default(self,obj):
        if isinstance(obj,models.Model):
            return obj.pk
        elif callable(obj) or isinstance(obj,staticmethod):
            return id(obj)
        return json.JSONEncoder.default(self,obj)

class_id = 0
class_id = 0
compound_classes = {}
def CompoundFieldFactory(compoundfield_class,model,field_name,related_field_names=None,field_class=None,**kwargs):
    global class_id

    kwargs = kwargs or {}
    if not related_field_names:
        related_field_names = compoundfield_class.related_field_names
    if hasattr(compoundfield_class,"init_kwargs") and callable(compoundfield_class.init_kwargs):
        kwargs = compoundfield_class.init_kwargs(model,field_name,related_field_names,kwargs)

    hidden_layout="{}" * (len(related_field_names) + 1)
    field_class = field_class or model._meta.get_field(field_name).formfield().__class__
    class_key = md5.new("{}.{}.{}{}{}".format(compoundfield_class.__name__,field_class.__module__,field_class.__name__,json.dumps(related_field_names),json.dumps(kwargs,cls=_JSONEncoder))).hexdigest()
    if class_key not in compound_classes:
        class_id += 1
        class_name = "{}_{}".format(field_class.__name__,class_id)
        kwargs.update({"related_field_names":related_field_names,"hidden_layout":hidden_layout})
        compound_classes[class_key] = type(class_name,(compoundfield_class,field_class),kwargs)
        #print("{}.{}={}".format(field_name,compound_classes[class_key],compound_classes[class_key].get_layout))
    return compound_classes[class_key]

def SwitchFieldFactory(model,field_name,related_field_names,field_class=None,**kwargs):
    return CompoundFieldFactory(SwitchField,model,field_name,related_field_names,field_class,**kwargs)

def OtherOptionFieldFactory(model,field_name,related_field_names,field_class=None,**kwargs):
    return CompoundFieldFactory(OtherOptionField,model,field_name,related_field_names,field_class,**kwargs)

choices_classes = {}
class ChoiceFieldMixin(object):
    def __init__(self,*args,**kwargs):
        kwargs["choices"] = self.CHOICES
        if "min_value" in kwargs:
            del kwargs["min_value"]
        super(ChoiceFieldMixin,self).__init__(*args,**kwargs)

def ChoiceFieldFactory(choices,choice_class=forms.ChoiceField):
    global class_id
    class_key = md5.new("{}".format(json.dumps(choices))).hexdigest()
    if class_key not in choices_classes:
        class_id += 1
        class_name = "{}_{}".format(choice_class.__name__,class_id)
        choices_classes[class_key] = type(class_name,(ChoiceFieldMixin,choice_class),{"CHOICES":choices})
    return choices_classes[class_key]


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
            kwargs["on_layout"] = u"{{}}<br>{}".format("{}" * len(related_field_names))

        if not kwargs.get("off_layout"):
            kwargs["off_layout"] = u"{}"

        if not kwargs.get("edit_layout"):
            kwargs["edit_layout"] = u"{{}}<br>{}".format("{}" * len(related_field_names))

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
        if (not self.reverse and val1_str != self.true_value) or (self.reverse and val1_str == self.true_value):
            #print("{}={} true_value={}   reverse={}".format(f.name,val1,self.true_value,self.reverse))
            for rf in f.related_fields:
                hide_field(rf.field)
            
        f.field.widget.attrs = f.field.widget.attrs or {}
        show_fields = ";".join(["$('#{0}').show();$('#{0}').prop('disabled',false)".format(field.auto_id) for field in f.related_fields])
        hide_fields = ";".join(["$('#{0}').hide();$('#{0}').prop('disabled',true)".format(field.auto_id) for field in f.related_fields])

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
    other_option = None

    @classmethod
    def init_kwargs(cls,model,field_name,related_field_names,kwargs):
        if not kwargs.get("other_option"):
            raise Exception("Missing 'other_option' keyword parameter")

        if not kwargs.get("other_layout"):
            kwargs["other_layout"] = u"{{}}<br>{}".format("{}" * len(related_field_names))

        if not kwargs.get("layout"):
            kwargs["layout"] = None

        if not kwargs.get("edit_layout"):
            kwargs["edit_layout"] = u"{{}}<br>{}".format("{}" * len(related_field_names))

        #wraper the related field in a containaer
        kwargs["edit_layout_hide"] = kwargs["edit_layout"].format("{{0}}",*[ "<span id='{{}}_container' style='display:none'>{{{{{}}}}}</span>".format(i) for i in range(1,len(related_field_names) + 1)])
        kwargs["edit_layout"] = kwargs["edit_layout"].format("{{0}}",*[ "<span id='{{}}_container'>{{{{{}}}}}</span>".format(i) for i in range(1,len(related_field_names) + 1)])

        return kwargs

    def _view_layout(self,f):
        val1 = f.value()
        if val1 == self.other_option:
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
        other_value = self.other_option.id if hasattr(self.other_option,"id") else self.other_option
        if val1 != other_value:
            for rf in f.related_fields:
                rf.field.widget.attrs["disabled"]  = True
            edit_layout = self.edit_layout_hide.format(*[field.auto_id for field in f.related_fields])
        else:
            edit_layout = self.edit_layout.format(*[field.auto_id for field in f.related_fields])

        f.field.widget.attrs = f.field.widget.attrs or {}
        show_fields = ";".join(["$('#{0}').show();$('#{1}').prop('disabled',false)".format("{}_container".format(field.auto_id),field.auto_id) for field in f.related_fields])
        hide_fields = ";".join(["$('#{0}').hide();$('#{1}').prop('disabled',true)".format("{}_container".format(field.auto_id),field.auto_id) for field in f.related_fields])

        if isinstance(f.field.widget,forms.widgets.RadioSelect):
            f.field.widget.attrs["onclick"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(other_value),show_fields,hide_fields)
        elif isinstance(f.field.widget,forms.widgets.Select):
            f.field.widget.attrs["onchange"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(other_value),show_fields,hide_fields)
        else:
            raise Exception("Not  implemented")
        return (edit_layout,f.field.related_field_names)
        
    
