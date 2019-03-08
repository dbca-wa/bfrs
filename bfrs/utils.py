import LatLon
import tempfile
import subprocess
import shutil

from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from bfrs.models import (Bushfire, BushfireSnapshot, District, Region,BushfireProperty,
    AreaBurnt, Damage, Injury, Tenure,
    SNAPSHOT_INITIAL, SNAPSHOT_FINAL,
    DamageSnapshot, InjurySnapshot, AreaBurntSnapshot,BushfirePropertySnapshot,
    SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS,
    AUTH_MANDATORY_FIELDS, AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND, 
    AUTH_MANDATORY_DEP_FIELDS, AUTH_MANDATORY_DEP_FIELDS_FIRE_NOT_FOUND, AUTH_MANDATORY_FORMSETS,
    check_mandatory_fields,
    )
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.core.mail import send_mail
from cStringIO import StringIO
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.models import User, Group, Permission
import json
import pytz

import unicodecsv
from django.utils.encoding import smart_str
from datetime import datetime
from django.core import serializers
from xlwt import Workbook
from itertools import count
from django.forms.models import inlineformset_factory
from collections import defaultdict, OrderedDict
from copy import deepcopy
from django.core.urlresolvers import reverse
from django.db.models import Q
import requests
from requests.auth import HTTPBasicAuth
from dateutil import tz
from dfes import P1CAD
import os

import logging
logger = logging.getLogger(__name__)

def breadcrumbs_li(links):
    """Returns HTML: an unordered list of URLs (no surrounding <ul> tags).
    ``links`` should be a iterable of tuples (URL, text).
    """
    crumbs = ''
    li_str = '<li><a href="{}">{}</a></li>'
    li_str_last = '<li class="active"><span>{}</span></li>'
    # Iterate over the list, except for the last item.
    if len(links) > 1:
        for i in links[:-1]:
            crumbs += li_str.format(i[0], i[1])
    # Add the last item.
    crumbs += li_str_last.format(links[-1][1])
    return crumbs

_users_group = None
def users_group():
    return Group.objects.get(name='Users')
    #global _users_group
    #if not _users_group:
    #    _users_group = Group.objects.get(name='Users')
    #return _users_group

_fssdrs_group = None
def fssdrs_group():
    return Group.objects.get(name=settings.FSSDRS_GROUP)
    #global _fssdrs_group
    #if not _fssdrs_group:
    #    _fssdrs_group = Group.objects.get(name=settings.FSSDRS_GROUP)
    #return _fssdrs_group

def can_maintain_data(user):
    return fssdrs_group() in user.groups.all() and not is_external_user(user)

def is_external_user(user):
    """ User group check added to prevent role-based internal users from having write access """
    try:
        return user.email.split('@')[1].lower() not in settings.INTERNAL_EMAIL or not user.groups.filter(name__in=['Users', settings.FSSDRS_GROUP,settings.FINAL_AUTHORISE_GROUP]).exists()
        #return user.email.split('@')[1].lower() not in settings.INTERNAL_EMAIL
    except:
        return True

def model_to_dict(instance, include=[], exclude=[]):
    fields = instance._meta.concrete_fields
    if include:
        return {f.attname: getattr(instance, f.attname) for f in fields if f.name in include}
    return {f.attname: getattr(instance, f.attname) for f in fields if f.name not in exclude}

def serialize_bushfire(auth_type, action, obj):
    action = action if action else 'Update'
    snapshot_type = SNAPSHOT_INITIAL if auth_type == 'initial' else SNAPSHOT_FINAL
    d = model_to_dict(obj, exclude=['id', 'created', 'modified'])
    s = BushfireSnapshot.objects.create(snapshot_type=snapshot_type, action=action, bushfire_id=obj.id, **d)

    # create the formset snapshots and attach the bushfire_snapshot
    for i in obj.properties.all():
        BushfirePropertySnapshot.objects.create(
            snapshot_id=s.id, snapshot_type=snapshot_type, name=i.name, value=i.value
        )

    for i in obj.damages.all():
        damage_obj = DamageSnapshot.objects.create(
            snapshot_id=s.id, snapshot_type=snapshot_type, damage_type=i.damage_type, number=i.number, creator=obj.modifier, modifier=obj.modifier
        )

    for i in obj.injuries.all():
        injury_obj = InjurySnapshot.objects.create(
            snapshot_id=s.id, snapshot_type=snapshot_type, injury_type=i.injury_type, number=i.number, creator=obj.modifier, modifier=obj.modifier
        )

    for i in obj.tenures_burnt.all():
        tenure_burnt_obj = AreaBurntSnapshot.objects.create(
            snapshot_id=s.id, snapshot_type=snapshot_type, tenure_id=i.tenure_id, area=i.area, creator=obj.modifier, modifier=obj.modifier
        )

def archive_snapshot(auth_type, action, obj):
        """ 
            allows archicing of existing snapshot before overwriting 
            currently, can't find any code which call this method
        """
        cur_snapshot_history = obj.snapshot_history.all()
        SnapshotHistory.objects.create(
            creator = obj.modifier,
            modifier = obj.modifier,
            auth_type = auth_type,
            action = action if action else 'Update',
            snapshot = obj.initial_snapshot if auth_type =='initial' else obj.final_snapshot if obj.final_snapshot else '{"Deleted": True}',
            prev_snapshot = cur_snapshot_history.latest('created') if cur_snapshot_history else None,
            bushfire_id = obj.id
        )

def invalidate_bushfire(obj, user,cur_obj=None):
    """ 
        Invalidate the current bushfire, create new bushfire report with new fire_number and data in obj and update links, including historical links if the bushfire need to be invalidated
        return (new bushfire,True) if the current bushfire is invalidated and data is saved into a new report, otherwise return (current bushfire,False) directly
    """
    if not obj.pk:
        #new object, can't invalidate it
        return (obj,False)

    #get the current object for database if it is None
    cur_obj = cur_obj or Bushfire.objects.get(pk=obj.pk)

    if cur_obj.district == obj.district:
        #district isn't changed, no need to invalidate it
        return (obj,False)

    with transaction.atomic():
        #invalidate the current object
        cur_obj.report_status = Bushfire.STATUS_INVALIDATED
        cur_obj.invalid_details = obj.invalid_details or "Moved from '{}' to '{}'".format(cur_obj.district.name,obj.district.name)
        cur_obj.modifier = user
        cur_obj.sss_id = None
        cur_obj.save(update_fields=["report_status","invalid_details","modifier","modified","sss_id"])

        # create a new object as a copy of existing
        obj.pk = None

        # check if we have this district already in the list of invalidated linked bushfires, and re-use fire_number if so
        reusable_invalidated_objs = cur_obj.bushfire_invalidated.filter(district=obj.district,report_status=Bushfire.STATUS_INVALIDATED)
        if reusable_invalidated_objs:
            # re-use previous fire_number
            linked_bushfire = reusable_invalidated_objs[0]
            obj.fire_number = linked_bushfire.fire_number
            linked_bushfire.delete() # to avoid integrity constraint
        else:
            # create new fire_number
            obj.fire_number = ' '.join(['BF', str(obj.year), obj.district.code, '{0:03d}'.format(obj.next_id(obj.district))])

        obj.region = obj.district.region
        obj.valid_bushfire = None
        obj.fire_not_found = False
        obj.invalid_details = None
        obj.save()

        # link the new bushfire to the old invalidated bushfire
        created = datetime.now(tz=pytz.utc)

        # move all links from the above invalidated bushfire to the new bushfire
        for linked in cur_obj.bushfire_invalidated.all():
            obj.bushfire_invalidated.add(linked)

        def copy_fk_records(obj_id, fk_set, create_new=True):
            # create duplicate injury records and associate them with the new object
            for record in fk_set.all():
                if create_new:
                    record.id = None
                record.bushfire_id = obj_id 
                record.save()

        copy_fk_records(obj.id, cur_obj.properties)
        copy_fk_records(obj.id, cur_obj.damages)
        copy_fk_records(obj.id, cur_obj.injuries)
        copy_fk_records(obj.id, cur_obj.tenures_burnt)

        # update Bushfire Snapshots to the new bushfire_id and then create a new snapshot
        copy_fk_records(obj.id, cur_obj.snapshots, create_new=False)

        # link the old invalidate bushfire to the new (valid) bushfire - fwd link
        cur_obj.valid_bushfire = obj
        cur_obj.save(update_fields=["valid_bushfire"])

        if obj.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
            serialize_bushfire('Final', 'Update District ({} --> {})'.format(cur_obj.district.code, obj.district.code), obj)

    return (obj,True)

