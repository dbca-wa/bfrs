import requests
import json
import itertools
import traceback
import os
from datetime import datetime,timedelta
from collections import defaultdict, OrderedDict

from django.core import serializers
from django.conf import settings
from django.db import IntegrityError, transaction

from bfrs.models import (Bushfire, Tenure,AreaBurntSnapshot,AreaBurnt)
from bfrs import utils

BUSHFIRE=1
SNAPSHOT=2

SCOPES_DESC = {
    BUSHFIRE : "Bushfire",
    SNAPSHOT : "Snapshot"
}

GRID_DATA = 1
ORIGIN_POINT_TENURE = 2
BURNT_AREA = 4

DATATYPES_DESC = {
    GRID_DATA : "Grid Data",
    ORIGIN_POINT_TENURE :"The tenure of OriginPoint",
    BURNT_AREA : "Burnt Area"
}

ALL_DATA = GRID_DATA | ORIGIN_POINT_TENURE

def get_refresh_status_file():
    status_file = os.path.join(settings.BASE_DIR,"logs","bfrs-refresh-data-{}.json".format(settings.ENV_TYPE))
    if not os.path.exists(os.path.dirname(status_file)):
        os.mkdir(os.path.exists(os.path.dirname(status_file)))

    return status_file


def get_refresh_status(resume=True):
    status_file = get_refresh_status_file()

    if resume:
        if os.path.exists(status_file):
            try:
                with open(status_file) as f:
                    status = json.loads(f.read())
            except:
                status = {}
                os.remove(status_file)
        else:
            status = {}
    else:
        if os.path.exists(status_file):
            os.remove(status_file)
        status = {}

    return status


def save_refresh_status(status):
    status_file = get_refresh_status_file()
    if not status:
        os.remove(status_file)
        return

    status_content = json.dumps(status,indent=4)
    with open(status_file,"w") as f:
        f.write(status_content)

def get_last_refreshed_bushfireid(status,scope,data_types):
    bfid = None
    if "progress" not in status:
        status["progress"] = {}
    progress_status = status["progress"]

    #initialize progress status
    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        if sname not in progress_status:
            progress_status[sname] = {
                "id":s,
            }
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if data_types & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if tname not in progress_status[sname]:
                progress_status[sname][tname] = {
                    "id":t,
                }
    #get min bfid
    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if data_types & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if "last_refreshed_id" not in progress_status[sname][tname]:
                return None
            elif bfid is None or  bfid > progress_status[sname][tname]["last_refreshed_id"]:
                bfid = progress_status[sname][tname]["last_refreshed_id"]
    return bfid

def set_last_refreshed_bushfireid(status,scope,data_types,bfid):
    if "progress" not in status:
        status["progress"] = {}
    progress_status = status["progress"]

    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if data_types & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if "last_refreshed_id"  not in progress_status[sname][tname]:
                progress_status[sname][tname]["last_refreshed_id"] = bfid
            elif progress_status[sname][tname]["last_refreshed_id"] < bfid:
                progress_status[sname][tname]["last_refreshed_id"] = bfid

def get_scope_and_datatypes(status,bushfire,scope,data_types):
    progress_status = status["progress"]
    result = {}
    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if data_types & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            bfid = progress_status[sname][tname].get("last_refreshed_id")
            if not bfid or bushfire.id > bfid:
                if s in result:
                    result[s] = result[s] | t
                else:
                    result[s] = t

    #merge scope if possible
    result2 = {}
    for s,data_types in result.items():
        if data_types in result2:
            result2[data_types] = result2[data_types] | s
        else:
            result2[data_types] = s

    #return list of (scope,data_types)
    return [(s,t) for t,s in result2.items()]


def add_warnings(status,bushfire,scope,data_types,warnings):
    if not warnings:
        return

    if "warnings" not in status:
        status["warnings"] = {}
    all_warnings = status["warnings"]

    warning_key = "{}:{}".format(bushfire.id,bushfire.fire_number)
    if warning_key not in all_warnings:
        all_warnings[warning_key] = []

    #delete existing warnings
    index = len(all_warnings[warning_key]) - 1
    while index >= 0:
        try:
            bfwarnings = all_warnings[warning_key][index]
            if bfwarnings[0][1] & scope == 0:
                continue
            if bfwarnings[0][2] & data_types == 0:
                continue
            del all_warnings[warning_key][index]
        finally:
            index -= 1
    #add the new warnings   
    for warning in warnings:
        all_warnings[warning_key].append(warning)

