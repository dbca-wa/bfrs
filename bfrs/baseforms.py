from collections import OrderedDict

from django.utils.encoding import python_2_unicode_compatible
from django.utils.html import html_safe
from django.utils import six
from django import forms
from django.db import models
from django.template.defaultfilters import safe
from django.utils import safestring

from . import basewidgets
from . import basefields

class ConfigDict(dict):
    def __init__(self,dict_obj,all_key=None):
        super(ConfigDict,self).__init__()
        self.data = dict_obj
        self.all_key = all_key

    def __contains__(self,name):
        return name in self.data or (self.all_key and self.all_key in self.data)

    def __getitem__(self,name):
        try:
            return self.data[name]
        except:
            if self.all_key and self.all_key in self.data:
                return self.data[self.all_key]
            raise

    def __len__(self):
        return len(self.data) if self.data else 0

    def __str__(self):
        return str(self.data)

    def __repr__(self):
        return repr(self.data)

    def get(self,name,default=None):
        return self.data.get(name,self.data.get(self.all_key,default) if self.all_key else default)

class ChainDict(dict):
    def __init__(self,dict_objs):
        super(ConfigDict,self).__init__()
        if isinstance(self.dicts,list):
            self.dicts = dict_objs
        elif isinstance(self.dicts,tuple):
            self.dicts = list(dict_objs)
        elif isinstance(self.dicts,dict):
            self.dicts = [dict_objs] 
        else:
            self.dicts = [dict(dict_objs)] 

        self.all_key = all_key

    def __contains__(self,name):
        for d in self.dicts:
            if name in d:
                return True 
        return False

    def __getitem__(self,name):
        for d in self.dicts:
            try:
                return d[name]
            except:
                continue

        raise KeyError(name)

    def __len__(self):
        """
        return 1 if has value;otherwise return 0
        """
        for d in self.dicts:
            if d:
                return 1 
                
        return 0

    def __str__(self):
        return [str(d) for d in self.dicts]

    def __repr__(self):
        return [repr(d) for d in self.dicts]

    def get(self,name,default=None):
        for d in self.dicts:
            try:
                return d[name]
            except:
                continue

        return default

    def update(self,dict_obj):
        self.dicts.insert(0,dict_obj)


class BoundField(forms.boundfield.BoundField):
    """ 
    Extend django's BoundField to support the following features
    1. Get extra css_classes from field's attribute 'css_classes'
    """
    def css_classes(self, extra_classes=None):
        if hasattr(self.field,"css_classes"):
            if extra_classes:
                if hasattr(extra_classes, 'split'):
                    extra_classes = extra_classes.split()
                extra_classes += getattr(self.field,"css_classes")
                return super(BoundField,self).css_classes(extra_classes)
            else:
                return super(BoundField,self).css_classes(getattr(self.field,"css_classes"))
        else:
            return super(BoundField,self).css_classes(extra_classes)

    @property
    def is_display(self):
        return isinstance(self.field.widget,basewidgets.DisplayWidget)

    @property
    def initial(self):
        data = self.form.initial.get(self.name, self.field.initial)
        if callable(data):
            if self._initial_value is not UNSET:
                data = self._initial_value
            else:
                data = data()
                # If this is an auto-generated default date, nix the
                # microseconds for standardized handling. See #22502.
                if (isinstance(data, (datetime.datetime, datetime.time)) and
                        not self.field.widget.supports_microseconds):
                    data = data.replace(microsecond=0)
                self._initial_value = data
        elif not self.is_display and isinstance(data,models.Model):
            return data.pk
        return data

    @property
    def auto_id(self):
        if self.is_display:
            return ""
        else:
            return super(BoundField,self).auto_id

    def value(self):
        """
        Returns the value for this BoundField, using the initial value if
        the form is not bound or the data otherwise.
        """
        if not self.form.is_bound:
            data = self.initial
        else:
            data = self.field.bound_data(
                self.data, self.form.initial.get(self.name, self.field.initial)
            )
        if isinstance(data,models.Model) and self.is_display:
            return data
        else:
            return self.field.prepare_value(data)