def get_missing_mandatory_fields(obj,action):
    """ 
    Return the missing mandatory fields for report to perfrom the 'action'
    if no missing mandatory fields, return None
    """
    if action == 'submit':
        return check_mandatory_fields(obj, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS) or None

    elif action in ['save_final','save_reviewed','authorise']:
        fields = AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_FIELDS
        dep_fields = AUTH_MANDATORY_DEP_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_DEP_FIELDS
        return (check_mandatory_fields(obj, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS) + check_mandatory_fields(obj, fields, dep_fields, AUTH_MANDATORY_FORMSETS)) or None
    return None

def tenure_category(category):
    """
    Return the tenure category used in bfrs
    """
    if category in ["Freehold"]:
        #Freehold is blonging to "Private Property"
        return "Private Property"
    elif category.lower().startswith('other crown'):
        return "Other Crown"
    else:
        return category

def update_areas_burnt(bushfire, burning_area):
    """
    Updates AreaBurnt model attached to the bushfire record from api.py, via REST API (Operates on data dict from SSS)
    Uses sss_dict
    This method just simply delete the existing datas and add the current datas
    """

    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for layer in burning_area.get("layers",{}).keys():
        for d in burning_area["layers"][layer]['areas']:
            aggregated_sums[tenure_category(d["category"])] += d["area"]

    area_unknown = 0.0
    category_unknown = []
    new_area_burnt_object = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure_qs[0], area=round(area, 2)))
        elif area:
            area_unknown += area
            if category not in category_unknown:
                category_unknown.append(category)

    if area_unknown > 0:
        logger.info('Unknown Tenure categories: ({}). May need to add these categories to the Tenure Table'.format(category_unknown))

    if "other_area" in burning_area:
        area_unknown += burning_area["other_area"]

    if area_unknown > 0:
        new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=Tenure.OTHER, area=round(area_unknown, 2)))

    try:
        with transaction.atomic():
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_area_burnt_object)
    except IntegrityError:
        return 0

    return 1

def update_injury_fs(bushfire, injury_formset):
    if not injury_formset:
        return 1

    if bushfire.injury_unknown:
        #injury unknown, remove all injury objects
        Injury.objects.filter(bushfire=bushfire).delete()
        return 1

    new_fs_object = []
    deleted_fs_id = []
    updated_fs_object = []
    for form in injury_formset:
        if not form.cleaned_data:
            continue
        remove = form.cleaned_data.get('DELETE')
        injury_type = form.cleaned_data.get('injury_type')
        number = form.cleaned_data.get('number')
        obj = form.cleaned_data.get('id')

        #if either injury_type or number is null, remove will be set tp True in BaseInjuryFormSet
        if remove:
            if obj:
                #this object exists in database, removed by user
                deleted_fs_id.append(obj.id)
            else:
                #this object doesn't exist in database,ignore it
                pass
        elif form.is_valid():
            #this is a valid object
            if obj:
                #the object exists in database
                if obj.injury_type != injury_type or obj.number != number:
                    #existing object has been changed
                    obj.injury_type = injury_type
                    obj.number = number
                    updated_fs_object.append(obj)
                else:
                    #existing object is not changed,ignore 
                    pass
            else:
                #this is a new object, add it
                new_fs_object.append(Injury(bushfire=bushfire, injury_type=injury_type,number=number))

    try:
        with transaction.atomic():
            #delete removed objects
            if deleted_fs_id:
                Injury.objects.filter(id__in=deleted_fs_id).delete()
            #update changed objects
            for obj in updated_fs_object:
                obj.save()
            #add new objects
            for obj in new_fs_object:
                obj.save()
    except IntegrityError:
        return 0

    return 1

def update_damage_fs(bushfire, damage_formset):
    if not damage_formset:
        return 1

    if bushfire.damage_unknown:
        #damage unknown, remove all damage objects
        Damage.objects.filter(bushfire=bushfire).delete()
        return 1

    new_fs_object = []
    deleted_fs_id = []
    updated_fs_object = []
    for form in damage_formset:
        if not form.cleaned_data:
            continue
        damage_type = form.cleaned_data.get('damage_type')
        number = form.cleaned_data.get('number')
        remove = form.cleaned_data.get('DELETE')
        obj = form.cleaned_data.get('id')

        #if either damage_type or number is null, remove will be set tp True in BaseDamageFormSet
        if remove:
            if obj:
                #this object exists in database, removed by user
                deleted_fs_id.append(obj.id)
            else:
                #this object doesn't exist in database,ignore it
                pass
        elif form.is_valid():
            #this is a valid object
            if obj:
                #the object exists in database
                if obj.damage_type != damage_type or obj.number != number:
                    #existing object has been changed
                    obj.damage_type = damage_type
                    obj.number = number
                    updated_fs_object.append(obj)
                else:
                    #existing object is not changed,ignore 
                    pass
            else:
                #this is a new object, add it
                new_fs_object.append(Damage(bushfire=bushfire, damage_type=damage_type, number=number))

    try:
        with transaction.atomic():
            #delete removed objects
            if deleted_fs_id:
                Damage.objects.filter(id__in=deleted_fs_id).delete()
            #update changed objects
            for obj in updated_fs_object:
                obj.save()
            #add new objects
            for obj in new_fs_object:
                obj.save()
    except IntegrityError:
        return 0

    return 1

def get_bushfire_url(request, bushfire,url_type):
    if request:
        build_absolute_uri = request.build_absolute_uri
    else:
        build_absolute_uri = lambda uri:uri
    if bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
        return build_absolute_uri(reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id}))

    if url_type == "initial":
        if bushfire.report_status == Bushfire.STATUS_INITIAL:
            return build_absolute_uri(reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id}))
    elif url_type == "initial_snapshot":
        if bushfire.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED:
            return build_absolute_uri(reverse('bushfire:initial_snapshot', kwargs={'pk':bushfire.id}))
    elif url_type == "final":
        if bushfire.report_status >= Bushfire.STATUS_INITIAL_AUTHORISED:
            return build_absolute_uri(reverse('bushfire:bushfire_final', kwargs={'pk':bushfire.id}))
    elif url_type == "final_snapshot":
        if bushfire.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
            return build_absolute_uri(reverse('bushfire:final_snapshot', kwargs={'pk':bushfire.id}))
    elif url_type == "auto":
        if bushfire.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
            return build_absolute_uri(reverse('bushfire:final_snapshot', kwargs={'pk':bushfire.id}))
        elif bushfire.report_status == Bushfire.STATUS_INITIAL_AUTHORISED:
            return build_absolute_uri(reverse('bushfire:bushfire_final', kwargs={'pk':bushfire.id}))
        else:
            return build_absolute_uri(reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id}))

    return ""

