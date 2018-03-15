from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from bfrs.models import (Bushfire, BushfireSnapshot, District, Region,
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

def users_group():
    return Group.objects.get(name='Users')

def fssdrs_group():
    return Group.objects.get(name='FSS Datasets and Reporting Services')

def can_maintain_data(user):
    return fssdrs_group() in user.groups.all() and not is_external_user(user)

def is_external_user(user):
    """ User group check added to prevent role-based internal users from having write access """
    try:
        return user.email.split('@')[1].lower() not in settings.INTERNAL_EMAIL or not user.groups.filter(name__in=['Users', 'FSS Datasets and Reporting Services']).exists()
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
            currently, can't find any code call this method
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

    if cur_obj.report_status != Bushfire.STATUS_INITIAL:
        #bushfire report is submitted, can't invalidate it
        return (obj,False)

    if cur_obj.district == obj.district:
        #district isn't changed, no need to invalidate it
        return (obj,False)

    with transaction.atomic():
        #invalidate the current object
        cur_obj.report_status = Bushfire.STATUS_INVALIDATED
        cur_obj.modifier = user
        cur_obj.sss_id = None
        # link the old invalidate bushfire to the new (valid) bushfire - fwd link
        cur_obj.valid_bushfire = obj
        cur_obj.save()

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
        cur_obj.save()

        serialize_bushfire('Final', 'Update District ({} --> {})'.format(cur_obj.district.code, obj.district.code), obj)

    return (obj,True)

def check_district_changed(request, obj, form):
    """
    Checks if district is changed from within the bushfire reporting system (FSSDRS Group can do this)
    Further, primary use case is to update the district from SSS, which then executes the equiv code below from bfrs/api.py
    """
    if request.POST.has_key('district') and not request.POST.get('district'):
        return None

    if obj:
        cur_obj = Bushfire.objects.get(id=obj.id)
        district = District.objects.get(id=request.POST['district']) if request.POST.has_key('district') else None # get the district from the form
        if request.POST.has_key('action') and request.POST.get('action')=='invalidate' and cur_obj.report_status!=Bushfire.STATUS_INVALIDATED:
            obj.invalid_details = request.POST.get('invalid_details')
            obj.district = district
            obj.region = district.region
            obj,saved = invalidate_bushfire(obj, request.user,cur_obj)
            if not saved:
                obj.save()
            return HttpResponseRedirect(reverse("home"))

        #elif district != cur_obj.district and not request.POST.has_key('fire_not_found'):
        elif district != cur_obj.district :
            #if cur_obj.fire_not_found and form.is_valid():
            if form.is_valid():
                # logic below to save object, present to allow final form change from fire_not_found=True --> to fire_not_found=False. Will allow correct fire_number invalidation
                obj = form.save(commit=False)
                obj.modifier = request.user
                obj.region = cur_obj.region # this will allow invalidate_bushfire() to invalidate and create the links as necessary if user confirms in the confirm page
                obj.district = cur_obj.district
                obj.fire_number = cur_obj.fire_number
                obj.save()

            message = 'District has changed (from {} to {}). This action will invalidate the existing bushfire and create  a new bushfire with the new district, and a new fire number.'.format(
                cur_obj.district.name,
                district.name
            )
            context={
                'action': 'invalidate',
                'district': district.id,
                'message': message,
            }
            return TemplateResponse(request, 'bfrs/confirm.html', context=context)

    return None


def authorise_report(request, obj):
    """ Sets the
        1. initial report to 'Submitted' status, or
        2. final report to 'Authorisd' status
    """
    template_summary = 'bfrs/detail_summary.html'
    template_mandatory_fields = 'bfrs/mandatory_fields.html'
    context = {
        'is_authorised': True,
        'object': obj,
        'snapshot': obj,
        'damages': obj.damages,
        'injuries': obj.injuries,
        'tenures_burnt': obj.tenures_burnt.order_by('id'),
    }

    if request.POST.has_key('submit_initial') or request.POST.has_key('_save_and_submit'):
        action = request.POST.get('submit_initial') if request.POST.has_key('submit_initial') else request.POST.get('_save_and_submit')
        if action == 'Submit':
            context['action'] = action
            context['initial'] = True
            context['mandatory_fields'] = check_mandatory_fields(obj, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS)

            if context['mandatory_fields']:
                return TemplateResponse(request, template_mandatory_fields, context=context)

            return TemplateResponse(request, template_summary, context=context)

    elif request.POST.has_key('authorise_final'):
        action = request.POST.get('authorise_final')
        if action == 'Authorise':
            context['action'] = action
            context['final'] = True
            fields = AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_FIELDS
            dep_fields = AUTH_MANDATORY_DEP_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_DEP_FIELDS
            context['mandatory_fields'] = check_mandatory_fields(obj, fields, dep_fields, AUTH_MANDATORY_FORMSETS)

            if context['mandatory_fields']:
                return TemplateResponse(request, template_mandatory_fields, context=context)

            return TemplateResponse(request, template_summary, context=context)

    elif request.POST.has_key('_save') and obj.is_final_authorised:
        # the '_save' component will ensure all mandatory fields are (still) completed if FSSDRS group attempt to re-save after obj has already been final authorised
        action = request.POST.get('_save')
        if action == 'Authorise' or action == 'Save final':
            context['action'] = action
            context['final'] = True

            context['mandatory_fields'] = check_mandatory_fields(obj, SUBMIT_MANDATORY_FIELDS, SUBMIT_MANDATORY_DEP_FIELDS, SUBMIT_MANDATORY_FORMSETS)
            fields = AUTH_MANDATORY_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_FIELDS
            dep_fields = AUTH_MANDATORY_DEP_FIELDS_FIRE_NOT_FOUND if obj.fire_not_found else AUTH_MANDATORY_DEP_FIELDS
            context['mandatory_fields'] = context['mandatory_fields'] + check_mandatory_fields(obj, fields, dep_fields, AUTH_MANDATORY_FORMSETS)

            if not obj.fire_not_found and context['mandatory_fields']:
                logger.info('Delete Authorisation - FSSDRS user {} attempted to save an already Authorised/Reviewed report {}, with missing fields\n{}'.format(
                    request.user.get_full_name(), obj.fire_number, context['mandatory_fields']
                ))
                update_status(request, obj, 'delete_authorisation_(missing_fields_-_FSSDRS)')
                return HttpResponseRedirect(reverse("home"))

            elif context['mandatory_fields']:
                return TemplateResponse(request, template_mandatory_fields, context=context)

            serialize_bushfire('Final', 'Post Authorised Update', obj)
            return HttpResponseRedirect(reverse("home"))

    return None

def create_areas_burnt(bushfire, tenure_layers):
    """
    Creates the initial bushfire record together with AreaBurnt FormSet from BushfireUpdateView (Operates on data dict from SSS)
    Uses sss_dict - used by get_context_data, to display initial sss_data supplied from SSS system
    """
    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for layer in tenure_layers:
        for d in tenure_layers[layer]['areas']:
            aggregated_sums[d["category"]] += d["area"]


    area_unknown = 0.0
    category_unknown = []
    new_area_burnt_list = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_list.append({
                'tenure': tenure_qs[0],
                'area': round(area, 2)
            })

        elif area:
            area_unknown += area
            if category not in category_unknown:
                category_unknown.append(category)

    if area_unknown > 0:
        new_area_burnt_list.append({'tenure': Tenure.objects.get(name='Unknown'), 'area': round(area_unknown, 2)})
        logger.info('Unknown Tenure categories: ({}). May need to add these categories to the Tenure Table'.format(category_unknown))

    AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=len(new_area_burnt_list), min_num=0, validate_min=True, exclude=())
    area_burnt_formset = AreaBurntFormSet(instance=bushfire, prefix='area_burnt_fs')
    for subform, data in zip(area_burnt_formset.forms, new_area_burnt_list):
        subform.initial = data

    return area_burnt_formset

