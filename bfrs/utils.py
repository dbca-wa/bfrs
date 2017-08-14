from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from bfrs.models import (Bushfire, BushfireSnapshot, District, Region,
    AreaBurnt, Damage, Injury, Tenure,
    SNAPSHOT_INITIAL, SNAPSHOT_FINAL,
    DamageSnapshot, InjurySnapshot, AreaBurntSnapshot,
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
import requests
from requests.auth import HTTPBasicAuth

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

def fssdrs_group():
    return Group.objects.get(name='FSS Datasets and Reporting Services')

def can_maintain_data(user):
    return fssdrs_group() in user.groups.all() and not is_external_user(user)


def is_external_user(user):
    try:
        return user.email.split('@')[1].lower() not in settings.INTERNAL_EMAIL #['dpaw.wa.gov.au']
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
    for i in obj.damages.all():
        damage_obj, created = DamageSnapshot.objects.update_or_create(
            snapshot_id=s.id, snapshot_type=snapshot_type, damage_type=i.damage_type, number=i.number, creator=obj.modifier, modifier=obj.modifier
        )

    for i in obj.injuries.all():
        injury_obj, created = InjurySnapshot.objects.update_or_create(
            snapshot_id=s.id, snapshot_type=snapshot_type, injury_type=i.injury_type, number=i.number, creator=obj.modifier, modifier=obj.modifier
        )

    for i in obj.tenures_burnt.all():
        tenure_burnt_obj, created = AreaBurntSnapshot.objects.update_or_create(
            snapshot_id=s.id, snapshot_type=snapshot_type, tenure_id=i.tenure_id, area=i.area, creator=obj.modifier, modifier=obj.modifier
        )

def archive_snapshot(auth_type, action, obj):
        """ allows archicing of existing snapshot before overwriting """
        cur_snapshot_history = obj.snapshot_history.all()
        SnapshotHistory.objects.create(
            creator = obj.modifier,
            modifier = obj.modifier,
            auth_type = auth_type,
            action = action if action else 'Update',
            #snapshot = obj.initial_snapshot if auth_type =='initial' else obj.final_snapshot if obj.final_snapshot else '{"Deleted": True}',
            snapshot = obj.initial_snapshot if auth_type =='initial' else obj.final_snapshot if obj.final_snapshot else '{"Deleted": True}',
            prev_snapshot = cur_snapshot_history.latest('created') if cur_snapshot_history else None,
            bushfire_id = obj.id
        )

def invalidate_bushfire(obj, new_district, user):
    """ Invalidate the current bushfire, create new bushfire and update links, including historical links """
    if obj.district == new_district:
        return None

    with transaction.atomic():
        old_rpt_status = obj.report_status
        obj.report_status = Bushfire.STATUS_INVALIDATED
        obj.modifier = user
        obj.save()
        old_obj = deepcopy(obj)
        old_invalidated = old_obj.bushfire_invalidated.all()

        # create a new object as a copy of existing
        obj.pk = None

        # check if we have this district already in the list of invalidated linked bushfires, and re-use fire_number if so
        invalidated_objs = [invalidated_obj for invalidated_obj in old_invalidated if invalidated_obj.district==new_district]
        if invalidated_objs and invalidated_objs[0].report_status==Bushfire.STATUS_INVALIDATED:
            # re-use previous fire_number
            linked_bushfire = invalidated_objs[0]
            obj.fire_number = linked_bushfire.fire_number
            linked_bushfire.delete() # to avoid integrity constraint
        else:
            # create new fire_number
            obj.fire_number = ' '.join(['BF', str(obj.year), new_district.code, '{0:03d}'.format(obj.next_id(new_district))])

        obj.report_status = old_rpt_status
        obj.district = new_district
        obj.region = new_district.region
        obj.valid_bushfire = None
        obj.fire_not_found = False
        obj.save()

        # link the new bushfire to the old invalidated bushfire
        created = datetime.now(tz=pytz.utc)

        # copy all links from the above invalidated bushfire to the new bushfire
        if old_invalidated:
            for linked in old_invalidated:
                obj.bushfire_invalidated.add(linked)

        # link the old invalidate bushfire to the new (valid) bushfire - fwd link
        old_obj.valid_bushfire = obj
        old_obj.save()

        def copy_fk_records(obj_id, fk_set, create_new=True):
            # create duplicate injury records and associate them with the new object
            for record in fk_set.all():
                if create_new:
                    record.id = None
                record.bushfire_id = obj_id 
                record.save()

        copy_fk_records(obj.id, old_obj.damages)
        copy_fk_records(obj.id, old_obj.injuries)
        copy_fk_records(obj.id, old_obj.tenures_burnt)

        # update Bushfire Snapshots to the new bushfire_id and then create a new snapshot
        copy_fk_records(obj.id, old_obj.snapshots, create_new=False)
        serialize_bushfire('Final', 'Update District ({} --> {})'.format(old_obj.district.code, obj.district.code), obj)

        return obj
    return False

def check_district_changed(request, obj, form):
    """
    Checks if district is changed from within the bushfire reporting system (FSSDRS Group can do this)
    Further, primary use case is to update the district from SSS, which then executes the equiv code below from bfrs/api.py
    """
    if request.POST.has_key('district') and not request.POST.get('district'):
        return None

    if obj:
        cur_obj = Bushfire.objects.get(id=obj.id)
        #import ipdb; ipdb.set_trace()
        district = District.objects.get(id=request.POST['district']) if request.POST.has_key('district') else None # get the district from the form
        if request.POST.has_key('action') and request.POST.get('action')=='invalidate' and cur_obj.report_status!=Bushfire.STATUS_INVALIDATED:
            obj.invalid_details = request.POST.get('invalid_details')
            obj.save()
            obj = invalidate_bushfire(obj, district, request.user)
            return HttpResponseRedirect(reverse("home"))

        elif district != cur_obj.district and not request.POST.has_key('fire_not_found'):
            if cur_obj.fire_not_found and form.is_valid():
                # logic below to save object, present to allow final form change from fire_not_found=True --> to fire_not_found=False. Will allow correct fire_number invalidation
                obj = form.save(commit=False)
                obj.modifier = request.user
                obj.region = cur_obj.region # this will allow invalidate_bushfire() to invalidate and create the links as necessary
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

            #import ipdb; ipdb.set_trace()
            if not obj.fire_not_found and context['mandatory_fields']:
                logger.info('Delete Authorisation - FSSDRS user {} attempted to save an already Authorised/Reviewed report {}, with missing fields\n{}'.format(
                    request.user.get_full_name(), obj.fire_number, context['mandatory_fields']
                ))
                update_status(request, obj, 'delete_authorisation_(missing_fields_-_FSSDRS)')
                return HttpResponseRedirect(reverse("home"))

#            if not obj.fire_not_found and context['mandatory_fields']:
#                context.update({
#                    'action': 'delete_final_authorisation',
#                    'message': 'Fire not found has been reset to "No", and mandatory fields are missing. This action will save the report and also delete the existing {}'.format('authorisation and review' if obj.is_reviewed else 'authorisation'),
#                    'fire_not_found_reset': True,
#                    'snapshot': obj,
#                })
#                return TemplateResponse(request, 'bfrs/detail_summary.html', context=context)

            elif context['mandatory_fields']:
                return TemplateResponse(request, template_mandatory_fields, context=context)

            serialize_bushfire('Final', 'Post Authorised Update', obj)
            return HttpResponseRedirect(reverse("home"))

    return None

def create_areas_burnt(bushfire, area_burnt_list):
    """
    Creates the initial bushfire record together with AreaBurnt FormSet from BushfireUpdateView (Operates on data dict from SSS)
    Uses sss_dict - used by get_context_data, to display initial sss_data supplied from SSS system
    """
    #t=Tenure.objects.all()[0]
    #initial = [{'tenure': t, 'area':0.0, 'name':'ABC', 'other':'Other'}]

    #if not area_burnt_list:
    #    return 1

    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for d in area_burnt_list:
        aggregated_sums[d["category"]] += d["area"]

    area_other = 0.0
    new_area_burnt_list = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_list.append({
                'tenure': tenure_qs[0],
                'area': round(area, 2)
            })

        elif area:
            area_other += area

    if area_other > 0:
        new_area_burnt_list.append({'tenure': Tenure.objects.get(name='Other'), 'area': round(area_other, 2)})

    AreaBurntFormSet = inlineformset_factory(Bushfire, AreaBurnt, extra=len(new_area_burnt_list), min_num=0, validate_min=True, exclude=())
    area_burnt_formset = AreaBurntFormSet(instance=bushfire, prefix='area_burnt_fs')
    for subform, data in zip(area_burnt_formset.forms, new_area_burnt_list):
        subform.initial = data

    return area_burnt_formset

def update_areas_burnt(bushfire, area_burnt_list):
    """
    Updates AreaBurnt model attached to the bushfire record from api.py, via REST API (Operates on data dict from SSS)
    Uses sss_dict
    """
    #if not area_burnt_list:
    #    return 1

    # aggregate the area's in like tenure types
    aggregated_sums = defaultdict(float)
    for d in area_burnt_list:
        aggregated_sums[d["category"]] += d["area"]

    area_other = 0.0
    new_area_burnt_object = []
    for category, area in aggregated_sums.iteritems():
        tenure_qs = Tenure.objects.filter(name=category)
        if tenure_qs:
            new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure_qs[0], area=round(area, 2)))
        elif area:
            area_other += area

    if area_other > 0:
        new_area_burnt_object.append(AreaBurnt(bushfire=bushfire, tenure=Tenure.objects.get(name='Other'), area=round(area, 2)))

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
#    if not area_burnt_formset:
#        return 1

    new_fs_object = []
    for form in area_burnt_formset:
        if form.is_valid():
            tenure = form.cleaned_data.get('tenure')
            area = form.cleaned_data.get('area')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (tenure):
                new_fs_object.append(AreaBurnt(bushfire=bushfire, tenure=tenure, area=area))

    try:
        with transaction.atomic():
            AreaBurnt.objects.filter(bushfire=bushfire).delete()
            AreaBurnt.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_injury_fs(bushfire, injury_formset):
    if not injury_formset:
        return 1

    new_fs_object = []
    for form in injury_formset:
        if form.is_valid():
            injury_type = form.cleaned_data.get('injury_type')
            number = form.cleaned_data.get('number')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (injury_type and number):
                new_fs_object.append(Injury(bushfire=bushfire, injury_type=injury_type, number=number))

    try:
        with transaction.atomic():
            Injury.objects.filter(bushfire=bushfire).delete()
            if not bushfire.injury_unknown:
                Injury.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def update_damage_fs(bushfire, damage_formset):
    if not damage_formset:
        return 1

    new_fs_object = []
    for form in damage_formset:
        if form.is_valid():
            damage_type = form.cleaned_data.get('damage_type')
            number = form.cleaned_data.get('number')
            remove = form.cleaned_data.get('DELETE')

            if not remove and (damage_type and number):
                new_fs_object.append(Damage(bushfire=bushfire, damage_type=damage_type, number=number))

    try:
        with transaction.atomic():
            Damage.objects.filter(bushfire=bushfire).delete()
            if not bushfire.damage_unknown:
                Damage.objects.bulk_create(new_fs_object)
    except IntegrityError:
        return 0

    return 1

