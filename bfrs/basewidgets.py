from django.forms.widgets import Widget,TextInput,Select,RadioSelect,CheckboxInput
from django.core.cache import caches
from django.urls import reverse
from django.db import models
from django.contrib.auth.models import User
from django.utils import safestring
import hashlib

import utils

to_str = lambda o: "" if o is None else str(o)

class DisplayWidget(Widget):
    pass

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

class BooleanDisplay(DisplayWidget):
    def render(self,name,value,attrs=None,renderer=None):
        if value is None:
            return ""
        elif value:
            return "<img src='/static/img/icon-yes.svg' alt='True'>"
        else:
            return "<img src='/static/img/icon-no.svg' alt='True'>"

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
    def __init__(self,html_true="Yes",html_false="No",include_html_tag=False):
        super(BooleanDisplay,self).__init__()
        if include_html_tag:
            self.html_true = safestring.SafeText(html_true)
            self.html_false = safestring.SafeText(html_false)
        else:
            self.html_true = html_true
            self.html_false = html_false

    def render(self,name,value,attrs=None,renderer=None):
        if value is None:
            return ""
        elif value:
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


class DatetimeInput(TextInput):
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
        if not self.html_id:
            html_id = "{}_related_html".format( attrs.get("id"))
            wrapped_html = "<span id='{}' {} >{}</span>".format(html_id,"style='display:none'" if (not self.reverse and value != self.true_value) or (self.reverse and value == self.true_value) else "" ,self.html)
        else:
            html_id = self.html_id
            if (not self.reverse and value == self.true_value) or (self.reverse and value != self.true_value):
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
        if isinstance(self,RadioSelect):
            attrs["onclick"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(self.true_value),hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
        elif isinstance(self,CheckboxInput):
            attrs["onclick"]="""
                if (this.checked) {{
                    {0}
                }} else {{
                    {1}
                }}
            """.format(hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
        elif isinstance(self,Select):
            attrs["onchange"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(self.true_value),hide_html if self.reverse else show_html,show_html if self.reverse else hide_html)
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
    if not cls:
        widget_class_id += 1
        class_name = "{}_{}".format(widget_class.__name__,widget_class_id)
        cls = type(class_name,(SwitchWidgetMixin,widget_class),{"switch_template":template,"true_value":true_value,"html":html,"reverse":reverse,"html_id":html_id})
        widget_classes[key] = cls
    return cls