def update_areas_burnt(bushfire, tenure_layers):
    """
    Updates AreaBurnt model attached to the bushfire record from api.py, via REST API (Operates on data dict from SSS)
    Uses sss_dict
    """

    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for layer in tenure_layers:
        for d in tenure_layers[layer]['areas']:
            aggregated_sums[d["category"]] += d["area"]

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
        new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=Tenure.objects.get(name='Unknown'), area=round(area_unknown, 2)))
        logger.info('Unknown Tenure categories: ({}). May need to add these categories to the Tenure Table'.format(category_unknown))

    try:
        with transaction.atomic():
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_area_burnt_object)
    except IntegrityError:
        return 0

    return 1

def update_areas_burnt_fs(bushfire, area_burnt_formset):
    """
    Creates the AreaBurnt Model, from the area_burnt_formset

    At first object create time, formset values are saved to the newly created bushfire object
    """
    deleted_fs_tenure = []
    updated_fs_object = []
    for form in area_burnt_formset:
        if not form.cleaned_data:
            continue
        tenure = form.cleaned_data.get('tenure')
        area = form.cleaned_data.get('area')
        remove = form.cleaned_data.get('DELETE')

        #if either injury_type or number is null, remove will be set tp True in BaseInjuryFormSet
        if remove:
            if tenure:
                #this object exists in database, removed by user
                deleted_fs_tenure.append(tenure)
            else:
                #this object doesn't exist in database,ignore it
                pass
        elif form.is_valid():
            #this is a valid object
            updated_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, area=area))

    try:
        with transaction.atomic():
            #delete removed objects
            if deleted_fs_tenure:
                AreaBurnt.objects.filter(bushfire=bushfire,tenure__in=deleted_fs_tenure).delete()
            #update changed objects
            for obj in updated_fs_object:
                AreaBurnt.objects.update_or_create(bushfire=obj.bushfire,tenure=obj.tenure,defaults={"area":area})
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