def refresh_all_spatial_data(scope=BUSHFIRE,data_types = 0,resume=True,size=0):
    if data_types == 0 or scope == 0:
        return

    all_warnings = OrderedDict()
    status = get_refresh_status(resume)
    last_refreshed_id = get_last_refreshed_bushfireid(status,scope,data_types)
    try:
        refresh_status_file = os.path.join(settings.BASE_DIR,"logs","")
        warnings = {}
        counter = 0
        start_time = datetime.now()
        save_interval = timedelta(minutes=2)
        for bushfire in Bushfire.objects.all().order_by("id") if last_refreshed_id is None else Bushfire.objects.filter(id__gt=last_refreshed_id).order_by("id"):
            scope_types = get_scope_and_datatypes(status,bushfire,scope,data_types)
            warning_key = (bushfire.id,bushfire.fire_number)
            for s,t in scope_types:
                warnings = _refresh_spatial_data(bushfire,scope=s,data_types=t)
                set_last_refreshed_bushfireid(status,s,t,bushfire.id)
                if warnings:
                    add_warnings(status,bushfire,s,t,warnings)
                    if warning_key in all_warnings:
                        for w in warnings:
                            all_warnings[warning_key].append(w)
                    else:
                        all_warnings[warning_key] = warnings
            counter += 1
            if size and counter >= size:
                break
            if datetime.now() - start_time >= save_interval:
                save_refresh_status(status)
                start_time = datetime.now()
    except Exception as ex:
        print("Failed to refresh the spatial data for bushfire report({}),{}".format(bushfire.fire_number,str(ex)))
        traceback.print_exc()


    save_refresh_status(status)
    
    if all_warnings:
        for bushfire,warnings in all_warnings.items():
            print("================All warnings for bushfire({})==========================".format(bushfire))
            for key,msgs in warnings:
                if key[1] == BUSHFIRE:
                    print("    All {}  warnings for bushfire({})".format(key[2],key[0]))
                else:
                    print("    All {}  warnings for bushfire({})'s snapshot({})".format(key[2],bushfire.id,key[0]))
                index = 0
                for msg in msgs:
                    index += 1
                    print("        {}:{}".format(index,msg))

def _refresh_spatial_data(bushfire,scope=BUSHFIRE,data_types=0):
    warnings = [] 
    if data_types == 0 or scope == 0:
        return warnings

    if warnings is None:
        warnings = {}
        print_warnings = True
    else:
        print_warnings = False

    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,basestring):
        bushfire = Bushfire.objects.get(fire_number=bushfire)
    elif not isinstance(bushfire,Bushfire):
        raise Exception("Bushfire should be bushfire id or fire number or Bushfire instance")

    if scope & (BUSHFIRE | SNAPSHOT) == (BUSHFIRE | SNAPSHOT) :
        bushfires = itertools.chain([bushfire],bushfire.snapshots.all())
    elif scope == BUSHFIRE :
        bushfires = [bushfire]
    elif scope == SNAPSHOT :
        bushfires = bushfire.snapshots.all()
    else:
        raise ("Scope({}) Not Support".format(scope))
    
    for bf in bushfires:
        is_snapshot =  hasattr(bf,"snapshot_type")
        if data_types & GRID_DATA == GRID_DATA:
            warning = refresh_grid_data(bf,is_snapshot)
            if warning :
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,GRID_DATA),warning if isinstance(warning,(list,tuple)) else [warning]))

        if data_types & ORIGIN_POINT_TENURE == ORIGIN_POINT_TENURE:
            warning = refresh_originpoint_tenure(bf,is_snapshot)
            if warning :
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,ORIGIN_POINT_TENURE),warning if isinstance(warning,(list,tuple)) else [warning]))

        if data_types & BURNT_AREA == BURNT_AREA:
            warning = refresh_burnt_area(bf,is_snapshot)
            if warning :
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,BURNT_AREA),warning if isinstance(warning,(list,tuple)) else [warning]))

    return warnings

def refresh_spatial_data(bushfire,scope=BUSHFIRE,data_types=0):
    warnings = _refresh_spatial_data(bushfire,scope=scope,data_types=data_types)
    if warnings:
        for key,msgs in warnings:
            if key[1] == BUSHFIRE:
                print("================All {}  warnings for bushfire({})==========================".format(key[2],key[0]))
            else:
                print("================All {}  warnings for bushfire({})'s snapshot({})==========================".format(key[2],bushfire.id,key[0]))
            index = 0
            for msg in msgs:
                index += 1
                print("    {}:{}".format(index,msg))


