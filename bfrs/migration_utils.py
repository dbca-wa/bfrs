import requests
import json
import itertools
import traceback
import os
import shutil
import tempfile
from datetime import datetime,timedelta
from collections import defaultdict, OrderedDict

from django.core import serializers
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.contrib.gis.geos import Point, GEOSGeometry, Polygon, MultiPolygon, GEOSException
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import User

from bfrs.models import (Bushfire, Tenure,AreaBurntSnapshot,AreaBurnt,BushfireSnapshot)
from bfrs import utils
from bfrs.utils import serialize_bushfire

RERUN = 1
RESUME = 2
REPROCESS_ERRORS = 4
REPROCESS_WARNINGS = 8


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

def get_refresh_status_file(reporting_year):
    status_file = os.path.join(settings.BASE_DIR,"logs","bfrs-refresh-data-{}.{}.json".format(reporting_year,settings.ENV_TYPE))
    if not os.path.exists(os.path.dirname(status_file)):
        os.mkdir(os.path.exists(os.path.dirname(status_file)))

    return status_file


def get_refresh_status(reporting_year,scope,data_type,runtype):
    status_file = get_refresh_status_file(reporting_year)

 
    save = False
    if os.path.exists(status_file):
        try:
            with open(status_file) as f:
                status = json.loads(f.read())
        except:
            status = {}
            os.remove(status_file)
    else:
        status = {}

    if "progress" not in status:
        status["progress"] = {}
        save = True

    if runtype & RERUN == RERUN:
        #clean the refresh progress
        for s in (BUSHFIRE,SNAPSHOT):
            if scope & s == 0:
                continue
            if SCOPES_DESC[s] not in status["progress"]:
                continue
            for t in (GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA):
                if data_type & t == 0:
                    continue
                if DATATYPES_DESC[t] not in status["progress"][SCOPES_DESC[s]]:
                    continue
                del status["progress"][SCOPES_DESC[s]][DATATYPES_DESC[t]]
                save = True
        #clean the refresh warnings
        if "warnings" in status:
            removed_keys = []
            for key,warnings in status["warnings"].items():
                index = len(warnings) - 1
                while index >= 0:
                    warning = warnings[index]
                    try:
                        if warning[0][1] & scope == 0:
                            continue
                        if warning[0][2] & data_type == 0:
                            continue
                        del warnings[index]
                    finally:
                        index -= 1
                if len(warnings) == 0:
                    removed_keys.append(key)
                    save = True
            for key in removed_keys:
                del status["warnings"][key]
                save = True

    if save:
        save_refresh_status(reporting_year,status)


    return status


def save_refresh_status(reporting_year,status):
    status_file = get_refresh_status_file(reporting_year)
    if not status:
        os.remove(status_file)
        return

    status_content = json.dumps(status,indent=4)
    with open(status_file,"w") as f:
        f.write(status_content)

def get_last_refreshed_bushfireid(status,scope,datatypes):
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
                "scope":s,
            }
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if datatypes & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if tname not in progress_status[sname]:
                progress_status[sname][tname] = {
                    "data_type":t,
                }
    #get min bfid
    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if datatypes & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if "last_refreshed_id" not in progress_status[sname][tname]:
                return None
            elif bfid is None or  bfid > progress_status[sname][tname]["last_refreshed_id"]:
                bfid = progress_status[sname][tname]["last_refreshed_id"]
    return bfid

def set_last_refreshed_bushfireid(status,scope,datatypes,bfid):
    if "progress" not in status:
        status["progress"] = {}
    progress_status = status["progress"]

    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if datatypes & t  == 0:
                continue
            tname = DATATYPES_DESC[t]
            if "last_refreshed_id"  not in progress_status[sname][tname]:
                progress_status[sname][tname]["last_refreshed_id"] = bfid
            elif progress_status[sname][tname]["last_refreshed_id"] < bfid:
                progress_status[sname][tname]["last_refreshed_id"] = bfid

def get_scope_and_datatypes(status,bushfire,scope,datatypes):
    progress_status = status["progress"]
    result = {}
    for s in [BUSHFIRE,SNAPSHOT]:
        if scope & s  == 0:
            continue
        sname = SCOPES_DESC[s]
        for t in [GRID_DATA,ORIGIN_POINT_TENURE,BURNT_AREA]:
            if datatypes & t  == 0:
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
    for s,datatypes in result.items():
        if datatypes in result2:
            result2[datatypes] = result2[datatypes] | s
        else:
            result2[datatypes] = s

    #return list of (scope,datatypes)
    return [(s,t) for t,s in result2.items()]


