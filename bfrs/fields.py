from django.conf import settings

from . import basefields 
from .models import Cause,Bushfire


class FireCauseField(basefields.CompoundField):
    related_field_names = ("cause_state","other_cause","prescribed_burn_id")
    def _view_layout(self,f):
        cause = f.value()
        cause_state = f.related_fields[0].value()
        if cause and cause == Cause.OTHER:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}<br>{}",("other_cause",))
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}<br>{}",("other_cause",))
            else:
                return ("{}<br>{}",("other_cause",))
        elif cause and cause == Cause.ESCAPE_DPAW_BURNING:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}<br>Burn ID: {}",("prescribed_burn_id",))
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}<br>Burn ID: {}",("prescribed_burn_id",))
            else:
                return ("{}<br>Burn ID: {}",("prescribed_burn_id",))
        elif cause:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known<br>{}",None)
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible<br>{}",None)
            else:
                return ("{}",None)
        else:
            if cause_state == Bushfire.CAUSE_STATE_KNOWN:
                return ("Known",None)
            elif cause_state == Bushfire.CAUSE_STATE_POSSIBLE:
                return ("Possible",None)
            else:
                return ("",None)

    def _edit_layout(self,f):
        cause = f.value()
        # if isinstance(cause,basestring):
        if isinstance(cause,str):
            cause = int(cause) if cause else None

        attrs = {}
        attrs["onchange"]="""
        if (this.value === '{0}') {{
            $("#{1}").show();
            $("#{1}").prop("disabled",false);
        }} else {{
            $("#{1}").hide();
            $("#{1}").prop("disabled",true);
        }}
        if(this.value === '{2}') {{
            $("#{3}").show()
            $("#{3}").prop("disabled",false);
        }} else {{
            $("#{3}").hide()
            $("#{3}").prop("disabled",true);
        }}
        """.format(Cause.OTHER.id,f.related_fields[1].auto_id,Cause.ESCAPE_DPAW_BURNING.id,f.related_fields[2].auto_id)
        return (("{{1}}<br>{{0}}<br>{{2}}{{3}}<script type='text/javascript'>$('#{}').change()</script>".format(f.auto_id),attrs),self.related_field_names)

class InitialAreaField(basefields.CompoundField):
    related_field_names = ("fire_boundary","initial_area_unknown")
    def _view_layout(self,f):
        if f.value():
            return ("{0}",None)
        else:
            area_unknown = f.related_fields[1].value()
            if area_unknown:
                return ("{1}",("initial_area_unknown",))
            else:
                return ("",None)

    def _edit_layout(self,f):
        # initial_boundary = True if f.related_fields[0].value() else False
        initial_boundary = True if f.related_fields and f.related_fields[0] and f.related_fields[0].value() else False
        attrs = {}
        if initial_boundary:
            attrs["disabled"] = True
            return (("{0}",attrs),None)
        else:
            area_unknown = f.related_fields[1].value()

            attrs = {}
            if area_unknown:
                attrs["disabled"] = True
                attrs["style"] = "display:none"

            field1_attrs = {}
            field1_attrs["onclick"]="""
            if (this.checked) {{
                $("#{0}").hide();
                $("#{0}").prop("disabled",true);
            }} else {{
                $("#{0}").show();
                $("#{0}").prop("disabled",false);
            }}
            """.format(f.auto_id)
            return (("{1}<br>{0}",attrs),(("initial_area_unknown",field1_attrs),))

class FinalAreaField(basefields.CompoundField):
    related_field_names = ("final_fire_boundary","area_limit")
    def _view_layout(self,f):
        return ("{0}",None)

    def _edit_layout(self,f):
        #final_boundary = f.related_fields[0].value()
        final_boundary = f.related_fields[0].value() if f.related_fields and f.related_fields[0] else None
        attrs = {}
        if final_boundary:
            attrs["disabled"] = True
            return (("{0}",attrs),None)
        else:
            area_limit = f.related_fields[1].value()
            f.field.widget.attrs = f.field.widget.attrs or {}
            attrs = {}
            if not area_limit:
                attrs["disabled"] = True
                attrs["style"] = "display:none"

            field1_attrs = {}
            field1_attrs["onclick"]="""
            if (this.checked) {{
                $("#{0}").show();
                $("#{0}").prop("disabled",false);
            }} else {{
                $("#{0}").hide();
                $("#{0}").prop("disabled",true);
            }}
            """.format(f.auto_id)
            return (("{{1}} Area < {}ha<span style='margin: 20px;'></span>{{0}}".format(settings.AREA_THRESHOLD),attrs),(("area_limit",field1_attrs),))

class FirePositionField(basefields.CompoundField):
    related_field_names = ("fire_position_override",)
    def _view_layout(self,f):
        return ("{0}<br>SSS override - {1}",self.related_field_names)

    def _edit_layout(self,f):
        override = f.related_fields[0].value()
        attrs = {}
        if not override:
            attrs["disabled"] = True

        field0_attrs = {}
        field0_attrs["onclick"]="""
            if (this.checked) {{
                $("#{0}").prop("disabled",false);
            }} else {{
                $("#{0}").prop("disabled",true);
            }}
            """.format(f.auto_id)
        return (("{0}<br>{1} SSS override",attrs),((self.related_field_names[0],field0_attrs),))

