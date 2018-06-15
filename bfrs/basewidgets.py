from django.forms.widgets import Widget
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

hyperlink_classes = {}
def HyperlinkDisplayFactory(url_name,field_name,widget_class,ids=[("id","pk")],baseclass=HyperlinkTextDisplay):
    key = hashlib.md5("{}{}".format(url_name,field_name).encode('utf-8')).hexdigest()
    cls = hyperlink_classes.get(key)
    if not cls:
        cls = type(key,(baseclass,),{"url_name":url_name,"widget_class":widget_class,"ids":ids})
        hyperlink_classes[key] = cls
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