def add_warnings(status,bushfire,scope,datatypes,warnings):
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
            if bfwarnings[0][2] & datatypes == 0:
                continue
            del all_warnings[warning_key][index]
        finally:
            index -= 1
    #add the new warnings   
    for warning in warnings:
        all_warnings[warning_key].append(warning)

def refresh_all_bushfires(scope=BUSHFIRE,datatypes = 0,runtype=RESUME,layersuffix=""):
    try:
        min_year = Bushfire.objects.all().order_by("reporting_year").first().reporting_year
        max_year = Bushfire.objects.all().order_by("-reporting_year").first().reporting_year
        year = min_year
        while year <= max_year:
            try:
                refresh_bushfires(year,scope=scope,datatypes=datatypes,runtype=runtype,layersuffix=layersuffix)
            finally:
                year += 1
    except:
        return

def refresh_bushfires(reporting_year,scope=BUSHFIRE,datatypes = 0,runtype=RESUME,size=0,layersuffix=""):
    if datatypes == 0 or scope == 0:
        return

    if runtype & RERUN == RERUN:
        runtype = RERUN

    all_warnings = OrderedDict()
    status = get_refresh_status(reporting_year,scope,datatypes,runtype)
    last_refreshed_id = get_last_refreshed_bushfireid(status,scope,datatypes)
    try:
        warnings = {}
        counter = 0
        start_time = datetime.now()
        save_interval = timedelta(minutes=2)

        #reprocess failed bushfires
        if "warnings" in status and runtype & (REPROCESS_ERRORS | REPROCESS_WARNINGS) > 0:
            removed_keys = []
            for key,previous_warnings in status["warnings"].items():
                index = len(previous_warnings) - 1
                while index >= 0:
                    try:
                        previous_warning = previous_warnings[index]
                        if previous_warning[0][3] == "WARNING" and runtype & REPROCESS_WARNINGS == 0:
                            continue
                        if previous_warning[0][3] == "ERROR" and runtype & REPROCESS_ERRORS == 0:
                            continue
                        if previous_warning[0][1] & scope == 0:
                            continue
                        if previous_warning[0][2] & datatypes == 0:
                            continue
                        bushfire = Bushfire.objects.get(id = int(key.split(':')[0]))
                        print("Reprocess bushfire({}) {}:{} ".format(bushfire.fire_number,previous_warning[0][3],previous_warning[1]))
                        warnings = _refresh_bushfire(bushfire,scope=previous_warning[0][1],datatypes=previous_warning[0][2],layersuffix=layersuffix)
                        warning_key = (bushfire.id,bushfire.fire_number)
                        if warnings:
                            add_warnings(status,bushfire,previous_warning[0][1],previous_warning[0][2],warnings)
                            if warning_key in all_warnings:
                                for w in warnings:
                                    all_warnings[warning_key].append(w)
                            else:
                                all_warnings[warning_key] = warnings
                        else:
                            del previous_warnings[index]
                    finally:
                        index -= 1
                if len(previous_warnings) == 0:
                    removed_keys.append(key)
                        
                counter += 1
                if size and counter >= size:
                    break
                if datetime.now() - start_time >= save_interval:
                    save_refresh_status(reporting_year,status)
                    start_time = datetime.now()
            if removed_keys:
                for key in removed_keys:
                    del status["warnings"][key]

            save_refresh_status(reporting_year,status)
            
                
        #refresh bushfires
        if runtype & (RERUN | RESUME) > 0:
            bushfires = Bushfire.objects.filter(reporting_year=reporting_year)
            bushfires = bushfires.order_by("id") if last_refreshed_id is None else bushfires.filter(id__gt=last_refreshed_id).order_by("id")
            index = 0
            totalcount = len(bushfires)
            for bushfire in bushfires:
                index += 1
                print("Refresh {}'s bushfire({}), {}/{}".format(reporting_year,bushfire.fire_number,index,totalcount))
                scope_types = get_scope_and_datatypes(status,bushfire,scope,datatypes)
                warning_key = (bushfire.id,bushfire.fire_number)
                for s,t in scope_types:
                    warnings = _refresh_bushfire(bushfire,scope=s,datatypes=t,layersuffix=layersuffix)
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
                    save_refresh_status(reporting_year,status)
                    start_time = datetime.now()
    except Exception as ex:
        print("Failed to refresh the spatial data,{}".format(str(ex)))
        traceback.print_exc()


    save_refresh_status(reporting_year,status)
    
    if all_warnings:
        for bushfire,warnings in all_warnings.items():
            print("================All warnings or errors for bushfire({})==========================".format(bushfire))
            for key,msgs in warnings:
                if key[1] == BUSHFIRE:
                    print("    All {}  warnings or errors for bushfire({})".format(DATATYPES_DESC[key[2]],key[0]))
                else:
                    print("    All {}  warnings or errors for bushfire({})'s snapshot({})".format(DATATYPES_DESC[key[2]],bushfire[0],key[0]))
                index = 0
                for msg in msgs:
                    index += 1
                    print("    {}. {}:{}".format(index,key[3],msg))