def save_model(instance,update_fields=None,extra_update_fields=None):
    if update_fields == "__all__" or extra_update_fields == "__all__":
        #save all
        instance.save()
    elif not update_fields and not extra_update_fields:
        #both update_fields and extra_update_fields are none or empty, save all
        instance.save()
    elif not update_fields:
        instance.save(update_fields=extra_update_fields)
    elif not extra_update_fields:
        instance.save(update_fields=update_fields)
    else:
        instance.save(update_fields=extra_update_fields + update_fields)

def update_status(request, bushfire, action,action_name="",update_fields=None):

    notification = {}
    user_email = request.user.email if settings.CC_TO_LOGIN_USER else None
    if action == 'submit':
        if bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
            #bushfire report is in an invalidated status, can't be submitted
            raise Exception("Can't submit the '{1}' report({0}) ".format(bushfire.fire_number,bushfire.report_status_name))
        elif bushfire.report_status > Bushfire.STATUS_INITIAL:
            #bushfire report is already submiited
            raise Exception("Report({0}) is already submitted".format(bushfire.fire_number))
            
        bushfire.init_authorised_by = request.user
        bushfire.init_authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED

        save_model(bushfire,update_fields,["init_authorised_by","init_authorised_date","report_status"])
        serialize_bushfire('initial', action, bushfire)

        if not bushfire.dfes_incident_no:
            if settings.P1CAD_ENDPOINT:
                #use p1cad web service to create incident no
                try:
                    incident_no = P1CAD.create_incident(bushfire,request)
                    bushfire.dfes_incident_no = incident_no
                    save_model(bushfire,["dfes_incident_no"])
                    notification['create_incident_no'] = "Create dfes incident no '{}'".format(incident_no)
                except Exception as e:
                    notification['create_incident_no'] = "Failed to create dfes incident no. {}".format(e.message)
            else:
                #no dfes incident no, send email to dfes
                resp = send_email({
                    "bushfire":bushfire, 
                    "user_email":user_email,
                    "to_email":settings.DFES_EMAIL,
                    "request":request,
                    "subject":'DFES Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number),
                    "template":"bfrs/email/dfes_email.html"
                })
                notification['DFES'] = 'Email Sent' if resp else 'Email failed'

        # send emails
        if bushfire.dispatch_aerial:
            send_fire_bomging_req_email({
                "bushfire":bushfire, 
                "user_email":user_email,
                "request":request,
            })

        if BushfireProperty.objects.filter(bushfire=bushfire,name="plantations").count() > 0:
            resp = send_email({
                "bushfire":bushfire, 
                "user_email":user_email,
                "to_email":settings.FPC_EMAIL,
                "request":request,
                "subject":'FPC Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number),
                "template":"bfrs/email/fpc_email.html"
            })
            notification['FPC'] = 'Email Sent' if resp else 'Email failed'

        resp = send_email({
            "bushfire":bushfire, 
            "user_email":user_email,
            "to_email":rdo_email_addresses(bushfire),
            "request":request,
            "subject":'RDO Email - {}, Initial Bushfire submitted - {}'.format(bushfire.region.name.upper(), bushfire.fire_number),
            "template":"bfrs/email/rdo_email.html"
        })
        notification['RDO'] = 'Email Sent' if resp else 'Email failed'

        resp = send_email({
            "bushfire":bushfire, 
            "user_email":user_email,
            "to_email":settings.POLICE_EMAIL,
            "request":request,
            "subject":'POLICE Email - Initial Bushfire submitted {}, and an investigation is required - {}'.format(bushfire.fire_number, 'Yes' if bushfire.investigation_req else 'No'),
            "template":"bfrs/email/police_email.html"
        })
        notification['POLICE'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.park_trail_impacted:
            resp = send_email({
                "bushfire":bushfire, 
                "user_email":user_email,
                "to_email":settings.PVS_EMAIL,
                "request":request,
                "subject":'PVS Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number),
                "template":"bfrs/email/pvs_email.html"
            })
            notification['PVS'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.media_alert_req :
            resp = send_email({
                "bushfire":bushfire, 
                "user_email":user_email,
                "to_email":settings.PICA_EMAIL,
                "request":request,
                "subject":'PICA Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number),
                "template":"bfrs/email/pica_email.html"
            })
            notification['PICA'] = 'Email Sent' if resp else 'Email failed'

            resp = send_sms({
                "bushfire":bushfire, 
                "user_email":user_email,
                "phones":settings.MEDIA_ALERT_SMS_TOADDRESS_MAP,
                "request":request,
                "failed_subject":'Failed to send PICA SMS. {}'.format(bushfire.fire_number),
                "template":"bfrs/email/pica_sms.txt"
            })
            notification['PICA SMS'] = 'SMS Sent' if resp else 'SMS failed'

        bushfire.area = None # reset bushfire area
        bushfire.final_fire_boundary = False # used to check if final boundary is updated in Final Report template - allows to toggle show()/hide() area_limit widget via js
        save_model(bushfire,None,["area","final_fire_boundary"])

    elif action == 'authorise':
        if bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
            #bushfire report is in an invalidated status, can't be submitted
            raise Exception("Can't authorise the '{1}' report({0}) ".format(bushfire.fire_number,bushfire.report_status_name))
        elif bushfire.report_status > Bushfire.STATUS_INITIAL_AUTHORISED:
            #bushfire report is already authorised
            raise Exception("Report({0}) is already authorised".format(bushfire.fire_number))

        bushfire.authorised_by = request.user
        bushfire.authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        save_model(bushfire,update_fields,["report_status","authorised_by","authorised_date"])
        serialize_bushfire('final', action, bushfire)

        # send emails
        resp = send_email({
            "bushfire":bushfire, 
            "user_email":user_email,
            "to_email":settings.FSSDRS_EMAIL,
            "request":request,
            "subject":'FSSDRS Email - Final Fire report has been authorised - {}'.format(bushfire.fire_number),
            "template":"bfrs/email/fssdrs_authorised_email.html"
        })
        notification['FSSDRS-Auth'] = 'Email Sent' if resp else 'Email failed'

    elif action == 'mark_reviewed':
        if not bushfire.can_review:
            if not self.is_final_authorised:
                raise Exception("Please authorise the report({0}) before reviewing.".format(bushfire.fire_number))
            elif not self.final_fire_boundary:
                raise Exception("Please upload the final fire boundary for the report({0}) before reviewing.".format(bushfire.fire_number))
            elif not self.area:
                raise Exception("No need to review the report({0}) which has no burning area.".format(bushfire.fire_number))
            else:
                raise Exception("No need to reivew the report({0}) which has no fire found".format(bushfire.fire_number))
        bushfire.reviewed_by = request.user
        bushfire.reviewed_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_REVIEWED
        save_model(bushfire,update_fields,["report_status","reviewed_by","reviewed_date"])
        serialize_bushfire('review', action, bushfire)

        # send emails
        resp = send_email({
            "bushfire":bushfire, 
            "user_email":user_email,
            "to_email":settings.FSSDRS_EMAIL,
            "request":request,
            "subject":'FSSDRS Email - Final Fire report has been reviewed - {}'.format(bushfire.fire_number),
            "template":"bfrs/email/fssdrs_reviewed_email.html"
        })
        notification['FSSDRS-Review'] = 'Email Sent' if resp else 'Email failed'

    elif action in ('delete_final_authorisation' , 'delete_authorisation_(missing_fields_-_FSSDRS)', 'delete_authorisation(merge_bushfires)'):
        if not bushfire.is_final_authorised:
            raise Exception("The report({0}) is not authorised.".format(bushfire.fire_number))
        if bushfire.is_reviewed:
            #already reviewed, remove the review status
            bushfire.reviewed_by = None
            bushfire.reviewed_date = None

        if not bushfire.area:
            bushfire.final_fire_boundary = False

        if bushfire.archive:
            #already archived, reset to unarchived
            bushfire.archive = False

        bushfire.authorised_by = None
        bushfire.authorised_date = None
        bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
        save_model(bushfire,update_fields,["authorised_by","authorised_date","report_status","reviewed_by","reviewed_date","final_fire_boundary","archive"])
        serialize_bushfire('final', action, bushfire)

    elif action == 'delete_review':
        if not bushfire.is_reviewed:
            raise Exception("The report({0}) is not reviewed.".format(bushfire.fire_number))
        bushfire.reviewed_by = None
        bushfire.reviewed_date = None
        bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        save_model(bushfire,update_fields,["reviewed_by","reviewed_date","report_status"])
        serialize_bushfire('review', action, bushfire)
    elif action == 'archive':
        if bushfire.report_status < Bushfire.STATUS_FINAL_AUTHORISED:
            raise Exception("The report({0}) is not authorised.".format(bushfire.fire_number))
        elif bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
            raise Exception("The report({0}) is invalidated.".format(bushfire.fire_number))
        elif bushfire.archive:
            raise Exception("The report({0}) is already archived".format(bushfire.fire_number))
        bushfire.archive = True
        save_model(bushfire,update_fields,["archive"])
    elif action == 'unarchive':
        if not bushfire.archive:
            raise Exception("The report({0}) is not archived".format(bushfire.fire_number))
        bushfire.archive = False
        save_model(bushfire,update_fields,["archive"])
    elif action == "merge_reports":
        #merge bushfires into another bushfire
        #validate the parameters
        primary_bushfire,merged_bushfires = bushfire
        if not primary_bushfire:
            raise Exception("Primary bushfire is missing")
        elif not primary_bushfire.pk:
            raise Exception("Primary bushfire is not created")
        elif primary_bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
            raise Exception("The bushfire({1}) is '{2}' and is not eligible to be a primary bushfire for '{0}'.".format(action_name,primary_bushfire.id,primary_bushfire.report_status_name))
        
        if not merged_bushfires:
            raise Exception("Merged bushfires is missing")
        invalid_bushfires = [ bf for bf in merged_bushfires if not bf.pk ]
        if invalid_bushfires:
            raise Exception("{} bushfires are not created yet.".format(len(invalid_bushfires)))
        invalid_bushfires = [ bf for bf in merged_bushfires if bf.report_status >= Bushfire.STATUS_INVALIDATED ] 
        if invalid_bushfires:
            raise Exception("The bushfires({1}) are not eligible for '{0}'".format(action_name,["{}<{}>".format(bf.fire_number,bf.report_status_name) for bf in invalid_bushfires]))

        with transaction.atomic():
            #clean the final fire boundary related data: burning area, final fire boundary flag, 
            primary_bushfire.tenures_burnt.all().delete()
            primary_bushfire.final_fire_boundary = False
            primary_bushfire.area = None
            primary_bushfire.other_area = None

            if primary_bushfire.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
                #if primary bushfire is final authorised, then remove the authorisation 
                update_status(request,primary_bushfire,'delete_authorisation(merge_bushfires)',update_fields=["final_fire_boundary","area","other_area"])
            else:
                primary_bushfire.save(update_fields=["final_fire_boundary","area","other_area"])
                
            #update merged bushfires to merged status and link to the primary bushfire
            for bf in merged_bushfires:
                bf.invalid_details = "Merged to bushfire '{}'".format(primary_bushfire.fire_number)
                bf.valid_bushfire = primary_bushfire
                if bf.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
                    bf.report_status = Bushfire.STATUS_MERGED
                    serialize_bushfire("final", "Merge", bf)
                else:
                    bf.report_status = Bushfire.STATUS_MERGED
                bf.save(update_fields=["invalid_details","valid_bushfire","report_status"])

                #if some bushfires were merged into this bushfire, then relink those merged bushfire to new primary bushfire
                for mbf in bf.bushfire_invalidated.filter(report_status = Bushfire.STATUS_MERGED):
                    mbf.invalid_details = "Merged to bushfire '{}'".format(primary_bushfire.fire_number)
                    mbf.valid_bushfire = primary_bushfire
                    mbf.save(update_fields=["invalid_details","valid_bushfire"])

            #send emails
        resp = send_email({
            "bushfire":primary_bushfire, 
            "related_bushfires":merged_bushfires,
            "user_email":user_email,
            "to_email":concat_email_addresses(settings.MERGE_BUSHFIRE_EMAIL,rdo_email_addresses(primary_bushfire,merged_bushfires)),
            "request":request,
            "title_4_related_bushfires":"The merged bushfires are listed below.",
            "subject":'{0} Email - Merge bushfires({2}) to primary bushfire ({1})'.format(action_name,primary_bushfire.fire_number,",".join([bf.fire_number for bf in merged_bushfires])),
            "template":"bfrs/email/merge_bushfires_email.html"
        })
        notification['invalidate_duplicated_bushfire'] = 'Email Sent' if resp else 'Email failed'

    elif action == "invalidate_duplicated_reports":
        #validate the parameters
        primary_bushfire,duplicated_bushfires = bushfire
        if not primary_bushfire:
            raise Exception("Primary bushfire is missing")
        elif not primary_bushfire.pk:
            raise Exception("Primary bushfire is not created")
        elif primary_bushfire.report_status >= Bushfire.STATUS_INVALIDATED:
            raise Exception("The bushfire({1}) is '{2}' and is not eligible to be a primary bushfire for '{0}'.".format(action_name,primary_bushfire.id,primary_bushfire.report_status_name))
        
        if not duplicated_bushfires:
            raise Exception("Duplicated bushfires is missing")
        invalid_bushfires = [ bf for bf in duplicated_bushfires if not bf.pk ]
        if invalid_bushfires:
            raise Exception("{} bushfires are not created yet.".format(len(invalid_bushfires)))
        invalid_bushfires = [ bf for bf in duplicated_bushfires if bf.report_status >= Bushfire.STATUS_INVALIDATED ] 
        if invalid_bushfires:
            raise Exception("The bushfires({1}) are not eligible for '{0}'".format(action_name,["{}<{}>".format(bf.fire_number,bf.report_status_name) for bf in invalid_bushfires]))

        with transaction.atomic():
            #update duplicated bushfires to duplicated status and link to the primary bushfire
            for bf in duplicated_bushfires:
                bf.invalid_details = "Duplicated with bushfire '{}'".format(primary_bushfire.fire_number)
                bf.valid_bushfire = primary_bushfire
                if bf.report_status >= Bushfire.STATUS_FINAL_AUTHORISED:
                    bf.report_status = Bushfire.STATUS_DUPLICATED
                    serialize_bushfire("final", "Invalidate_duplicated_reports", bf)
                else:
                    bf.report_status = Bushfire.STATUS_DUPLICATED
                bf.save(update_fields=["invalid_details","valid_bushfire","report_status"])
                #if some bushfires were duplicated with this bushfire, then relink those duplicated bushfire to new primary bushfire
                for dbf in bf.bushfire_invalidated.filter(report_status = Bushfire.STATUS_DUPLICATED):
                    dbf.invalid_details = "Duplicated with bushfire '{}'".format(primary_bushfire.fire_number)
                    dbf.valid_bushfire = primary_bushfire
                    dbf.save(update_fields=["invalid_details","valid_bushfire"])

        #send emails
        resp = send_email({
            "bushfire":primary_bushfire, 
            "related_bushfires":duplicated_bushfires,
            "user_email":user_email,
            "to_email":rdo_email_addresses(primary_bushfire,duplicated_bushfires),
            "request":request,
            "title_4_related_bushfires":"The duplciated bushfires are listed below.",
            "subject":'{0} Email - Duplicated bushfires({2}) are linked to bushfire ({1})'.format(action_name,primary_bushfire.fire_number,",".join([bf.fire_number for bf in duplicated_bushfires])),
            "template":"bfrs/email/invalidate_duplicated_bushfires_email.html"
        })
        notification['invalidate_duplicated_bushfire'] = 'Email Sent' if resp else 'Email failed'
    else:
        raise Exception("Unknow action({})".format(action))
        
    return notification

def send_fire_bomging_req_email(context):
    bushfire = context["bushfire"]
    context["to_email"] = settings.FIRE_BOMBING_REQUEST_EMAIL
    if "user_email" in context:
        context["cc_email"] = concat_email_addresses(settings.FIRE_BOMBING_REQUEST_CC_EMAIL,settings.CC_EMAIL,context.pop("user_email"))
    else:
        context["cc_email"] = concat_email_addresses(settings.FIRE_BOMBING_REQUEST_CC_EMAIL,settings.CC_EMAIL)
    context["subject"] = 'Fire Bombing Request Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number)
    context["template"] = "bfrs/email/fire_bombing_request_email.html"
    folder = None
    try:
        folder,pdf_file = generate_pdf("latex/fire_bombing_request_form.tex",context={"bushfire":bushfire,"graphic_folder":settings.LATEX_GRAPHIC_FOLDER})
        context["attachments"] = [(pdf_file,"fire_bombing_request.pdf","application/pdf")]
        send_email(context)
    finally:
        if folder:
            shutil.rmtree(folder)
        


NOTIFICATION_FIELDS = [
    'region', 'district', 'year',
    'name', 'fire_detected_date',
    'fire_number', 'dfes_incident_no',
    'fire_position', 'origin_point', 'origin_point_mga',
    'tenure', 'duty_officer',
    'dispatch_pw', 'dispatch_pw_date', 'dispatch_aerial', 'dispatch_aerial_date',
    'initial_control', 'initial_area',
    'prob_fire_level', 'investigation_req',
    'media_alert_req', 'park_trail_impacted',
    'other_info',
]


def notifications_to_html(bushfire, url):
    #d = [(bushfire._meta.get_field(i).verbose_name, str(getattr(bushfire, i))) for i in NOTIFICATION_FIELDS]
    d = []
    for i in NOTIFICATION_FIELDS:
        try:
            d.append( (bushfire._meta.get_field(i).verbose_name, str(getattr(bushfire, i))) )
        except:
            d.append( (bushfire._meta.get_field(i).verbose_name, getattr(bushfire, i)) )

    ordered_dict = OrderedDict(d)

    msg = '<table style="border:1px solid black;">'
    for k,v in ordered_dict.iteritems():
        if k == bushfire._meta.get_field('dfes_incident_no').verbose_name:
            v = '<font color="red">Not available</font>' if not v else v
        elif v == 'None' or not v:
            v = '-'
        elif v == 'False':
            v = 'No'
        elif v == 'True':
            v = 'Yes'
        elif k == bushfire._meta.get_field('dispatch_pw').verbose_name:
            v = 'Yes' if v == '1' else 'No'
        elif k == bushfire._meta.get_field('origin_point').verbose_name:
            v = bushfire.origin_geo
        elif k == bushfire._meta.get_field('dispatch_pw_date').verbose_name:
            v = bushfire.dispatch_pw_date.astimezone(tz.gettz(settings.TIME_ZONE)).strftime('%Y-%m-%d %H:%M')
        elif k == bushfire._meta.get_field('dispatch_aerial_date').verbose_name:
            v = bushfire.dispatch_aerial_date.astimezone(tz.gettz(settings.TIME_ZONE)).strftime('%Y-%m-%d %H:%M')
        elif k == bushfire._meta.get_field('fire_detected_date').verbose_name:
            v = bushfire.fire_detected_date.astimezone(tz.gettz(settings.TIME_ZONE)).strftime('%Y-%m-%d %H:%M')
            
        msg += '<tr> <th style="border-bottom:1px solid; border-right:1px solid; text-align: left;">' + k + '</th> <td style="border-bottom:1px solid;">' + v + '</td> </tr>'
    msg += '</table><br>'

    if url and not bushfire.dfes_incident_no:
        url_final = url.replace('initial/snapshot', 'final')
        msg += 'DFES incident number not available, please check the bushfire reporting system for updates to the DFES incident number <a href="{0}">{1}</a>'.format(url_final, bushfire.fire_number)

    msg += '<br><br>'
    msg += '<font face="Calibri" color="gray">The information contained in this email was the best available at the time. For updated information please contact the relevant Duty Officer</font>'


    return msg

def concat_strings(*args):
    """
    Try not to create new list object if possible
    return None if no args'
           the args if no merging is required
           a new list object which conbine all email addresses after removing duplcated email address
    """
    if not args:
        return None
        
    created = False
    result = None
    for addresses in args:
        if not addresses:
            #None or empty list. ignore
            continue
        if result is None:
            #first non empyt address list, try to use it as the result list
            result = addresses
            continue
        if isinstance(addresses,list) or isinstance(addresses,tuple):
            #address list
            if isinstance(result,list) or isinstance(result,tuple):
                for address in addresses:
                    if address in result:
                        #already in result,ignore
                        continue
                    elif created:
                        #result list is a new created list, add it to list directly
                        result.append(address)
                    elif isinstance(result,tuple):
                        #create a new list to combine the result and current address
                        result = list(result)
                        result.append(address)
                        created = True
                    else:
                        #create a new list to combine the result and current address
                        result = result + [address]
                        created = True
            elif result in addresses:
                #result is already in addresses
                continue
            elif isinstance(addresses,tuple):
                #create a list to combine the result and current address list
                result = list(addresses)
                result.append(result)
                created = True
            else:
                #create a list to combine the result and current address list
                result = addresses + [result]
                created = True
        else:
            #addresses is just a single email address
            if isinstance(result,list) or isinstance(result,tuple):
                if addresses in result:
                    #already in result, ignore
                    continue
                elif created:
                    #result list is a new created list, add it to list directly
                    result.append(addresses)
                elif isinstance(result,tuple):
                    #create a new list to combine the result and current address
                    result = list(result)
                    result.append(addresses)
                    created = True
                else:
                    #create a new list to combine the result and current address
                    result = result + [addresses]
                    created = True
            elif addresses == result:
                #address is same as the result,ignore
                continue
            else:
                #create a new list to combine the result and current addresses
                result = [result,addresses]
                created = True

    return result

def concat_email_addresses(*args):
    result = concat_strings(*args)
    if not result:
        return None
    elif isinstance(result,list) or isinstance(result,tuple):
        return result
    else:
        return [result]

def send_email(context):
    if not settings.ALLOW_EMAIL_NOTIFICATION or context["bushfire"].fire_number in settings.EMAIL_EXCLUSIONS:
        #email notification is disabled.        `
        return

    #clear the send_failed status if it is true
    if context.get("send_failed"):
        del context["send_failed"]

    subject = context.get("subject") or ""
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)
    body = render_to_string(context["template"],context=context)
    """
    if context.get("save_email_to_file"):
        with open(context["save_email_to_file"],'wb') as f:
            f.write(u'{}'.format(body).encode('utf-8'))
    """
    message = EmailMessage(
        subject=subject, 
        body=body, 
        from_email=context.get("from_email",settings.FROM_EMAIL), 
        to=context.get("to_email") or None, 
        cc=concat_email_addresses(context.get("cc_email",settings.CC_EMAIL),context.get("user_email")), 
        bcc=context.get("bcc_email",settings.BCC_EMAIL))
    for attachment in context.get("attachments") or []:
        with open(attachment[0]) as f:
            message.attach(attachment[1],f.read(),attachment[2])
    message.content_subtype = 'html'
    ret = message.send()

    if not ret :
        subject = (context.get("failed_subject") or "Failed to send email \" {}\"").format(subject)
        context["send_failed"] = True
        context["original_subject"] = context.get("subject") or ""
        email_address = lambda address: (address if isinstance(address,str) else ";".join(address))if address else ""
        context["original_from_email"] = email_address(context.get("from_email",settings.FROM_EMAIL))
        context["original_to_email"] = email_address(context.get("to_email"))
        context["original_cc_email"] = email_address(concat_email_addresses(context.get("cc_email",settings.CC_EMAIL),context.get("user_email")))
        context["original_bcc_email"] = email_address(context.get("bcc_email",settings.BCC_EMAIL))
        context["from_email"] = settings.FROM_EMAIL
        context["to_email"] = settings.SUPPORT_EMAIL
        context["cc_email"] = context.get("user_email") or None
        context["send_date"] = str(datetime.now())
        if "bcc_email" in context:
            del context["bcc_email"]

        body = render_to_string(context["template"],context=context)

        logger.error(subject)
        support_email(subject,body,context.get("user_email"))

    return ret

def rdo_email_addresses(bushfire,related_bushfires=None):
    region_name = bushfire.region.name.upper()
    to_email = getattr(settings, region_name.replace(' ', '_') + '_EMAIL') or []
    #add all email address for related_bushfires to to_email
    if related_bushfires:
        for bf in related_bushfires:
            region_name = bf.region.name.upper()
            for address in getattr(settings, region_name.replace(' ', '_') + '_EMAIL') or []:
                if address not in to_email:
                    to_email.append(address)

    return to_email

def send_sms(context):
    if not settings.ALLOW_EMAIL_NOTIFICATION or context["bushfire"].fire_number in settings.EMAIL_EXCLUSIONS or not context.get("phones"):
       return

#    if 'bfrs-prod' not in os.getcwd():
#       return

    message = render_to_string(context["template"],context=context)
    message = message.strip()

    TO_SMS_ADDRESS = None
    if isinstance(context["phones"],list):
        TO_SMS_ADDRESS = [phone_no + '@' + settings.SMS_POSTFIX for phone_no in context["phones"]]
    elif isinstance(context["phones"],dict):
        TO_SMS_ADDRESS = [phone_no + '@' + settings.SMS_POSTFIX for phone_no in context["phones"].values()]
    else:
        TO_SMS_ADDRESS = [context["phones"] + '@' + settings.SMS_POSTFIX]
    ret = send_mail('', message, settings.EMAIL_TO_SMS_FROMADDRESS, TO_SMS_ADDRESS)

    if not ret :
        subject = context.get("failed_subject") or "Failed to send sms"
        context["original_subject"] = context.get("subject") or ""
        email_address = lambda address: (address if isinstance(address,str) else ";".join(address))if address else ""
        context["original_from_email"] = email_address(context.get("from_email",settings.FROM_EMAIL))
        context["from_email"] = settings.FROM_EMAIL
        context["to_email"] = settings.SUPPORT_EMAIL
        context["cc_email"] = context.get("user_email") or None
        context["send_failed"] = True
        context["send_date"] = str(datetime.now())
        context["sms_message"] = message

        body = render_to_string("bfrs/email/send_sms_failed.html",context=context)

        logger.error(ret)
        support_email(subject,body,context.get("user_email"))

    return ret

def support_email(subject, body,user_email):
    if not settings.SUPPORT_EMAIL and not user_email:
       return

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.SUPPORT_EMAIL,cc=[user_email] if user_email else None)
    message.content_subtype = 'html'
    ret = message.send()
    if not ret:
        logger.error('Failed to send Support Email<br>subject: {}<br>body: {}'.format(subject, body))


