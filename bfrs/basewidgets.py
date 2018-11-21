from django import forms
from django.core.cache import caches
from django.urls import reverse
from django.db import models
from django.contrib.auth.models import User
from django.utils import safestring
import hashlib

import utils

to_str = lambda o: "" if o is None else str(o)

class DisplayMixin(forms.Widget):
    pass

class DisplayWidget(DisplayMixin,forms.Widget):
    def __deepcopy__(self, memo):
        return self

class TextDisplay(DisplayWidget):
    def render(self,name,value,attrs=None,renderer=None):
        return to_str(value)

class FinancialYearDisplay(DisplayWidget):
    def render(self,name,value,attrs=None,renderer=None):
        value = int(value)
        return "{}/{}".format(value,value+1)

class DmsCoordinateDisplay(DisplayWidget):
    def render(self,name,value,attrs=None,renderer=None):
        if value:
            return utils.dms_coordinate(value)
        else:
            return ""

class DatetimeDisplay(DisplayWidget):
    def __init__(self,date_format="%d/%m/%Y %H:%M:%S"):
        super(DatetimeDisplay,self).__init__()
        self.date_format = date_format or "%d/%m/%Y %H:%M:%S"

    def render(self,name,value,attrs=None,renderer=None):
        if value:
            return value.strftime(self.date_format)
        else:
            return ""

class HyperlinkTextDisplay(DisplayWidget):
    def __init__(self,**kwargs):
        super(HyperlinkTextDisplay,self).__init__(**kwargs)
        self.widget = self.widget_class(**kwargs)

    def value_from_datadict(self,data,files,name):
        result = []
        for f in self.ids:
            val = data.get(f[0])
            if val is None:
                result.clear()
                break
            elif isinstance(val,models.Model):
                result.append(val.pk)
            else:
                result.append(val)
        result.append(self.widget.value_from_datadict(data,files,name))
        return result

    def render(self,name,value,attrs=None,renderer=None):
        if value:
            link = self.hyperlink(value[0:-1])
            if link:
                return "<a href='{}'>{}</a>".format(link,self.widget.render(name,value[-1],attrs,renderer)) if value else ""
            else:
                return self.widget.render(name,value[-1],attrs,renderer)
        else:
            return ""

    def hyperlink(self,pks):
        if len(pks) == 0:
            return None
        else:
            kwargs = {}
            index = 0
            while index < len(pks):
                kwargs[self.ids[index][1]] = pks[index]
                index += 1
            return reverse(self.url_name,kwargs=kwargs)

widget_classes = {}
widget_class_id = 0
def HyperlinkDisplayFactory(url_name,field_name,widget_class,ids=[("id","pk")],baseclass=HyperlinkTextDisplay):
    global widget_class_id
    key = hashlib.md5("{}{}{}".format(baseclass.__name__,url_name,field_name).encode('utf-8')).hexdigest()
    cls = widget_classes.get(key)
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(baseclass.__name,widget_class_id)
        cls = type(class_name,(baseclass,),{"url_name":url_name,"widget_class":widget_class,"ids":ids})
        widget_classes[key] = cls
    return cls



class BooleanDisplay(DisplayWidget):
    def __init__(self,html_true="Yes",html_false="No",include_html_tag=False,true_value=True):
        super(BooleanDisplay,self).__init__()
        if include_html_tag:
            self.html_true = safestring.SafeText(html_true)
            self.html_false = safestring.SafeText(html_false)
        else:
            self.html_true = html_true
            self.html_false = html_false
        self.true_value = true_value

    def render(self,name,value,attrs=None,renderer=None):
        if value is None:
            return ""
        elif value == self.true_value:
            return self.html_true
        else:
            return self.html_false

    

class TemplateDisplay(DisplayWidget):
    def __init__(self,widget,template):
        super(TemplateDisplay,self).__init__()
        self.template = template
        self.widget = widget

    def render(self,name,value,attrs=None,renderer=None):
        if not self.template or not value:
            return self.widget.render(name,value,attrs,renderer)
        return safestring.SafeText(self.template.format(self.widget.render(name,value,attrs,renderer)))