def _refresh_bushfire(bushfire,scope=BUSHFIRE,datatypes=0,layersuffix=""):
    warnings = [] 
    if datatypes == 0 or scope == 0:
        return warnings

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
        if datatypes & GRID_DATA == GRID_DATA:
            try:
                warning = refresh_grid_data(bf,is_snapshot)
                if warning :
                    warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,GRID_DATA,'WARNING'),warning if isinstance(warning,(list,tuple)) else [warning]))
            except Exception as ex:
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,GRID_DATA,'ERROR'),[str(ex)]))


        if datatypes & ORIGIN_POINT_TENURE == ORIGIN_POINT_TENURE:
            try:
                warning = refresh_originpoint_tenure(bf,is_snapshot,layersuffix=layersuffix)
                if warning :
                    warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,ORIGIN_POINT_TENURE,'WARNING'),warning if isinstance(warning,(list,tuple)) else [warning]))
            except Exception as ex:
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,ORIGIN_POINT_TENURE,'ERROR'),[str(ex)]))

        if datatypes & BURNT_AREA == BURNT_AREA:
            try:
                warning = refresh_burnt_area(bf,is_snapshot,layersuffix=layersuffix)
                if warning :
                    warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,BURNT_AREA,'WARNING'),warning if isinstance(warning,(list,tuple)) else [warning]))
            except Exception as ex:
                warnings.append(((bf.id,SNAPSHOT if is_snapshot else BUSHFIRE,BURNT_AREA,'ERROR'),[str(ex)]))

    return warnings

def get_bushfire(bushfire):
    if isinstance(bushfire,int):
        return Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,basestring):
        return Bushfire.objects.get(fire_number=bushfire)
    elif isinstance(bushfire,(list,tuple)):
        return [get_bushfire(bf) for bf in bushfire]
    elif not isinstance(bushfire,(Bushfire,BushfireSnapshot)):
        raise Exception("Bushfire should be bushfire id or fire number, Bushfire instance or Bushfiresnapshot instance")
    else:
        return bushfire


def refresh_bushfire(bushfire,scope=BUSHFIRE,datatypes=0,layersuffix=""):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,basestring):
        bushfire = Bushfire.objects.get(fire_number=bushfire)
    elif not isinstance(bushfire,Bushfire):
        raise Exception("Bushfire should be bushfire id or fire number or Bushfire instance")

    warnings = _refresh_bushfire(bushfire,scope=scope,datatypes=datatypes,layersuffix=layersuffix)
    if warnings:
        for key,msgs in warnings:
            if key[1] == BUSHFIRE:
                print("================All {}  warnings or errors for bushfire({})==========================".format(DATATYPES_DESC[key[2]],key[0]))
            else:
                print("================All {}  warnings or errors for bushfire({})'s snapshot({})==========================".format(DATATYPES_DESC[key[2]],bushfire.id,key[0]))
            index = 0
            for msg in msgs:
                index += 1
                print("    {}. {}:{}".format(index,key[3],msg))


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