def create_other_user():
    user, created = User.objects.get_or_create(username='other', first_name='Other', last_name='Contact')
    users_group, users_group_created = Group.objects.get_or_create(name='Users')
    user.groups.add(users_group)

def create_admin_user():
    return User.objects.get_or_create(username='admin',
        defaults={'is_active':'False', 'first_name':'Admin', 'last_name':'Admin', 'email':'admin@{}'.format(settings.INTERNAL_EMAIL[0]) }
    )

def _add_users_to_fssdrs_group():
    group, g_created = Group.objects.get_or_create(name=settings.FSSDRS_GROUP)
    if g_created:
        group.permissions = Permission.objects.filter(codename__in=['add_group', 'change_group', 'add_permission', 'change_permission', 'add_user', 'change_user', 'final_authorise_bushfire'])

    for user in User.objects.filter(email__in=settings.FSSDRS_USERS):
        if not user.groups.filter(id=group.id).exists():
            user.groups.add(group)
            logger.info('Adding user {} to group {}'.format(user.get_full_name(), group.name))

        if not user.is_staff:
            user.is_staff = True
            user.save()

def _add_users_to_final_authorise_group():
    group, g_created = Group.objects.get_or_create(name=settings.FINAL_AUTHORISE_GROUP)
    if g_created:
        group.permissions = Permission.objects.filter(codename__in=['final_authorise_bushfire'])

    for user in User.objects.filter(email__in=settings.FINAL_AUTHORISE_GROUP_USERS):
        if not user.groups.filter(id=group.id).exists():
            user.groups.add(group)
            logger.info('Adding user {} to group {}'.format(user.get_full_name(), group.name))

        if not user.is_staff:
            user.is_staff = True
            user.save()

