from . import basefields
from django import forms

NOT_NONE=1
HAS_DATA=2
ALWAYS=3
DATA_MAP=4

def switch_layout(policy=HAS_DATA,on_layout=u"{0}<br>{1}",off_layout=u"{0}",reverse=False):
    """
    suitable for compound fields which include primary field and one or more related field
    if reverse is False, will show the related field if primary field is true 
    if reverse is True, will show the related field if primary field is false
    """
    def _func(f):
        val1 = f.value()
        if (not reverse and val1) or (reverse and not val1):
            val2 = f.related_fields[0].value()
            if policy == ALWAYS:
                return (off_layout if reverse else on_layout,f.field.related_field_names)
            elif policy == NOT_NONE and val2 is not None:
                return (off_layout if reverse else on_layout,f.field.related_field_names)
            elif policy == HAS_DATA and val2:
                return (off_layout if reverse else on_layout,f.field.related_field_names)
                
        return (on_layout if reverse else off_layout,None)

    return _func
        
def switch_edit_layout(true_value=True,layout=u"{0}<br>{1}",reverse=False):
    """
    suitable for compound fields which include primary field and one or more related field
    if reverse is False, will show the related field if primary field is true 
    if reverse is True, will show the related field if primary field is false
    """
    def _func(f):
        val1 = f.value()
        if (not reverse and not val1) or (reverse and val1):
            for rf in f.related_fields:
                basefields.hide_field(rf.field)
            
        f.field.widget.attrs = f.field.widget.attrs or {}
        show_fields = ";".join(["$('#{}').show()".format(field.auto_id) for field in f.related_fields])
        hide_fields = ";".join(["$('#{}').hide()".format(field.auto_id) for field in f.related_fields])

        if isinstance(f.field.widget,forms.widgets.RadioSelect):
            f.field.widget.attrs["onclick"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(true_value),show_fields,hide_fields)
        elif isinstance(f.field.widget,forms.widgets.CheckboxInput):
            f.field.widget.attrs["onclick"]="""
                if (this.checked) {{
                    {0}
                }} else {{
                    {1}
                }}
            """.format(show_fields,hide_fields)
        elif isinstance(f.field.widget,forms.widgets.Select):
            f.field.widget.attrs["onchange"]="""
                if (this.value === '{0}') {{
                    {1}
                }} else {{
                    {2}
                }}
            """.format(str(true_value),show_fields,hide_fields)
        return (layout,f.field.related_field_names)
    return _func
        
    
    
def other_option_layout(other_option,policy=HAS_DATA,other_layout="{0}<br>{1}",layout="{0}"):
    """
    suitable for compound fields which include primary field and one or more related field, primary field is a enumeration type, with a other options
    other_layout is used when other option is chosen
    layout is used when other option is not chosen
    """
    def _func(f):
        val1 = f.value()
        #if f.name == "field_officer":
        #    import ipdb;ipdb.set_trace()
        if val1 == other_option:
            val2 = f.related_fields[0].value()
            if policy == ALWAYS:
                return (other_layout,f.field.related_field_names)
            elif policy == NOT_NONE and val2 is not None:
                return (other_layout,f.field.related_field_names)
            elif policy == HAS_DATA and val2:
                return (other_layout,f.field.related_field_names)
            elif policy == DATA_MAP and val2 in other_layout:
                return (other_layout[val2],f.field.related_field_names)
                
        return (layout,None)

    return _func
        
    