def mail_url(request, bushfire, status='initial'):
    if status == 'initial':
        return "http://" + request.get_host() + reverse('bushfire:initial_snapshot', kwargs={'pk':bushfire.id})
    if status == 'final':
        return "http://" + request.get_host() + reverse('bushfire:final_snapshot', kwargs={'pk':bushfire.id})


def update_status(request, bushfire, action):

    notification = {}
    if action == 'Submit' and bushfire.report_status==Bushfire.STATUS_INITIAL:
        bushfire.init_authorised_by = request.user
        bushfire.init_authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
        bushfire.save()
        serialize_bushfire('initial', action, bushfire)

        # send emails
        resp = rdo_email(bushfire, mail_url(request, bushfire))
        notification['RDO'] = 'Email Sent' if resp else 'Email failed'

        resp = dfes_email(bushfire, mail_url(request, bushfire))
        notification['DFES'] = 'Email Sent' if resp else 'Email failed'

        resp = police_email(bushfire, mail_url(request, bushfire))
        notification['POLICE'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.park_trail_impacted:
            resp = pvs_email(bushfire, mail_url(request, bushfire))
            notification['PVS'] = 'Email Sent' if resp else 'Email failed'

        if bushfire.media_alert_req:
            resp = pica_email(bushfire, mail_url(request, bushfire))
            notification['PICA'] = 'Email Sent' if resp else 'Email failed'

            resp = pica_sms(bushfire, mail_url(request, bushfire))
            notification['PICA SMS'] = 'SMS Sent' if resp else 'SMS failed'

        bushfire.area = None # reset bushfire area
        bushfire.final_fire_boundary = False # used to check if final boundary is updated in Final Report template - allows to toggle show()/hide() area_limit widget via js
        bushfire.save()

    elif action == 'Authorise' and bushfire.report_status==Bushfire.STATUS_INITIAL_AUTHORISED:
        bushfire.authorised_by = request.user
        bushfire.authorised_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        bushfire.save()
        serialize_bushfire('final', action, bushfire)

        # send emails
        resp = fssdrs_email(bushfire, mail_url(request, bushfire, status='final'), status='final')
        notification['FSSDRS-Auth'] = 'Email Sent' if resp else 'Email failed'

        bushfire.save()

    elif action == 'mark_reviewed' and bushfire.can_review:
        bushfire.reviewed_by = request.user
        bushfire.reviewed_date = datetime.now(tz=pytz.utc)
        bushfire.report_status = Bushfire.STATUS_REVIEWED
        bushfire.save()
        serialize_bushfire('review', action, bushfire)

        # send emails
        resp = fssdrs_email(bushfire, mail_url(request, bushfire, status='review'), status='review')
        notification['FSSDRS-Auth'] = 'Email Sent' if resp else 'Email failed'

        bushfire.save()

    elif (action == 'delete_final_authorisation' or action == 'delete_authorisation_(missing_fields_-_FSSDRS)') and bushfire.is_final_authorised:
        if bushfire.is_reviewed:
            bushfire.reviewed_by = None
            bushfire.reviewed_date = None

        if not bushfire.area:
            bushfire.final_fire_boundary = False

        bushfire.authorised_by = None
        bushfire.authorised_date = None
        bushfire.report_status = Bushfire.STATUS_INITIAL_AUTHORISED
        serialize_bushfire(action, action, bushfire)
        bushfire.save()

    elif action == 'delete_review' and bushfire.is_reviewed:
        bushfire.reviewed_by = None
        bushfire.reviewed_date = None
        bushfire.report_status = Bushfire.STATUS_FINAL_AUTHORISED
        serialize_bushfire(action, action, bushfire)
        bushfire.save()

    return notification

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

def rdo_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

    region_name = bushfire.region.name.upper()
    to_email = getattr(settings, region_name.replace(' ', '_') + '_EMAIL')
    subject = 'RDO Email - {}, Initial Bushfire submitted - {}'.format(region_name, bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'RDO Email - {0}, {1}\n\nInitial Bushfire has been submitted and is located at <a href="{2}">{2}</a><br><br>'.format(region_name, bushfire.fire_number, url)
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=to_email, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()

    if not ret:
        msg = 'Failed to send RDO Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)

    return ret


def pvs_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

    subject = 'PVS Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'PVS Email - {0}\n\nInitial Bushfire has been submitted and is located at <a href="{1}">{1}</a><br><br>'.format(bushfire.fire_number, url)
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.PVS_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()

    if not ret:
        msg = 'Failed to send PVS Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)

    return ret

def fpc_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

    subject = 'FPC Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'FPC Email - {0}\n\nInitial Bushfire has been submitted and is located at <a href="{1}">{1}</a><br><br>'.format(bushfire.fire_number, url)
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.FPC_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()

    if not ret:
        msg = 'Failed to send FPC Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)

    return ret


def pica_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

    subject = 'PICA Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'PICA Email - {0}\n\nInitial Bushfire has been submitted and is located at <a href="{1}">{1}</a><br><br>'.format(bushfire.fire_number, url)
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.PICA_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()

    if not ret:
        msg = 'Failed to send PICA Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)

    return ret


def pica_sms(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

#    if 'bfrs-prod' not in os.getcwd():
#       return

    message = 'PICA SMS - {}\n\nInitial Bushfire has been submitted and is located at {}'.format(bushfire.fire_number, url)
    TO_SMS_ADDRESS = [phone_no + '@' + settings.SMS_POSTFIX for phone_no in settings.MEDIA_ALERT_SMS_TOADDRESS_MAP.values()]
    ret = send_mail('', message, settings.EMAIL_TO_SMS_FROMADDRESS, TO_SMS_ADDRESS)

    if not ret:
        msg = 'Failed to send PICA SMS. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)

    return ret


def dfes_email(bushfire, url):
    if (not settings.ALLOW_EMAIL_NOTIFICATION or
        bushfire.fire_number in settings.EMAIL_EXCLUSIONS or
        bushfire.dfes_incident_no != ''):
       return

    subject = 'DFES Email - Initial Bushfire submitted - {}'.format(bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = '---- PLEASE REPLY AS FOLLOWS: "<span style="color:red;">Incident: ABCDE12345</span>" on a single line without quotes (alphanumeric max. 32 chars) ----<br><br>DFES Email<br><br>Fire Number:{0}<br><br>(Lat/Lon) {1}<br><br>Initial Bushfire has been submitted and is located at <a href="{2}">{2}</a><br><br>'.format(bushfire.fire_number, bushfire.origin_point, url)
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.DFES_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()
    
    if not ret:
        msg = 'Failed to send DFES Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)
        
    return ret

def police_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION or bushfire.fire_number in settings.EMAIL_EXCLUSIONS:
       return

    subject = 'POLICE Email - Initial Bushfire submitted {}, and an investigation is required - {}'.format(bushfire.fire_number, 'Yes' if bushfire.investigation_req else 'No')
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'POLICE Email - {0}. Initial Bushfire has been submitted.<br><br>Investigation Required: {1}'.format(
        bushfire.fire_number, 'Yes' if bushfire.investigation_req else 'No'
    )
    body += notifications_to_html(bushfire, None)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.POLICE_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()
    
    if not ret:
        msg = 'Failed to send POLICE Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)
        
    return ret

def fssdrs_email(bushfire, url, status='final'):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'FSSDRS Email - Final Fire report has been authorised - {}'.format(bushfire.fire_number)
    if settings.ENV_TYPE != "PROD":
        subject += ' ({})'.format(settings.ENV_TYPE)

    body = 'FSSDRS Email - {0}\n\nreport has been authorised. User {1}, at {2}.\n\nThe report is located at <a href="{3}">{3}</a><br><br>'.format(
        bushfire.fire_number, bushfire.authorised_by, bushfire.authorised_date.astimezone(tz.gettz(settings.TIME_ZONE)).strftime('%Y-%m-%d %H:%M'), url
    )
    body += notifications_to_html(bushfire, url)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.FSSDRS_EMAIL, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
    message.content_subtype = 'html'
    ret = message.send()
    
    if not ret:
        msg = 'Failed to send FSSDRS Email. {}'.format(bushfire.fire_number)
        logger.error(msg)
        support_email(subject=msg, body=msg)
        
    return ret

def support_email(subject, body):
    if not settings.SUPPORT_EMAIL:
       return

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.SUPPORT_EMAIL)
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

    fssdrs_group, g_created = Group.objects.get_or_create(name=settings.FSSDRS_GROUP)
    if g_created:
        fssdrs_group.permissions = Permission.objects.filter(name__in=['Can add group', 'Can change group', 'Can add permission', 'Can change permission', 'Can add user', 'Can change user'])

    for user in User.objects.filter(email__in=settings.FSSDRS_USERS):
        if fssdrs_group not in user.groups.all():
            user.groups.add(fssdrs_group)
            logger.info('Adding user {} to group {}'.format(user.get_full_name(), fssdrs_group.name))

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
    request.session['refreshGokart'] = True
    request.session['region'] = region if region else 'null'
    request.session['district'] = district if district else 'null'
    request.session['id'] = fire_number if fire_number else 'null'

    if action:
        request.session['action'] = action
    else:
        request.session['action'] = 'create' if 'create' in request.get_full_path() else 'update'

def clear_gokart_session(request):
    #request.session['refreshGokart'] = 'null'
    request.session['region'] = 'null'
    request.session['district'] = 'null'
    #request.session['id'] = 'null'
    #request.session['action'] = 'null'


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