def _add_users_to_users_group(resp):
    users_group, users_group_created = Group.objects.get_or_create(name='Users')
    for user in resp.json()['objects']:
        try:
            if user['email'] and user['email'].split('@')[-1].lower() in settings.INTERNAL_EMAIL:
                u = User.objects.get(username__iexact=user['username'].lower())
                if users_group not in u.groups.all():
                    u.groups.add(users_group)
                    logger.info('Adding user {} to group {}'.format(u.get_full_name(), users_group.name))

        except Exception as e:
            logger.error('Error Adding Group to user:  {}\n{}\n'.format(user, e))

def _update_users_from_active_directory(sso_users):
    """
    Update Django users from Active Directory (AD)
    For all Django users missing from AD, set them inactive - these users are assumed no longer employed at the dept.
    we don't delete them since some may have FK relationships
    """
    ad_users  = []
    dj_users = []
    [ad_users.append(user['email']) for user in sso_users.json()['objects']]
    [dj_users.append(user.email) for user in User.objects.all()]
    #missing_from_dj = list(set(ad_users).difference(dj_users))
    missing_from_ad = list(set(dj_users).difference(ad_users))

    no_set_inactive = User.objects.filter(username__in=missing_from_ad).exclude(username='other').update(is_active=False)
    logger.info('Users set inactive: {}'.format(no_set_inactive))