def refresh_originpoint_tenure(bushfire,is_snapshot,layersuffix=""):
    warning = None
    req_data = {"features":serializers.serialize('geojson',[bushfire],geometry_field='origin_point',fields=('id','fire_number'))}
    req_options = {}
    update_fields = ["tenure"]
    req_options["originpoint_tenure"] = {
        "action":"getFeature",
        "layers":[
            {
                "id":"state_forest_plantation_distribution",
                "layerid":"cddp:state_forest_plantation_distribution{}".format(layersuffix),
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"fbr_fire_r",
                    "category":"fbr_fire_r"
                },
            },{
                "id":"legislated_lands_and_waters",
                "layerid":"cddp:legislated_lands_and_waters{}".format(layersuffix),
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"name",
                    "category":"category"
                },
            },{
                "id":"dept_interest_lands_and_waters",
                "layerid":"cddp:dept_interest_lands_and_waters{}".format(layersuffix),
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"name",
                    "category":"category"
                },
            },{
                "id":"other_tenures_new",
                "layerid":"cddp:other_tenures{}".format(layersuffix or "_new"),
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "id":"ogc_fid",
                    "name":"brc_fms_le",
                    "category":"brc_fms_le"
                },
            },{
                "id":"sa_nt_burntarea",
                "layerid":"cddp:sa_nt_state_polygons_burntarea{}".format(layersuffix),
                "kmiservice":settings.KMI_URL,
                "properties":{
                    "category":"name"
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
        try:
            bushfire.tenure = utils.get_tenure(tenure_data['feature']['category'],createIfMissing=False)
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

def refresh_burnt_area(bushfire,is_snapshot,layersuffix=""):
    warning = None
    area_burnt_objects = []
    update_fields = None
    layers =  None
    overlap_area = None
    try:
        if not bushfire.fire_boundary:
            #no fire boundary,
            if (bushfire.report_status != Bushfire.STATUS_INITIAL ) :
                if bushfire.area > 0:
                    if is_snapshot:
                        area_burnt_objects.append([{"snapshot":bushfire, "tenure":bushfire.tenure or Tenure.OTHER},{"snapshot_type":bushfire.snapshot_type, "area":bushfire.area,"created":timezone.now(),"modified":timezone.now()},None,None])
                    else:
                        area_burnt_objects.append([{"bushfire":bushfire, "tenure":bushfire.tenure or Tenure.OTHER},{"area":bushfire.area},None,None])
    
        else:
            update_fields = ["fb_validation_req","other_area"]
            req_data = {"features":serializers.serialize('geojson',[bushfire],geometry_field='fire_boundary',fields=('id','fire_number'))}
            req_options = {}
            if (bushfire.report_status == Bushfire.STATUS_INITIAL ) :
                layers =  None
            else: 
                layers = [{
                    "id":"legislated_lands_and_waters",
                    "layerid":"cddp:legislated_lands_and_waters{}".format(layersuffix),
                    "cqlfilter":"category<>'State Forest'",
                    "kmiservice":settings.KMI_URL,
                    "properties":{
                        "category":"category"
                    },
                },{
                    "id":"state_forest_plantation_distribution",
                    "layerid":"cddp:state_forest_plantation_distribution{}".format(layersuffix),
                    "kmiservice":settings.KMI_URL,
                    "properties":{
                        "category":"fbr_fire_r"
                    },
                },{
                    "id":"dept_interest_lands_and_waters",
                    "layerid":"cddp:dept_interest_lands_and_waters{}".format(layersuffix),
                    "kmiservice":settings.KMI_URL,
                    "properties":{
                        "category":"category"
                    },
                },{
                    "id":"other_tenures",
                    "layerid":"cddp:other_tenures{}".format(layersuffix or "_new"),
                    "kmiservice":settings.KMI_URL,
                    "properties":{
                        "category":"brc_fms_le"
                    },
                },{
                    "id":"sa_nt_burntarea",
                    "layerid":"cddp:sa_nt_state_polygons_burntarea{}".format(layersuffix),
                    "kmiservice":settings.KMI_URL,
                    "properties":{
                        "category":"name"
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

            #check result
            if result["features"]:
                area_data_status = result["features"][0]["area"]["status"]
                if area_data_status.get("failed") :
                    raise Exception(area_data_status["failed"])
                else:
                    if area_data_status.get("invalid"):
                        fb_validation_req = True
                    else:
                        fb_validation_req = None
            else:
                raise Exception("Unknown Exception")
    
            area_data = result["features"][0]["area"]["data"]
            #group burnt area
            total_area = 0
            if layers:
                #aggregate the area's in like tenure types
                aggregated_sums = defaultdict(float)
                for layerid in area_data.get("layers",{}):
                    for data in area_data["layers"][layerid]['areas']:
                        aggregated_sums[utils.get_tenure(data["category"],createIfMissing=False)] += data["area"]
                        total_area += data["area"]
            
                area_unknown = 0.0
                for tenure, area in aggregated_sums.iteritems():
                    area = round(area,2)
                    if area > 0:
                        if is_snapshot:
                            area_burnt_objects.append([{"snapshot":bushfire, "tenure":tenure},{"snapshot_type":bushfire.snapshot_type, "area":area,"created":timezone.now(),"modified":timezone.now()},None,None])
                        else:
                            area_burnt_objects.append([{"bushfire":bushfire, "tenure":tenure},{"area":area},None,None])
            
                if "other_area" in area_data:
                    area_unknown += area_data["other_area"]
            
                area_unknown = round(area_unknown,2)
                if area_unknown > 0 :
                    if is_snapshot:
                        area_burnt_objects.append([{"snapshot":bushfire, "tenure":Tenure.OTHER},{"snapshot_type":bushfire.snapshot_type, "area":area_unknown,"created":timezone.now(),"modified":timezone.now()},None,None])
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
                        warning = "The bushfire report({}) has {}ha other burnt area".format(bushfire.fire_number,area_unknown)
                elif area_unknown < 0:
                    if is_snapshot:
                        area_burnt_objects.append([{"snapshot":bushfire, "tenure":Tenure.OTHER},{"snapshot_type":bushfire.snapshot_type, "area":area_unknown,"created":timezone.now(),"modified":timezone.now()},None,None])
                    else:
                        area_burnt_objects.append([{"bushfire":bushfire, "tenure":Tenure.OTHER},{"area":area_unknown},None,None])
                    total_area += area_unknown
    
                    if is_snapshot:
                        warning  = "The bushfire report({})'s snapshot(id={},fire_number='{}',snapshot_type='{}',action='{}') has {}ha overlap area".format(
                            bushfire.bushfire.fire_number,
                            bushfire.id,
                            bushfire.fire_number,
                            bushfire.snapshot_type,
                            bushfire.action,
                            abs(area_unknown)
                        )
                    else:
                        warning = "The bushfire report({}) has {}ha overlap area".format(bushfire.fire_number,abs(area_unknown))

            if layers:
                overlap_area = round(abs(area_unknown),2) if area_unknown < 0 else 0
            else:
                overlap_area = 0
    

        with transaction.atomic():
            #update bushfire
            if bushfire.fire_boundary:
                if area_data.get('other_area'):
                    bushfire.other_area = round(float(area_data['other_area']),2)
                else:
                    bushfire.other_area = 0
    
                if bushfire.report_status < Bushfire.STATUS_INITIAL_AUTHORISED:
                    update_fields.append("initial_area_unknown")
                    update_fields.append("initial_area")
                    bushfire.initial_area_unknown = False
                    bushfire.initial_area = round(float(area_data['total_area']),2)
                else:
                    update_fields.append("area_limit")
                    update_fields.append("area")
                    bushfire.area_limit = False
                    bushfire.area = round(float(area_data['total_area']),2)
    
                bushfire.fb_validation_req = fb_validation_req
                bushfire.save(update_fields=update_fields)
    
            #update burnt area
            area_ids = []
            default_data = None
            for o in area_burnt_objects:
                if is_snapshot:
                    if default_data is None:
                        existing_area_burnt = AreaBurntSnapshot.objects.filter(snapshot=bushfire).first()
                        if existing_area_burnt is None:
                            default_data = {
                                "creator":bushfire.bushfire.modifier,
                                "modifier":bushfire.bushfire.modifier
                            }
                        else:
                            default_data = {
                                "creator":existing_area_burnt.creator,
                                "modifier":existing_area_burnt.modifier
                            }

                    default_data.update(o[1])
                    obj,created = AreaBurntSnapshot.objects.update_or_create(defaults=default_data,**o[0])
                else:
                    obj,created = AreaBurnt.objects.update_or_create(defaults=o[1],**o[0])
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

def exportBushfire(bushfire,folder=None,merged_bushfires=None):
    """
    export bushfire as geojson file
    bushfire should be a Bushfire or BushfireSnapshot object
    """
    bushfire = get_bushfire(bushfire)
    if merged_bushfires:
        merged_bushfires = get_bushfire(merged_bushfires)
        if bushfire.fire_boundary:
            polygons = [p for p in bushfire.fire_boundary]
        else:
            polygons = []
        for mbf in merged_bushfires:
            if mbf.fire_boundary:
                for p in mbf.fire_boundary:
                    polygons.append(p)
        bushfire.fire_boundary = MultiPolygon(polygons)

    if not isinstance(bushfire,(Bushfire,BushfireSnapshot)):
        raise Exception("Bushfire should be a Bushfire or BushfireSnapshot instance")
    if folder:
        if not os.path.exists(folder):
            raise Exception("The folder '{}' doesn't exist".format(folder))
        if not os.path.isdir(folder):
            raise Exception("The path '{}' is not a folder".format(folder))
    folder = folder or tempfile.gettempdir()
    if isinstance(bushfire,Bushfire):
        file_name = os.path.join(folder,"{}.geojson".format(bushfire.fire_number.replace(' ','_')))
        fields = ('id','fire_number')
    else:
        file_name = os.path.join(folder,"{}_{}.geojson".format(bushfire.fire_number.replace(' ','_'),bushfire.created.strftime("%Y-%m-%d_%H%M%S")))
        fields = ('id','fire_number','bushfire_id','created')

    with open(file_name,'w') as f:
        f.write(serializers.serialize('geojson',[bushfire],geometry_field='fire_boundary',fields=('id','fire_number')))

    return file_name

def exportBushfires(bushfires=None,reporting_year=None,folder=None):
    if not bushfires:
        if reporting_year:
            bushfires = Bushfire.objects.filter(reporting_year=reporting_year)
    if not bushfires:
        return
    for bushfire in bushfires:
        exportBushfire(bushfire,folder)

def importFireboundary(geojson_file,user=None,create_snapshot=True,action=None,layersuffix="",refresh_data=True):
    """
    import a bushfire's geojson file
    """
    if not os.path.exists(geojson_file):
        raise Exception("The geojson file '{}' doesn't exist".format(geojson_file))
    if os.path.isdir(geojson_file):
        raise Exception("The path '{}' is not a file".format(geojson_file))


    with open(geojson_file) as f:
        json_obj = json.loads(f.read())

    if not json_obj.get("features"):
        return

    user =  user or User.objects.filter(email__iexact = 'rocky.chen@dbca.wa.gov.au').first()
    if not user:
        raise Exception("User Not Found")

    for feature in json_obj["features"]:
        fire_number = feature.get('properties',{}).get('fire_number')
        if not fire_number:
            raise Exception("No fire_number found in file '{}'".format(geojson_file))
        if not (feature.get("geometry") or {}).get('coordinates'):
            print("Fire boundary not found in file '{}'".format(geojson_file))
            continue
        try:
            bushfire = Bushfire.objects.get(fire_number=fire_number)
        except ObjectDoesNotExist as ex:
            raise Exception("The fire_number '{}' does not exist in bfrs".format(fire_number))
        fire_boundary = MultiPolygon([Polygon(*p) for p in feature['geometry']['coordinates']])
        #update fire boundary
        bushfire.fire_boundary = fire_boundary
        bushfire.modifier = user
        if refresh_data:
            if bushfire.report_status > Bushfire.STATUS_INITIAL:
                #refresh burnt area
                warnings = _refresh_bushfire(bushfire,scope=BUSHFIRE,datatypes=BURNT_AREA,layersuffix=layersuffix)
                if warnings:
                    errors = []
                    for key,msgs in warnings:
                        if key[0] != bushfire.id:
                            continue
                        if key[3] != "ERROR":
                            continue
                        for msg in msgs:
                            errors.append(msg)
                    if errors:
                        raise Exception("Failed to calculate burnt area.{}{}".format(os.linesep,os.linesep.join(errors)))
        #save data
        bushfire.save(update_fields=("fire_boundary","modifier","modified"))
        #make snapshot
        if create_snapshot:
            serialize_bushfire('final', (action or 'Fix fire boundary issues by OIM'), bushfire)

def importFireboundaries(folder,user=None,create_snapshot=True,action=None,refresh_data=True):
    if not os.path.exists(folder):
        raise Exception("The folder '{}' doesn't exist".format(folder))
    if not os.path.isdir(folder):
        raise Exception("The path '{}' is not a folder".format(folder))

    geojson_files = sorted([f for f in os.listdir(folder) if f.lower().endswith(".geojson")])

    processed_folder = os.path.join(folder,"processed")
    if not os.path.exists(processed_folder):
        os.mkdir(processed_folder)

    user =  user or User.objects.filter(email__iexact = 'rocky.chen@dbca.wa.gov.au').first()
    if not user:
        raise Exception("User Not Found")

    for geojson_file in geojson_files:
        print("Processing file '{}'".format(geojson_file))
        source_file = os.path.join(folder,geojson_file)
        processed_file = os.path.join(processed_folder,geojson_file)
        try:
            importFireboundary(source_file,user=user,create_snapshot=create_snapshot,action=action,refresh_data=refresh_data)
            if os.path.exists(processed_file):
                os.remove(processed_file)
            shutil.move(source_file,processed_file)
        except:
            traceback.print_exc()

            