def refresh_grid_data(bushfire,is_snapshot):
    warning = None
    req_data = {"features":serializers.serialize('geojson',[bushfire],geometry_field='origin_point',fields=('id','fire_number'))}
    req_options = {}
    update_fields = ["origin_point_grid"]
    req_options["grid"] = {
        "action":"getClosestFeature",
        "layers":[
            {
                "id":"fd_grid_points",
                "layerid":"cddp:fd_grid_points",
                "kmiservice":settings.KMI_URL,
                "buffer":120,
                "check_bbox":True,
                "properties":{
                    "grid":"fdgrid",
                },
            },
            {
                "id":"pilbara_grid_1km",
                "layerid":"cddp:pilbara_grid_1km",
                "buffer":800,
                "kmiservice":settings.KMI_URL,
                "check_bbox":True,
                "properties":{
                    "grid":"id",
                },
            },
        ],
    }

    req_data["options"] = json.dumps(req_options)
    resp=requests.post(url="{}/spatial".format(settings.SSS_URL), data=req_data,auth=requests.auth.HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO),verify=settings.SSS_CERTIFICATE_VERIFY)
    resp.raise_for_status()
    result = resp.json()
    grid_data = result["features"][0]["grid"]
    if grid_data.get("failed"):
        raise Exception(grid_data["failed"])
    elif grid_data.get("id") == "fd_grid_points":
        bushfire.origin_point_grid = "FD:{}".format(grid_data["feature"]["grid"])
    elif grid_data.get("id") == "pilbara_grid_1km":
        bushfire.origin_point_grid = "PIL:{}".format(grid_data["feature"]["grid"])
    else:
        bushfire.origin_point_grid = None

    bushfire.save(update_fields=update_fields)

    if is_snapshot:
        print("The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}')'s grid data is {}".format(bushfire.bushfire.fire_number,bushfire.id,bushfire.fire_number,bushfire.snapshot_type,bushfire.action,bushfire.origin_point_grid if bushfire.origin_point_grid else "null"))
    else:
        print("The bushfire report({})'s grid data is {}".format(bushfire.fire_number,bushfire.origin_point_grid if bushfire.origin_point_grid else "null"))
    return warning

def refresh_originpoint_tenure(bushfire,is_snapshot):
    warning = None
    req_data = {"features":serializers.serialize('geojson',[bushfire],geometry_field='origin_point',fields=('id','fire_number'))}
    req_options = {}
    update_fields = ["tenure"]
    req_options["originpoint_tenure"] = {
        "action":"getFeature",
        "layers":[
            {
                "id":"legislated_lands_and_waters",
                "layerid":"cddp:legislated_lands_and_waters",
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"name",
                    "category":"category"
                },
            },{
                "id":"dept_interest_lands_and_waters",
                "layerid":"cddp:dept_interest_lands_and_waters",
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"name",
                    "category":"category"
                },
            },{
                "id":"other_tenures_new",
                "layerid":"cddp:other_tenures_new",
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"brc_fms_le",
                    "category":"brc_fms_le"
                },
            }]
    }
    req_data["options"] = json.dumps(req_options)
    resp=requests.post(url="{}/spatial".format(settings.SSS_URL), data=req_data,auth=requests.auth.HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO),verify=settings.SSS_CERTIFICATE_VERIFY)
    resp.raise_for_status()
    result = resp.json()
    tenure_data = result["features"][0]["originpoint_tenure"]
    if tenure_data.get("failed"):
        raise Exception(tenure_data["failed"])
    elif tenure_data and tenure_data.get('id'):
        category  = utils.tenure_category(tenure_data['feature']['category'])
        try:
            bushfire.tenure = Tenure.objects.get(name=category)
        except:
            raise Exception("Unknown tenure category({})".format(category))
    else:
        #origin point is not within dpaw_tenure
        bushfire.tenure = Tenure.OTHER
        if is_snapshot:
            warning = "The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}')'s origin point tenure is \"{}\"".format(
                bushfire.bushfire.fire_number,
                bushfire.id,
                bushfire.fire_number,
                bushfire.snapshot_type,
                bushfire.action,
                bushfire.tenure
            )
        else:
            warning = "The bushfire report({})'s origin point tenure is \"{}\"".format(bushfire.fire_number,bushfire.tenure)

    bushfire.save(update_fields=update_fields)

    if is_snapshot:
        print("The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}')'s origin point tenure is \"{}\"".format(bushfire.bushfire.fire_number,bushfire.id,bushfire.fire_number,bushfire.snapshot_type,bushfire.action,bushfire.tenure))
    else:
        print("The bushfire report({})'s origin point tenure is \"{}\"".format(bushfire.fire_number,bushfire.tenure))

    return warning