def _delete_duplicate_users():
    """ Delete all duplicate users, keeping the lowercase emails - Assumes emails are unique (which they are in AD) """
    for u in User.objects.all():
        qs =User.objects.filter(email__iexact=u.email)
        if qs.count() > 1:
            for user in qs:
                if user.email.islower():
                    pass
                else:
                    qs_fires = Bushfire.objects.filter(Q(creator=user) | Q(modifier=user) | Q(duty_officer=user) | Q(field_officer=user))
                    if qs_fires.count() == 0:
                        user.delete()
                    else:
                        logger.info('Cannot Delete Duplicate User. User {} has Bushfire(s) associated'.format(user))
                        

def update_users():
    resp=requests.get(url=settings.URL_SSO, auth=HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO))

    for user in resp.json()['objects']:
        try:
            if user['email'] and user['email'].split('@')[-1].lower() in settings.INTERNAL_EMAIL:
                #if user['email'].lower() == 'imt1_imt@dbca.wa.gov.au' or user['email'].lower() == 'ops_computers@dbca.wa.gov.au':
                #if 'imt' in user['email'].lower() or 'ops_computers' in user['email'].lower():
                #    import ipdb; ipdb.set_trace()
                    
                if User.objects.filter(email=user['email']).count() == 0:
                    u, created = User.objects.get_or_create(
                        username=user['username'].lower(),
                        defaults = {
                            'first_name': user['given_name'].lower().capitalize(),
                            'last_name': user['surname'].lower().capitalize(),
                            'email': user['email']
                        }
                    )

                    if created:
                        logger.info('User {}, Created {}'.format(u.get_full_name(), created))

        except Exception as e:
            logger.error('Error creating user:  {}\n{}\n'.format(user, e))


    _update_users_from_active_directory(resp)
    _add_users_to_fssdrs_group()
    _add_users_to_final_authorise_group()
    _add_users_to_users_group(resp)
    _delete_duplicate_users()
    create_other_user()
    create_admin_user()