@html_safe
@python_2_unicode_compatible
class CompoundBoundField(BoundField):
    "A Field plus data"
    def __init__(self, form, field, name):
        super(CompoundBoundField,self).__init__(form,field,name)
        self.related_fields = [self.form[name] for name in field.related_field_names]

    def __str__(self):
        """Renders this field as an HTML widget."""
        if self.field.show_hidden_initial:
            return self.as_widget() + self.as_hidden(only_initial=True)
        return self.as_widget()

    def __iter__(self):
        """
        Yields rendered strings that comprise all widgets in this BoundField.

        This really is only useful for RadioSelect widgets, so that you can
        iterate over individual radio buttons in a template.
        """
        id_ = self.field.widget.attrs.get('id') or self.auto_id
        attrs = {'id': id_} if id_ else {}
        attrs = self.build_widget_attrs(attrs)
        for subwidget in self.field.widget.subwidgets(self.html_name, self.value(), attrs):
            yield subwidget

    def __len__(self):
        return len(list(self.__iter__()))

    def __getitem__(self, idx):
        # Prevent unnecessary reevaluation when accessing BoundField's attrs
        # from templates.
        if not isinstance(idx, six.integer_types + (slice,)):
            raise TypeError
        return list(self.__iter__())[idx]

    @property
    def errors(self):
        """
        Returns an ErrorList for this field. Returns an empty ErrorList
        if there are none.
        """
        errors = self.form.errors.get(self.name, self.form.error_class())
        for field in self.related_fields:
            for err in field.errors:
                errors.append(err)
        return errors

    def as_widget(self, widget=None, attrs=None, only_initial=False):
        """
        Renders the field by rendering the passed widget, adding any HTML
        attributes passed as attrs.  If no widget is specified, then the
        field's default widget will be used.
        """
        if self.name == "cause":
            #import ipdb;ipdb.set_trace()
            pass
        html = super(CompoundBoundField,self).as_widget(widget,attrs,only_initial)
        if callable(self.field.html_layout):
            html_layout,field_names = self.field.html_layout(self)
            html = super(CompoundBoundField,self).as_widget(widget,attrs,only_initial)
            if field_names:
                return safestring.SafeText(html_layout.format(html,*[f.as_widget(only_initial=only_initial) for f in self.related_fields if f.name in field_names]))
            else:
                return html
        else:
            html = super(CompoundBoundField,self).as_widget(widget,attrs,only_initial)
            return safestring.SafeText(self.field.html_layout.format(html,*[f.as_widget(only_initial=only_initial) for f in self.related_fields]))

    def as_text(self, attrs=None, **kwargs):
        """
        Returns a string of HTML for representing this as an <input type="text">.
        """
        raise Exception("Not supported")

    def as_textarea(self, attrs=None, **kwargs):
        "Returns a string of HTML for representing this as a <textarea>."
        raise Exception("Not supported")

    def as_hidden(self, attrs=None, **kwargs):
        """
        Returns a string of HTML for representing this as an <input type="hidden">.
        """
        html = super(CompoundBoundField,self).as_widget(self.field.hidden_widget(), attrs, **kwargs)
        return self.field.hidden_layout.format(html,*[f.as_widget(f.field.hidden_widget(),None,**kwargs) for f in self.related_fields])

