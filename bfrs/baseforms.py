from collections import OrderedDict

from django.utils.encoding import python_2_unicode_compatible
from django.utils.html import html_safe
from django.db import transaction
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
        if name in self.data:
            return False if self.data[name] is None else True
        else:
            return self.all_key and self.all_key in self.data

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

class SubpropertyEnabledDict(dict):
    def __init__(self,dict_obj):
        super(SubpropertyEnabledDict,self).__init__()
        self.data = dict_obj

    def __contains__(self,name):
        if not self.data: return False

        pos = name.find(".")
        if pos >= 0:
            name = name[0:pos]

        return name in self.data

    def __getitem__(self,name):
        if self.data is None: raise TypeError("dict is None")

        pos = name.find(".")
        if pos >= 0:
            names = name.split(".")
            result = self.data
            for key in names:
                if not result: raise KeyError(name)
                try:
                    result = result[key]
                except KeyError as ex:
                    raise KeyError(name)

            return result
        else:
            return self.data[name]

    def __setitem__(self,name,value):
        if self.data is None: raise TypeError("dict is None")

        pos = name.find(".")
        if pos >= 0:
            names = name.split(".")
            result = self.data
            for key in names[0:-1]:
                try:
                    result = result[key]
                except KeyError as ex:
                    #key does not exist, create one
                    result[key] = {}
                    result = result[key]

            result[names[-1]] = value
        else:
            self.data[name] = value

    def __len__(self):
        return len(self.data) if self.data else 0

    def __str__(self):
        return str(self.data)

    def __repr__(self):
        return repr(self.data)

    def get(self,name,default=None):
        try:
            return self.__getitem__(name)
        except KeyError as ex:
            return default