def update_email_domain():
    for u in User.objects.all():
        if 'dpaw' in u.email:
            u.email = u.email.replace('dpaw', 'dbca')
            u.save()

        if 'DPaW' in u.email:
            u.email = u.email.replace('DPaW', 'dbca')
            u.save()

def refresh_gokart(request, fire_number=None, region=None, district=None, action=None):
    request.session['refreshGokart'] = {
        'ignoreIfNotOpen':'true',
        'data':{
            'refresh': True,
            'region' : region if region else None,
            'district' : district if district else None,
            'bushfireid' : fire_number if fire_number else None,
            'action': action if action else ('create' if 'create' in request.get_full_path() else 'update')
        }
    }
    request.session.modified = True


def get_pbs_bushfires(fire_ids=None):
    """ 
        fire_ids: string --> BF_2017_SWC_001, BF_2017_SWC_002, BF_2017_SWC_003", OR
                  list   --> ["BF_2017_SWC_001", "BF_2017_SWC_002", "BF_2017_SWC_003"]
    
        Returns list of dicts:
        [
            {'fire_id': u'BF_2017_SWC_001', 'area': '0.3', 'region': 1},
            {'fire_id': u'BF_2017_DON_001', 'area': '2.3', 'region': 2}
        ]
    """
    try:
        if fire_ids:
            if isinstance(fire_ids, list):
                params = {"fire_id__in": ','.join(fire_ids)}
            else:
                params = {"fire_id__in": fire_ids}
        elif isinstance(fire_ids, list) and len(fire_ids) == 0:
            """ case where there are no outstanding fires in BFRS """
            return 
        else:
            params = None
        pbs_url = settings.PBS_URL if settings.PBS_URL.endswith('/') else settings.PBS_URL + os.sep
        url = pbs_url + 'api/v1/prescribedburn/?format=json'
        return requests.get(url=url, params=params, auth=requests.auth.HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO)).json()
    except Exception as e:
        logger.error('REST API error connecting to PBS 268b bushfires:  {}\n{}\n'.format(url, e))
        return []
   

def export_final_csv(request, queryset):
    #import csv
    filename = 'export_final-' + datetime.now().strftime('%Y-%m-%dT%H%M%S') + '.csv'
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=' + filename
    writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

    writer.writerow([
        "ID",
		"Region",
		"District",
		"Name",
		"Year",
		"Incident No",
		"DFES Incident No",
		"Job Code",
		"Fire Level",
		"Media Alert Req",
		"Investigation Req",
		"Fire Position",
		#"Origin Point",
		#"Fire Boundary",
		"Fire Not Found",
		"Other Info",
		"Cause",
		"Other Cause",
		"Field Officer",
		"Duty Officer",
		"Init Authorised By",
		"Init Authorised Date",
		"Authorised By",
		"Authorised Date",
		"Dispatch P&W",
		"Dispatch Aerial",
		"Fire Detected",
		"Fire Controlled",
		"Fire Contained",
		"Fire Safe",
		"Fuel Type",
		#"Initial Snapshot",
		"First Attack",
		"Other First Attack",
		"Initial Control",
		"Other Initial Control",
		"Final Control",
		"Other Final Control",
		"Arson Squad Notified",
		"Offence No",
		"Area",
		"Authorised By",
		"Authorised Date",
		"Report Status",
    ]
	)
    for obj in queryset:
		writer.writerow([
			smart_str( obj.id),
			smart_str( obj.region.name),
			smart_str( obj.district.name),
			smart_str( obj.name),
			smart_str( obj.year),
			smart_str( obj.fire_number),
			smart_str( obj.dfes_incident_no),
			smart_str( obj.job_code),
			smart_str( obj.get_prob_fire_level_display()),
			smart_str( obj.media_alert_req),
			smart_str( obj.investigation_req),
			smart_str( obj.fire_position),
			#row.write(col_no(), smart_str( obj.origin_point)),
			#row.write(col_no(), smart_str( obj.fire_boundary),
			smart_str( obj.fire_not_found),
			smart_str( obj.other_info),
			smart_str( obj.cause),
			smart_str( obj.other_cause),
			smart_str( obj.field_officer.get_full_name() if obj.field_officer else None ),
			smart_str( obj.duty_officer.get_full_name() if obj.duty_officer else None ),
			smart_str( obj.init_authorised_by.get_full_name() if obj.init_authorised_by else None ),
			smart_str( obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else None),
			smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ),
			smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None),
			smart_str( obj.dispatch_pw_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_pw_date else None),
			smart_str( obj.dispatch_aerial_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_aerial_date else None),
			smart_str( obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else None),
			smart_str( obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else None),
			smart_str( obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else None),
			smart_str( obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else None),
			smart_str( obj.fuel_type),
			#row.write(col_no(), smart_str( obj.initial_snapshot),
			smart_str( obj.first_attack),
			smart_str( obj.other_first_attack),
			smart_str( obj.initial_control),
			smart_str( obj.other_initial_control),
			smart_str( obj.final_control),
			smart_str( obj.other_final_control),
			smart_str( obj.arson_squad_notified),
			smart_str( obj.offence_no),
			smart_str( obj.area),
			smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ),
			smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ),
			smart_str( obj.get_report_status_display()),
        ])
    return response
export_final_csv.short_description = u"Export CSV (Final)"


