import md5
import json

from django import forms

def hide_field(field):
    if field.widget.attrs:
        if field.widget.attrs.get("style"): 
            field.widget.attrs["style"]  = "{};{}".format(field.widget.attrs["style"],"display:none")
        else:
            field.widget.attrs["style"]  = "display:none"
    else:
        field.widget.attrs = {"style":"display:none"}


class CompoundField(object):
    related_field_names = []
    html_layout=None
    hidden_layout=None

class_id = 0
compound_classes = {}
def CompoundFieldFactory(model,field_name,related_field_names,html_layout=None,field_class=None):
    global class_id
    if not html_layout:
        html_layout="{}" * (len(related_field_names) + 1)
    elif callable(html_layout):
        html_layout = staticmethod(html_layout)

    hidden_layout="{}" * (len(related_field_names) + 1)
    field_class = field_class or model._meta.get_field(field_name).formfield().__class__
    class_key = md5.new("{}.{}{}{}".format(field_class.__module__,field_class.__name__,json.dumps(related_field_names),id(html_layout) if callable(html_layout) else html_layout)).hexdigest()
    if class_key not in compound_classes:
        class_id += 1
        class_name = "{}_{}".format(field_class.__name__,class_id)
        compound_classes[class_key] = type(class_name,(CompoundField,field_class),{"related_field_names":related_field_names,"hidden_layout":hidden_layout,"html_layout":html_layout})
    return compound_classes[class_key]

choices_classes = {}
class ChoiceFieldMixin(object):
    def __init__(self,*args,**kwargs):
        kwargs["choices"] = self.CHOICES
        super(ChoiceFieldMixin,self).__init__(*args,**kwargs)
def ChoiceFieldFactory(choices,choice_class=forms.ChoiceField):
    global class_id
    class_key = md5.new("{}".format(json.dumps(choices))).hexdigest()
    if class_key not in choices_classes:
        class_id += 1
        class_name = "{}_{}".format(choice_class.__name__,class_id)
        choices_classes[class_key] = type(class_name,(ChoiceFieldMixin,choice_class),{"CHOICES":choices})
    return choices_classes[class_key]