class ChainDict(dict):
    def __init__(self,dict_objs):
        super(ChainDict,self).__init__()
        if isinstance(self.dicts,list):
            self.dicts = dict_objs
        elif isinstance(self.dicts,tuple):
            self.dicts = list(dict_objs)
        elif isinstance(self.dicts,dict):
            self.dicts = [dict_objs] 
        else:
            self.dicts = [dict(dict_objs)] 

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
            html_id = super(BoundField,self).auto_id
            if "." in html_id:
                return html_id.replace(".","_")
            else:
                return html_id

    def value(self):
        """
        Returns the value for this BoundField, using the initial value if
        the form is not bound or the data otherwise.
        """
        if not self.form.is_bound or isinstance(self.field.widget,basewidgets.DisplayWidget) or self.field.widget.attrs.get("disabled"):
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

    def as_widget(self, widget=None, attrs=None, only_initial=False):
        """
        Renders the field by rendering the passed widget, adding any HTML
        attributes passed as attrs.  If no widget is specified, then the
        field's default widget will be used.
        """
        html_layout,field_names = self.field.get_layout(self)
        html = super(CompoundBoundField,self).as_widget(widget,attrs,only_initial)
        if field_names:
            args = [f.as_widget(only_initial=only_initial) for f in self.related_fields if f.name in field_names]
            args.append(self.auto_id)
            return safestring.SafeText(html_layout.format(html,*args))
        elif html_layout:
            return safestring.SafeText(html_layout.format(html,self.auto_id))
        else:
            return html

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

        for item in ("other_fields","extra_update_fields","ordered_fields"):
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


        for item in ("other_fields","extra_update_fields","ordered_fields"):
            if hasattr(meta,item) :
                setattr(opts,item,getattr(meta,item))
            else:
                setattr(opts,item,None)

        if hasattr(opts,"field_classes") and opts.field_classes:
            opts.field_classes = ConfigDict(opts.field_classes,all_key="__all__")

        formfield_callback = meta.formfield_callback if meta and hasattr(meta,"formfield_callback") else None

        model = opts.model
        model_field = None
        field_list = []
        kwargs = {}
        db_field = True
        property_name = None
        subproperty_enabled = False
        
        for field_name in opts.other_fields or []:
            if "." in field_name:
                property_name = field_name.split(".",1)[0]
                subproperty_enabled = True
            else:
                property_name = field_name
            try:
                if field_name != property_name:
                    raise Exception("Not a model field")
                model_field = model._meta.get_field(field_name)
                db_field = True
            except:
                #not a model field, check whether it is a property 
                if hasattr(model,property_name) and isinstance(getattr(model,property_name),property):
                    #field is a property
                    if field_name == property_name:
                        model_field = getattr(model,property_name)
                    else:
                        #a sub property of a model property
                        model_field = None
                    db_field = False
                else:
                    raise Exception("Unknown field {} ".format(field_name))

            kwargs.clear()
            if hasattr(opts,"field_classes")  and opts.field_classes and field_name in opts.field_classes and isinstance(opts.field_classes[field_name],forms.Field):
                #already configure a form field instance, use it directly
                form_field = opts.field_classes(field_name)
                field_list.append((field_name, formfield))
                continue

            if opts.widgets and field_name in opts.widgets:
                kwargs['widget'] = opts.widgets[field_name]
            elif not db_field:
                raise Exception("Please cofigure widget for property '{}' in 'widgets' option".format(field_name))

            if opts.localized_fields == forms.models.ALL_FIELDS or (opts.localized_fields and field_name in opts.localized_fields):
                kwargs['localize'] = True

            if opts.labels and field_name in opts.labels:
                kwargs['label'] = safe(opts.labels[field_name])
            elif not db_field:
                kwargs['label'] = safe(field_name)

            if opts.help_texts and field_name in opts.help_texts:
                kwargs['help_text'] = opts.help_texts[field_name]

            if opts.error_messages and field_name in opts.error_messages:
                kwargs['error_messages'] = opts.error_messages[field_name]

            if not db_field:
                kwargs['required'] = False

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

        setattr(opts,'subproperty_enabled',subproperty_enabled)

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

        editable_fields = [name for name,field in new_class.base_fields.iteritems() if not isinstance(field.widget,basewidgets.DisplayWidget)]
        setattr(opts,'editable_fields',editable_fields)
        update_db_fields = list(getattr(opts,"extra_update_fields") or [])
        update_model_properties = []

        for name,field in new_class.base_fields.iteritems():
            if isinstance(field.widget,basewidgets.DisplayWidget):
                continue
            if "." in name:
                #not a model field
                update_model_properties.append(name)
                continue
            try:
                model._meta.get_field(name)
                update_db_fields.append(name)
            except:
                #not a model field
                update_model_properties.append(name)
                continue

        setattr(opts,'update_db_fields',update_db_fields)
        setattr(opts,'update_model_properties',update_model_properties)
        
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

            if self._meta.subproperty_enabled:
                self.initial = SubpropertyEnabledDict(self.initial)

    def is_editable(self,name):
        return self._meta.editable_fields is None or name in self._meta.editable_fields

    def _post_clean(self):
        #save the value of model properties
        if self._meta.update_model_properties:
            for name in self._meta.update_model_properties:
                if "." in name:
                    props = name.split(".")
                    result = getattr(self.instance,props[0])
                    for prop in props[1:-1]:
                        try:
                            result = result[prop]
                        except KeyError as ex:
                            result[prop] = {}
                            result = result[prop]
                    result[props[-1]] = self.cleaned_data[name]
                else:
                    setattr(self.instance,name,self.cleaned_data[name])
        super(ModelForm,self)._post_clean()

    def save(self, commit=True):
        """
        Save this form's self.instance object if commit=True. Otherwise, add
        a save_m2m() method to the form which can be called after the instance
        is saved manually at a later time. Return the model instance.
        """
        update_properties = self._meta.update_model_properties and hasattr(self.instance,"save_properties") and callable(getattr(self.instance, "save_properties"))

        if self.instance.pk and hasattr(self._meta,"update_db_fields") and self._meta.editable_fields:
            if self.errors:
                raise ValueError(
                    "The %s could not be %s because the data didn't validate." % (
                        self.instance._meta.object_name,
                        'created' if self.instance._state.adding else 'changed',
                    )
                )
            if commit:
                # If committing, save the instance and the m2m data immediately.
                with transaction.atomic():
                    self.instance.save(update_fields=self._meta.update_db_fields)
                    if update_properties:
                        self.instance.save_properties(update_fields=self._meta.update_model_properties)
                self._save_m2m()
            else:
                # If not committing, add a method to the form to allow deferred
                # saving of m2m data.
                self.save_m2m = self._save_m2m
        elif commit:
            with transaction.atomic():
                super(ModelForm,self).save(commit)
                if update_properties:
                    self.instance.save_properties(update_fields=self._meta.update_model_properties)

        else:
            super(ModelForm,self).save(commit)


        return self.instance

    def full_clean(self):
        if self._meta.editable_fields is None:
            super(ModelForm,self).full_clean()
            return

        opt_fields = self._meta.fields
        fields = self.fields
        try:
            self._meta.fields = self._meta.editable_fields
            self.editable_fields = self.editable_fields if hasattr(self,'editable_fields') else dict([(n,f) for n,f in self.fields.iteritems() if n in self._meta.fields])
            self.fields = self.editable_fields
            super(ModelForm,self).full_clean()
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
            