def export_excel(request, queryset):

    filename = 'export_final-' + datetime.now().strftime('%Y-%m-%dT%H%M%S') + '.xls'
    #response = HttpResponse(content_type='application/vnd.ms-excel; charset=utf-16')
    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename=' + filename
    writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)
    #import ipdb; ipdb.set_trace()


    book = Workbook()
    sheet1 = book.add_sheet('Data')
    book.add_sheet('Sheet 2')

    col_no = lambda c=count(): next(c)
    row_no = lambda c=count(): next(c)
    sheet1 = book.get_sheet(0)
    hdr = sheet1.row(row_no())

    hdr.write(col_no(), "ID")
    hdr.write(col_no(), "Region")
    hdr.write(col_no(), "District")
    hdr.write(col_no(), "Name")
    hdr.write(col_no(), "Year")
    hdr.write(col_no(), "Fire Number")
    hdr.write(col_no(), "DFES Incident No")
    hdr.write(col_no(), "Job Code")
    hdr.write(col_no(), "Probable Fire Level")
    hdr.write(col_no(), "Max Fire Level")
    hdr.write(col_no(), "Media Alert Req")
    hdr.write(col_no(), "Investigation Req")
    hdr.write(col_no(), "Fire Position")
    #"Origin Point",
    #"Fire Boundary",
    hdr.write(col_no(), "Fire Not Found")
    hdr.write(col_no(), "Other Info")
    hdr.write(col_no(), "Cause")
    hdr.write(col_no(), "Other Cause")
    hdr.write(col_no(), "Field Officer")
    hdr.write(col_no(), "Duty Officer")
    hdr.write(col_no(), "Init Authorised By")
    hdr.write(col_no(), "Init Authorised Date")
    hdr.write(col_no(), "Authorised By")
    hdr.write(col_no(), "Authorised Date")
    hdr.write(col_no(), "Dispatch P&W")
    hdr.write(col_no(), "Dispatch Aerial")
    hdr.write(col_no(), "Fire Detected")
    hdr.write(col_no(), "Fire Controlled")
    hdr.write(col_no(), "Fire Contained")
    hdr.write(col_no(), "Fire Safe")
    #hdr.write(col_no(), "Fuel Type")
    hdr.write(col_no(), "First Attack")
    hdr.write(col_no(), "Other First Attack")
    hdr.write(col_no(), "Initial Control")
    hdr.write(col_no(), "Other Initial Control")
    hdr.write(col_no(), "Final Control")
    hdr.write(col_no(), "Other Final Control")
    hdr.write(col_no(), "Arson Squad Notified")
    hdr.write(col_no(), "Offence No")
    hdr.write(col_no(), "Area")
    hdr.write(col_no(), "Authorised By")
    hdr.write(col_no(), "Authorised Date")
    hdr.write(col_no(), "Report Status")
    hdr.write(col_no(), "Tenures of Area Burnt")
    hdr.write(col_no(), "Damage")
    hdr.write(col_no(), "Injuries and Fatalities")

    row_no = lambda c=count(1): next(c)
    for obj in queryset:
        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)

        row.write(col_no(), obj.id )
        row.write(col_no(), obj.region.name )
        row.write(col_no(), obj.district.name )
        row.write(col_no(), obj.name)
        row.write(col_no(), obj.year )
        row.write(col_no(), obj.fire_number )
        row.write(col_no(), obj.dfes_incident_no if obj.dfes_incident_no else None)
        row.write(col_no(), obj.job_code if obj.job_code else None)
        row.write(col_no(), smart_str( obj.get_prob_fire_level_display() if obj.prob_fire_level else None))
        row.write(col_no(), smart_str( obj.get_max_fire_level_display() if obj.max_fire_level else None))
        row.write(col_no(), smart_str( obj.media_alert_req if obj.media_alert_req else None))
        row.write(col_no(), smart_str( obj.investigation_req if obj.investigation_req else None))
        row.write(col_no(), smart_str( obj.fire_position if obj.fire_position else None))
        #row.write(col_no(), smart_str( obj.origin_point) )
        #row.write(col_no(), smart_str( obj.fire_boundary) )
        row.write(col_no(), smart_str( obj.fire_not_found if obj.fire_not_found else None))
        row.write(col_no(), smart_str( obj.other_info if obj.other_info else None))
        row.write(col_no(), smart_str( obj.cause if obj.cause else None))
        row.write(col_no(), smart_str( obj.other_cause if obj.other_cause else None))
        row.write(col_no(), smart_str( obj.field_officer.get_full_name() if obj.field_officer else None ) )
        row.write(col_no(), smart_str( obj.duty_officer.get_full_name() if obj.duty_officer else None ) )
        row.write(col_no(), smart_str( obj.init_authorised_by.get_full_name() if obj.init_authorised_by else None ) )
        row.write(col_no(), smart_str( obj.init_authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.init_authorised_date else None) )
        row.write(col_no(), smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ) )
        row.write(col_no(), smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None) )
        row.write(col_no(), smart_str( obj.dispatch_pw_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_pw_date else None) )
        row.write(col_no(), smart_str( obj.dispatch_aerial_date.strftime('%Y-%m-%d %H:%M:%S') if obj.dispatch_aerial_date else None) )
        row.write(col_no(), smart_str( obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else None) )
        row.write(col_no(), smart_str( obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else None) )
        row.write(col_no(), smart_str( obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else None) )
        row.write(col_no(), smart_str( obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else None) )
        #row.write(col_no(), smart_str( '; '.join(['(fuel_type={}, ros={}, flame_height={})'.format(i.fuel_type, i.ros, i.flame_height) for i in obj.fire_behaviour.all()])) if obj.fire_behaviour.all() else None )
        row.write(col_no(), smart_str( obj.first_attack if obj.first_attack else None))
        row.write(col_no(), smart_str( obj.other_first_attack if obj.other_first_attack else None))
        row.write(col_no(), smart_str( obj.initial_control if obj.initial_control else None))
        row.write(col_no(), smart_str( obj.other_initial_control if obj.other_initial_control else None))
        row.write(col_no(), smart_str( obj.final_control if obj.final_control else None))
        row.write(col_no(), smart_str( obj.other_final_control if obj.other_final_control else None))
        row.write(col_no(), smart_str( obj.arson_squad_notified if obj.arson_squad_notified else None))
        row.write(col_no(), obj.offence_no if obj.offence_no else None)
        row.write(col_no(), obj.area if obj.area else None)
        row.write(col_no(), smart_str( obj.authorised_by.get_full_name() if obj.authorised_by else None ) )
        row.write(col_no(), smart_str( obj.authorised_date.strftime('%Y-%m-%d %H:%M:%S') if obj.authorised_date else None ) )
        row.write(col_no(), smart_str( obj.get_report_status_display() if obj.report_status else None))
        row.write(col_no(), smart_str( '; '.join(['(name={}, area={})'.format(i.tenure.name, i.area) for i in obj.tenures_burnt.all()]) ))
        row.write(col_no(), smart_str( '; '.join(['(name={}, number={})'.format(i.damage_type.name, i.number) for i in obj.damages.all()]) if obj.damages.all() else None))
        row.write(col_no(), smart_str( '; '.join(['(name={}, number={})'.format(i.injury_type.name, i.number) for i in obj.injuries.all()]) if obj.injuries.all() else None ))

    book.save(response)

    return response
export_final_csv.short_description = u"Export Excel"



def dms_coordinate(point):
    if not point:
        return None

    c=LatLon.LatLon(LatLon.Longitude(point.get_x()), LatLon.Latitude(point.get_y()))
    latlon = c.to_string('d% %m% %S% %H')
    lon = latlon[0].split(' ')
    lat = latlon[1].split(' ')

    # need to format float number (seconds) to 1 dp
    lon[2] = str(round(eval(lon[2]), 1))
    lat[2] = str(round(eval(lat[2]), 1))

    # Degrees Minutes Seconds Hemisphere
    lat_str = lat[0] + u'\N{DEGREE SIGN} ' + lat[1].zfill(2) + '\' ' + lat[2].zfill(4) + '\" ' + lat[3]
    lon_str = lon[0] + u'\N{DEGREE SIGN} ' + lon[1].zfill(2) + '\' ' + lon[2].zfill(4) + '\" ' + lon[3]

    return 'Lat/Lon ' + lat_str + ', ' + lon_str

    


def generate_pdf(tex_template_file,context):
    tex_doc = render_to_string(tex_template_file,context=context)
    tex_doc = tex_doc.encode('utf-8')

    foldername = tempfile.mkdtemp()
    tex_filename = os.path.join(foldername,"{}.tex".format(os.path.splitext(os.path.basename(tex_template_file))[0]))
    pdf_filename = os.path.join(foldername,"{}.pdf".format(os.path.splitext(os.path.basename(tex_template_file))[0]))
    with open(tex_filename,"wb") as tex_file:
        tex_file.write(tex_doc)
    cmd = ['latexmk', '-cd', '-f', '-silent','-auxdir={}'.format(foldername),'-outdir={}'.format(foldername), '-pdf', tex_filename]
    subprocess.check_output(cmd)
    return (foldername,pdf_filename)