class DatetimeInput(forms.TextInput):
    def render(self,name,value,attrs=None,renderer=None):
        html = super(DatetimeInput,self).render(name,value,attrs)
        datetime_picker = """
        <script type="text/javascript">
            $("#{}").datetimepicker({{ 
                format: "Y-m-d H:i" ,
                maxDate:true,
                step: 30,
            }}); 
        </script>
        """.format(attrs["id"])
        return safestring.SafeText("{}{}".format(html,datetime_picker))


class TemplateWidgetMixin(object):
    template = ""

    def render(self,name,value,attrs=None,renderer=None):
        widget_html = super(TemplateWidgetMixin,self).render(name,value,attrs)
        return safestring.SafeText(self.template.format(widget_html))


def TemplateWidgetFactory(widget_class,template):
    global widget_class_id
    key = hashlib.md5("{}{}{}".format(widget_class.__name__,TemplateWidgetMixin.__name__,template).encode('utf-8')).hexdigest()
    cls = widget_classes.get(key)
    if not cls:
        widget_class_id += 1
        class_name = "{}_template_{}".format(widget_class.__name__,widget_class_id)
        cls = type(class_name,(TemplateWidgetMixin,widget_class),{"template":template})
        widget_classes[key] = cls
    return cls


class SwitchWidgetMixin(object):
    html = ""
    switch_template = ""
    true_value = True
    reverse = False
    html_id = None

    def render(self,name,value,attrs=None,renderer=None):
        value_str = str(value) if value is not None else ""
        if not self.html_id:
            html_id = "{}_related_html".format( attrs.get("id"))
            wrapped_html = "<span id='{}' {} >{}</span>".format(html_id,"style='display:none'" if (not self.reverse and value_str != self.true_value) or (self.reverse and value_str == self.true_value) else "" ,self.html)
        else:
            html_id = self.html_id
            if (not self.reverse and value_str == self.true_value) or (self.reverse and value_str != self.true_value):
                wrapped_html = ""
            else:
                wrapped_html = """
                <script type="text/javascript">
                $(document).ready(function() {{
                    $('#{}').hide()
                }})
                </script>
                """.format(html_id)
        
        show_html = "$('#{0}').show();".format(html_id)
        hide_html = "$('#{0}').hide();".format(html_id)

        attrs = attrs or {}
        if isinstance(self,forms.RadioSelect):
            attrs["onclick"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(self.true_value,hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
        elif isinstance(self,forms.CheckboxInput):
            attrs["onclick"]="""
                if (this.checked) {{
                    {0}
                }} else {{
                    {1}
                }}
            """.format(hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
        elif isinstance(self,forms.Select):
            attrs["onchange"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(self.true_value,hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
        else:
            raise Exception("Not implemented")

        widget_html = super(SwitchWidgetMixin,self).render(name,value,attrs)
        return safestring.SafeText(self.switch_template.format(widget_html,wrapped_html))

def SwitchWidgetFactory(widget_class,html=None,true_value=True,template="{0}<br>{1}",html_id=None,reverse=False):
    global widget_class_id
    if html_id:
        template="""{0}
        {1}
        """
    key = hashlib.md5("{}{}{}{}{}{}".format(widget_class.__name__,true_value,template,html,html_id,reverse).encode('utf-8')).hexdigest()
    cls = widget_classes.get(key)
    true_value = str(true_value) if true_value is not None else ""
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(widget_class.__name__,widget_class_id)
        cls = type(class_name,(SwitchWidgetMixin,widget_class),{"switch_template":template,"true_value":true_value,"html":html,"reverse":reverse,"html_id":html_id})
        widget_classes[key] = cls
    return cls

class ChoiceDisplay(DisplayWidget):
    choices = None
    def __init__(self,choices=None,**kwargs):
        super(ChoiceDisplay,self).__init__(**kwargs)
        if not self.choices:
            #class object has not a choices,use the passed in choices
            if isinstance(choices,list) or isinstance(choices,tuple):
                self.choices = dict(choices)
            elif isinstance(choices,dict):
                self.choices = choices
            else:
                raise Exception("Choices must be a dictionary or can be converted to a  dictionary.")
            
    def render(self,name,value,attrs=None,renderer=None):
        if self.__class__.choices:
            return self.__class__.choices.get(value,value)
        elif isinstance(self.choices,dict):
            return self.choices.get(value,value)
        else:
            for choice in self.choices:
                if choice[0] == value:
                    return choice[1]

            return value


def ChoiceWidgetFactory(name,choices):
    global widget_class_id
    widget_class = ChoiceDisplay
    if isinstance(choices,list) or isinstance(choices,tuple):
        choices = dict(choices)
    elif isinstance(choices,dict):
        choices = choices
    else:
        raise Exception("Choices must be a dictionary or can be converted to a  dictionary.")

    key = hashlib.md5("{}{}".format(widget_class.__name__,name).encode('utf-8')).hexdigest()
    cls = widget_classes.get(key)
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(widget_class.__name__,name)
        cls = type(class_name,(widget_class,),{"choices":choices})
        widget_classes[key] = cls
    return cls

html_id_seq = 0
class SelectableSelect(forms.Select):
    def __init__(self,**kwargs):
        if kwargs.get("attrs"):
            if kwargs["attrs"].get("class"):
                kwargs["attrs"]["class"] = "{} selectpicker dropup".format(kwargs["attrs"]["class"])
            else:
                kwargs["attrs"]["class"] = "selectpicker dropup"
        else:
            kwargs["attrs"] = {"class":"selectpicker dropup"}
        super(SelectableSelect,self).__init__(**kwargs)


    def render(self,name,value,attrs=None,renderer=None):
        global html_id_seq
        html_id = attrs.get("id",None) if attrs else None
        if not html_id:
            html_id_seq += 1
            html_id = "auto_id_{}".format(html_id_seq)
            if attrs is None:
                attrs = {"id":html_id}
            else:
                attrs["id"] = html_id

        html = super(SelectableSelect,self).render(name,value,attrs)


        return safestring.SafeText(u"""
        {}
        <script type="text/javascript">
            $("#{}").selectpicker({{
              style: 'btn-default',
              size: 6,
              liveSearch: true,
              dropupAuto: false,
              closeOnDateSelect: true,
            }});
        </script>
        """.format(html,html_id))

def ChoiceFieldRendererFactory(outer_html = None,inner_html = None,layout = None,renderer_class=forms.widgets.CheckboxFieldRenderer):
    """
    layout: none, horizontal,vertical
    outer_html: used if layout is None
    inner_html:used in layout is None
    """
    global widget_class_id

    if layout == "vertical":
        outer_html = '<ul{id_attr} style="padding:0px;margin:0px">{content}</ul>'
        inner_html = '<li style="list-style-type:none;padding:0px 15px 0px 0px;">{choice_value}{sub_widgets}</li>'
    else :
        outer_html = '<ul{id_attr} style="padding:0px;margin:0px">{content}</ul>'
        inner_html = '<li style="list-style-type:none;padding:0px 15px 0px 0px;display:inline;">{choice_value}{sub_widgets}</li>'

    key = hashlib.md5("ChoiceFieldRenderer<{}.{}{}{}>".format(renderer_class.__module__,renderer_class.__name__,outer_html,inner_html)).hexdigest()
    cls = widget_classes.get(key)
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(renderer_class.__name__,widget_class_id)
        cls = type(class_name,(renderer_class,),{"outer_html":outer_html,"inner_html":inner_html})
        widget_classes[key] = cls
    return cls


def DisplayWidgetFactory(widget_class):
    """
    Use other widget as display widget.
    """
    global widget_class_id

    key = hashlib.md5("DisplayWidget<{}>".format(widget_class.__module__,widget_class.__name__)).hexdigest()
    cls = widget_classes.get(key)
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(widget_class.__name__,widget_class_id)
        cls = type(class_name,(DisplayMixin,widget_class),{})
        widget_classes[key] = cls
    return cls