class BaseModelFormMetaclass(forms.models.ModelFormMetaclass):
    """
    Extend django's ModelFormMetaclass to support the following features
    1. other_fields to enable readonly and property field
    2. ordered_fields to support sort fields
    """
 
    @staticmethod
    def meta_item_from_base(bases,name):
        for b in bases:
            if hasattr(b, 'Meta') and hasattr(b.Meta, name):
                return getattr(b.Meta,name)
        return None

    def __new__(mcs, name, bases, attrs):
        base_formfield_callback = None
        #inheritence some configuration from super class
        if 'Meta' in attrs and not hasattr(attrs['Meta'],'exclude') and not hasattr(attrs["Meta"],"fields"):
            config = BaseModelFormMetaclass.meta_item_from_base(bases,'exclude')
            if config:
                setattr(attrs["Meta"],"exclude",config)
            config = BaseModelFormMetaclass.meta_item_from_base(bases,'fields')
            if config:
                setattr(attrs["Meta"],"fields",config)

        for item in ("other_fields","editable_fields","ordered_fields"):
            if 'Meta' in attrs and not hasattr(attrs['Meta'],item):
                config = BaseModelFormMetaclass.meta_item_from_base(bases,item)
                if config:
                    setattr(attrs["Meta"],item,config)

        for item in ("formfield_callback",):
            if 'Meta' in attrs and not hasattr(attrs['Meta'],item):
                config = BaseModelFormMetaclass.meta_item_from_base(bases,item)
                if config:
                    setattr(attrs["Meta"],item,staticmethod(config))


        for item in ("labels","field_classes","widgets"):
            if 'Meta' in attrs:
                config = BaseModelFormMetaclass.meta_item_from_base(bases,item)
                if config:
                    if hasattr(attrs['Meta'],item):
                        config = dict(config.data if isinstance(config,ConfigDict) else config)
                        config.update(getattr(attrs['Meta'],item))
                        setattr(attrs['Meta'],item,config)
                    else:
                        setattr(attrs['Meta'],item,config.data if isinstance(config,ConfigDict) else config)

        #add "__all__" support in configuration
        if 'Meta' in attrs and hasattr(attrs['Meta'],'widgets'):
            #add "__all__" support in widgets configuration
            attrs['Meta'].widgets = ConfigDict(attrs['Meta'].widgets,all_key="__all__")
    

        new_class = super(BaseModelFormMetaclass, mcs).__new__(mcs, name, bases, attrs)
        meta = getattr(new_class,"Meta") if hasattr(new_class,"Meta") else None
        opts = getattr(new_class,"_meta") if hasattr(new_class,"_meta") else None
        if not opts or not meta or not meta.model:
            return new_class


        for item in ("other_fields","editable_fields","ordered_fields"):
            if not hasattr(opts,item):
                setattr(opts,item,None)

        if hasattr(opts,"field_classes") and opts.field_classes:
            opts.field_classes = ConfigDict(opts.field_classes,all_key="__all__")

        formfield_callback = meta.formfield_callback if meta and hasattr(meta,"formfield_callback") else None

        model = opts.model
        model_field = None
        field_list = []
        kwargs = {}
        db_field = True
    
        for field_name in opts.other_fields or []:
            try:
                model_field = model._meta.get_field(field_name)
                db_field = True
            except:
                #not a model field, check whether it is a property 
                if hasattr(model,field_name) and isinstance(getattr(model,field_name),property):
                    #field is a property
                    model_field = getattr(model,field_name)
                    db_field = False
                else:
                    raise Exception("Unknown field {} ".format(field_name))

            kwargs.clear()
            if opts.widgets and field_name in opts.widgets:
                kwargs['widget'] = opts.widgets[field_name]
            elif not db_field:
                raise Exception("Please cofigure widget for property '{}' in 'widgets' option".format(field_name))

            if opts.localized_fields == forms.models.ALL_FIELDS or (opts.localized_fields and field_name in opts.localized_fields):
                kwargs['localize'] = True

            if opts.labels and field_name in opts.labels:
                kwargs['label'] = safe(opts.labels[field_name])
            elif not db_field:
                raise Exception("Please cofigure label for property '{}' in 'labels' option".format(field_name))

            if opts.help_texts and field_name in opts.help_texts:
                kwargs['help_text'] = opts.help_texts[field_name]

            if opts.error_messages and field_name in opts.error_messages:
                kwargs['error_messages'] = opts.error_messages[field_name]

            if hasattr(opts,"field_classes")  and opts.field_classes and field_name in opts.field_classes:
                kwargs['form_class'] = opts.field_classes[field_name]
            elif not db_field :
                raise Exception("Please cofigure form field for property '{}' in 'field_classes' option".format(field_name))

            if formfield_callback is None:
                if db_field:
                    formfield = model_field.formfield(**kwargs)
                else:
                    formfield = kwargs.pop('form_class')(**kwargs)
            elif not callable(formfield_callback):
                raise TypeError('formfield_callback must be a function or callable')
            else:
                formfield = formfield_callback(model_field, **kwargs)

            field_list.append((field_name, formfield))

        if field_list:
            field_list = OrderedDict(field_list)
            new_class.base_fields.update(field_list)

        if hasattr(new_class,"all_base_fields"):
            new_class.all_base_fields.update(new_class.base_fields)
        else:
            new_class.all_base_fields = new_class.base_fields

        if opts.ordered_fields:
            new_class.base_fields = OrderedDict()
            for field in ordered_fields:
                if field in new_class.all_base_fields:
                    new_class.base_fields[field] = new_class.all_base_fields[field]

        return new_class

class ModelForm(six.with_metaclass(BaseModelFormMetaclass, forms.models.BaseModelForm)):
    def __init__(self, *args,**kwargs):
        instance = None
        if "instance" in kwargs:
            instance = kwargs["instance"]
            kwargs["instance"] = None

        super(ModelForm,self).__init__(*args,**kwargs)
        if instance:
            self.instance = instance
            if self.initial:
                self.initial = ChainDict([self.initial,self.instance])
            else:
                self.initial = self.instance

    def full_clean(self):
        if self._meta.editable_fields is None:
            super(self,ModelForm).full_clean()
        import ipdb;ipdb.set_trace()    
        opt_fields = self._meta.fields
        fields = self.fields
        try:
            self._meta.fields = self._meta.editable_fields
            self.editable_fields = self.editable_fields if hasattr(self,'editable_fields') else [f for f in self.fields if f.name in self._meta.fields]
            self.fields = self.editalbe_fields
            super(self,ModelForm).full_clean()
        finally:
            self._meta.fields = opt_fields
            self.fields = fields

    def __getitem__(self, name):
        """Return a BoundField with the given name."""
        try:
            field = self.fields[name]
        except KeyError:
            raise KeyError(
                "Key '%s' not found in '%s'. Choices are: %s." % (
                    name,
                    self.__class__.__name__,
                    ', '.join(sorted(f for f in self.fields)),
                )
            )
        if name not in self._bound_fields_cache:
            if isinstance(field,basefields.CompoundField):
                self._bound_fields_cache[name] = CompoundBoundField(self,field,name)
            else:
                self._bound_fields_cache[name] = BoundField(self,field,name)
        return self._bound_fields_cache[name]
    
    class Meta:
        @staticmethod
        def formfield_callback(field,**kwargs):
            if isinstance(field,models.Field):
                form_class = kwargs.get("form_class")
                if form_class:
                    kwargs["choices_form_class"] = form_class
                result = field.formfield(**kwargs)
                if form_class and not isinstance(result,form_class):
                    raise Exception("'{}' don't use the form class '{}' declared in field_classes".format(field.__class__.__name__,form_class.__name__))
            else:
                result = kwargs.pop("form_class")(**kwargs)

            return result
            