def mail_url(request, bushfire, status='initial'):
    if status == 'initial':
        return "http://" + request.get_host() + reverse('bushfire:bushfire_initial', kwargs={'pk':bushfire.id})
    if status == 'final':
        return "http://" + request.get_host() + reverse('bushfire:bushfire_final', kwargs={'pk':bushfire.id})


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
    'fire_position', 'origin_point',
    'tenure', 'duty_officer',
    'dispatch_pw', 'dispatch_pw_date', 'dispatch_aerial', 'dispatch_aerial_date',
    'initial_control', 'initial_area',
    'prob_fire_level', 'investigation_req',
    'media_alert_req', 'park_trail_impacted',
    'other_info',
]
#def _notifications_to_text(bushfire):
#    d = [(bushfire._meta.get_field(i).verbose_name, str(getattr(bushfire, i))) for i in NOTIFICATION_FIELDS]
#    ordered_dict = OrderedDict(d)
#
#    msg = ''
#    for k,v in ordered_dict.iteritems():
#        msg +=  '{}:\t{}\n'.format(k, v).expandtabs(60)
#
#    return msg

def notifications_to_html(bushfire):
    d = [(bushfire._meta.get_field(i).verbose_name, str(getattr(bushfire, i))) for i in NOTIFICATION_FIELDS]
    ordered_dict = OrderedDict(d)

    msg = ''
    msg += '<table>'
    for k,v in ordered_dict.iteritems():
        if v == 'None' or not v:
            v = '-'
        elif v == 'False':
            v = 'No'
        elif v == 'True':
            v = 'Yes'
        elif k == bushfire._meta.get_field('dispatch_pw').verbose_name:
            v = 'Yes' if v == '1' else 'No'
            
        msg += '<tr> <th style="text-align: left;">{}</th> <td>{}</td> </tr>'.format(k, v)
    msg += '</table">'

    return msg