def refresh_burnt_area(bushfire,is_snapshot):
    warning = None
    if not bushfire.fire_boundary:
        #no fire boundary, no need to refresh
        if is_snapshot:
            print("The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') has no fire boundary".format(bushfire.bushfire.fire_number,bushfire.id,bushfire.fire_number,bushfire.snapshot_type,bushfire.action))
        else:
            print("The bushfire report({}) has no fire boundary".format(bushfire.fire_number))
        return warning

    update_fields = ["fb_validation_req","other_area"]
    req_data = {"features":serializers.serialize('geojson',[bushfire],geometry_field='fire_boundary',fields=('id','fire_number'))}
    req_options = {}
    layers =  None
    if (bushfire.report_status == Bushfire.STATUS_INITIAL ) :
        layers =  None
    else: 
        layers = [{
            "id":"legislated_lands_and_waters",
            "layerid":"cddp:legislated_lands_and_waters",
            "kmiservice":settings.KMI_URL,
            "properties":{
                "name":"name",
                "category":"category"
            },
        },{
            "id":"dept_interest_lands_and_waters",
            "layerid":"cddp:dept_interest_lands_and_waters",
            "kmiservice":settings.KMI_URL,
            "properties":{
                "name":"name",
                "category":"category"
            },
        },{
            "id":"other_tenures",
            "layerid":"cddp:other_tenures_new",
            "kmiservice":settings.KMI_URL,
            "properties":{
                "name":"brc_fms_le",
                "category":"brc_fms_le"
            },
        }]

    
    req_options["area"] = {
        "action":"getArea",
        "layers":layers,
        "layer_overlap":False,
        "merge_result":True,
        "unit":"ha",
    }
    req_data["options"] = json.dumps(req_options)
    resp=requests.post(url="{}/spatial".format(settings.SSS_URL), data=req_data,auth=requests.auth.HTTPBasicAuth(settings.USER_SSO, settings.PASS_SSO),verify=settings.SSS_CERTIFICATE_VERIFY)
    resp.raise_for_status()
    result = resp.json()
    fb_validation_req = None
    try:
        #check result
        if result["features"]:
            area_data_status = result["features"][0]["area"]["status"]
            if area_data_status.get("failed") :
                raise area_data_status["failed"]
            else:
                if area_data_status.get("invalid"):
                    fb_validation_req = True
                else:
                    fb_validation_req = None
        else:
            raise Exception("Unknown Exception")

        area_data = result["features"][0]["area"]["data"]
        #group burnt area
        area_burnt_objects = []
        total_area = 0
        if layers:
            #aggregate the area's in like tenure types
            aggregated_sums = defaultdict(float)
            for layerid in area_data.get("layers",{}):
                for data in area_data["layers"][layerid]['areas']:
                    aggregated_sums[utils.tenure_category(data["category"])] += data["area"]
                    total_area += data["area"]
        
            area_unknown = 0.0
            for category, area in aggregated_sums.iteritems():
                tenure_qs = Tenure.objects.filter(name=category)
                if tenure_qs:
                    if is_snapshot:
                        area_burnt_objects.append([{"snapshot":bushfire, "tenure":tenure_qs[0]},{"snapshot_type":bushfire.snapshot_type, "area":area},None,None])
                    else:
                        area_burnt_objects.append([{"bushfire":bushfire, "tenure":tenure_qs[0]},{"area":area},None,None])
                else:
                    raise Exception("Unknown tenure category({})".format(category))
        
            if "other_area" in area_data:
                area_unknown += area_data["other_area"]
        
            if area_unknown > 0 :
                if is_snapshot:
                    area_burnt_objects.append([{"snapshot":bushfire, "tenure":Tenure.OTHER},{"snapshot_type":bushfire.snapshot_type, "area":area_unknown},None,None])
                else:
                    area_burnt_objects.append([{"bushfire":bushfire, "tenure":Tenure.OTHER},{"area":area_unknown},None,None])
                total_area += area_unknown

                if is_snapshot:
                    warning  = "The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') has {} other burnt area".format(
                        bushfire.bushfire.fire_number,
                        bushfire.id,
                        bushfire.fire_number,
                        bushfire.snapshot_type,
                        bushfire.action,
                        area_unknown
                    )
                else:
                    warning = "The bushfire report({}) has {} other burnt area".format(bushfire.fire_number,area_unknown)


        with transaction.atomic():
            #update bushfire
            if area_data.get('other_area'):
                bushfire.other_area = float(area_data['other_area']) 
            else:
                bushfire.other_area = 0
    
            if bushfire.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                update_fields.append("initial_area_unknown")
                update_fields.append("initial_area")
                bushfire.initial_area_unknown = False
                bushfire.initial_area = float(area_data['total_area'])
            else:
                update_fields.append("area_limit")
                update_fields.append("area")
                bushfire.area_limit = False
                bushfire.area = float(area_data['total_area'])
    
            bushfire.fb_validation_req = fb_validation_req
            bushfire.save(update_fields=update_fields)
    
            #update burnt area
            area_ids = []
            for o in area_burnt_objects:
                obj,created = (AreaBurntSnapshot if is_snapshot else AreaBurnt).objects.update_or_create(defaults=o[1],**o[0])
                o[2] = obj
                o[3] = created
                area_ids.append(obj.id)
    
            #delete existing burnt areas but not in the current burnt areas
            if is_snapshot:
                if area_ids:
                    deleted_areas = list(AreaBurntSnapshot.objects.filter(snapshot=bushfire).exclude(id__in = area_ids))
                    del_areas,del_areas_detail = AreaBurntSnapshot.objects.filter(snapshot=bushfire).exclude(id__in = area_ids).delete()
                else:
                    deleted_areas = list(AreaBurntSnapshot.objects.filter(snapshot=bushfire))
                    del_areas,del_areas_detail = AreaBurntSnapshot.objects.filter(snapshot=bushfire).delete()
            else:
                if area_ids:
                    deleted_areas = list(AreaBurnt.objects.filter(bushfire=bushfire).exclude(id__in = area_ids))
                    del_areas,del_areas_detail = AreaBurnt.objects.filter(bushfire=bushfire).exclude(id__in = area_ids).delete()
                else:
                    deleted_areas = list(AreaBurnt.objects.filter(bushfire=bushfire))
                    del_areas,del_areas_detail = AreaBurnt.objects.filter(bushfire=bushfire).exclude(id__in = area_ids).delete()
            if len(deleted_areas) != del_areas:
                raise Exception("The number of deleted areas is not match with the number of areas which are required to be deleted")


        #print
        if layers:
            overlap_area = round(total_area - area_data['total_area'],2)
        else:
            overlap_area = None
        if is_snapshot:
            if bushfire.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                print("The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') initial_area_unknown={} initial_area={} other_area={} fb_validation_req={} overlap_area={}".format(
                    bushfire.bushfire.fire_number,
                    bushfire.id,
                    bushfire.fire_number,
                    bushfire.snapshot_type,
                    bushfire.action,
                    bushfire.initial_area_unknown,
                    round(bushfire.initial_area,2),
                    round(bushfire.other_area,2),
                    bushfire.fb_validation_req,
                    overlap_area
                ))
            else:
                print("The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') area_limit={} area={} other_area={} fb_validation_req={} overlap_area={}".format(
                    bushfire.bushfire.fire_number,
                    bushfire.id,
                    bushfire.fire_number,
                    bushfire.snapshot_type,
                    bushfire.action,
                    bushfire.area_limit,
                    round(bushfire.area,2),
                    round(bushfire.other_area,2),
                    bushfire.fb_validation_req,
                    overlap_area
                ))
        else:
            if bushfire.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                print("The bushfire report({}): initial_area_unknown={} initial_area={} other_area={} fb_validation_req={} overlap_area={}".format(
                    bushfire.fire_number,
                    bushfire.initial_area_unknown,
                    bushfire.initial_area,
                    bushfire.other_area,
                    bushfire.fb_validation_req,
                    overlap_area
                ))
            else:
                print("The bushfire report({}): area_limit={} area={} other_area={} fb_validation_req={} overlap_area={}".format(
                    bushfire.fire_number,
                    bushfire.area_limit,
                    bushfire.area,
                    bushfire.other_area,
                    bushfire.fb_validation_req,
                    overlap_area
                ))
        if area_burnt_objects:
            for o in area_burnt_objects:
                print("    {} AreaBurnt: id={} category=\"{}\" area={}".format("Create" if o[3] else "Update",o[2].id,o[2].tenure.name,o[2].area))

        if deleted_areas:
            for o in deleted_areas:
                print("    Delete AreaBurnt: id={} category=\"{}\" area={}".format(o.id,o.tenure.name,o.area))

    except Exception as ex:
        traceback.print_exc()       
        if is_snapshot:
            raise Exception("Calculate the burnt area of the snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') of the bushfire({}) failed. {}".format(bushfire.id,bushfire.fire_number,bushfire.snapshot_type,bushfire.action,bushfire.bushfire.fire_number,str(ex)))
        else:
            raise Exception("Calculate the burnt area of bushfire({})'s burnt failed. {}".format(bushfire.fire_number,str(ex)))


    return warning