def rdo_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'RDO Email - Initial report submitted - {}'.format(bushfire.fire_number)

    body = 'RDO Email - {0}\n\nInitial report has been submitted and is located at <a href="{1}">{1}</a><br><br>'.format(bushfire.fire_number, url)
    body += notifications_to_html(bushfire)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.RDO_EMAIL)
    message.content_subtype = 'html'
    message.send()

#def _rdo_email(bushfire, url):
#    if not settings.ALLOW_EMAIL_NOTIFICATION:
#       return
#
#    subject = 'RDO Email - Initial report submitted - {}'.format(bushfire.fire_number)
#    message = 'RDO Email - {}\n\nInitial report has been submitted and is located at {}\n\n{}'.format(
#        bushfire.fire_number, url, notifications_to_text2(bushfire)
#    )
#
#    return send_mail(subject, message, settings.FROM_EMAIL, settings.RDO_EMAIL)

def pvs_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'PVS Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'PVS Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.PVS_EMAIL)

def fpc_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'FPC Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'FPC Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.FPC_EMAIL)

def pica_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'PICA Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = 'PICA Email - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.PICA_EMAIL)

def pica_sms(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    message = 'PICA SMS - {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, url)

    return send_mail('', message, settings.EMAIL_TO_SMS_FROMADDRESS, settings.MEDIA_ALERT_SMS_TOADDRESS)

def dfes_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'DFES Email - Initial report submitted - {}'.format(bushfire.fire_number)
    message = '---- PLEASE REPLY ABOVE THIS LINE ----\n\nDFES Email\n\nFire Number:{}\n\n(Lat/Lon) {}\n\nInitial report has been submitted and is located at {}'.format(bushfire.fire_number, bushfire.origin_point, url)

    return send_mail(subject, message, settings.FROM_EMAIL, settings.DFES_EMAIL)

def police_email(bushfire, url):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'POLICE Email - Initial report submitted and an investigation is required- {}'.format(bushfire.fire_number)
    message = 'POLICE Email - {}\n\nInitial report has been submitted and is located at {}\n\nInvestigation Required: {}'.format(
        bushfire.fire_number, url, 'Yes' if bushfire.investigation_req else 'No'
    )

    return send_mail(subject, message, settings.FROM_EMAIL, settings.POLICE_EMAIL)

def fssdrs_email(bushfire, url, status='final'):
    if not settings.ALLOW_EMAIL_NOTIFICATION:
       return

    subject = 'FSSDRS Email - Final Fire report has been authorised - {}'.format(bushfire.fire_number)
    message = 'FSSDRS Email - {}\n\nreport has been authorised. User {}, at {}.\n\nThe report is located at {}'.format(
        bushfire.fire_number, bushfire.authorised_by, bushfire.authorised_date, url
    )
    return send_mail(subject, message, settings.FROM_EMAIL, settings.FSSDRS_EMAIL)

def create_other_user():
    return User.objects.get_or_create(username='other', first_name='Other', last_name='Contact')

def create_admin_user():
    return User.objects.get_or_create(username='admin',
        defaults={'is_active':'False', 'first_name':'Admin', 'last_name':'Admin', 'email':'admin@{}'.format(settings.INTERNAL_EMAIL[0]) }
    )

def add_users_to_fssdrs_group():

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

def update_users_from_active_directory(sso_users):
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


def update_users():
    resp=requests.get(url=settings.URL_SSO, auth=HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO))

    for user in resp.json()['objects']:
        try:
            if user['email'] and user['email'].split('@')[-1].lower() in settings.INTERNAL_EMAIL:
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


    update_users_from_active_directory(resp)
    add_users_to_fssdrs_group()
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
    hdr.write(col_no(), "Fuel Type")
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


