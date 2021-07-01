from django.db import connection
from bfrs.models import Bushfire, Region, District, Tenure, Cause, current_finyear,Agency
from bfrs.utils import get_pbs_bushfires
from django.db.models import Count, Sum
from django.db.models.query import QuerySet
from django.contrib.auth.models import User, Group
from django.contrib import messages
from datetime import datetime
from xlwt import Workbook, Font, XFStyle, Alignment, Pattern, Style
from itertools import count
import unicodecsv
import shutil

from django.http import HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.core.mail import send_mail
from django.db import connection
from cStringIO import StringIO
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
import os
import subprocess
import csv
import traceback

from django.template.loader import render_to_string
from .utils import generate_pdf

import logging
logger = logging.getLogger(__name__)

DISCLAIMER = 'Any discrepancies between the total and the sum of the individual values is due to rounding.'
MISSING_MAP = []

region_order = {
    'Goldfields':-97,
    'Kimberley':-100,
    'Midwest':-98,
    'Pilbara':-99,
    'South Coast':-95,
    'South West':-199,
    'Swan':-200,
    'Warren':-198,
    'Wheatbelt':-96
}

sorted_regions = {}
def get_sorted_regions(forest_region=None):
    key = "all" if forest_region is None else ("forest" if forest_region else "nonforest")
    if key not in sorted_regions:
        if forest_region is None:
            #sorted_regions[key] = sorted(Region.objects.all(),cmp=lambda r1,r2: cmp(region_order.get(r1.name,r1.id),region_order.get(r2.name,r2.id)))
            sorted_regions[key] = sorted(Region.objects.filter(dbca=True) ,cmp=lambda r1,r2: cmp(region_order.get(r1.name,r1.id),region_order.get(r2.name,r2.id)))
        else:
            #sorted_regions[key] = sorted(Region.objects.filter(forest_region=forest_region),cmp=lambda r1,r2: cmp(region_order.get(r1.name,r1.id),region_order.get(r2.name,r2.id)))
            sorted_regions[key] = sorted(Region.objects.filter(dbca=True).filter(forest_region=forest_region),cmp=lambda r1,r2: cmp(region_order.get(r1.name,r1.id),region_order.get(r2.name,r2.id)))

    return sorted_regions[key]

def style(bold=False, num_fmt='#,##0', horz_align=Alignment.HORZ_GENERAL, colour=None):
    style = XFStyle()
    font = Font()
    font.bold = bold
    style.font = font
    style.num_format_str = num_fmt
    style.alignment.horz = horz_align

    # add cell colour
    if colour:
        pattern = Pattern()
        pattern.pattern = Pattern.SOLID_PATTERN
        pattern.pattern_fore_colour = Style.colour_map[colour]
        style.pattern = pattern

    return style

style_normal_int   = style()
style_normal       = style(num_fmt='#,##0')
style_normal_float = style(num_fmt='#,##0.00')
style_normal_area = style(num_fmt='#,##0.00')
style_normal_percentage = style(num_fmt='#,##0.00\\%')

style_bold_int     = style(bold=True)
style_bold         = style(bold=True, num_fmt='#,##0', horz_align=Alignment.HORZ_CENTER)
style_bold_float   = style(bold=True, num_fmt='#,##0.00')
style_bold_area   = style(bold=True, num_fmt='#,##0.00')
style_bold_percentage   = style(bold=True, num_fmt='#,##0.00\\%')
style_bold_gen     = style(bold=True, num_fmt='#,##0')
style_bold_red     = style(bold=True, num_fmt='#,##0', colour='red')
style_bold_yellow  = style(bold=True, num_fmt='#,##0', colour='yellow')

def read_col(fin_year, col_type):
    """ 
        Reads historical data from file - provided by FMS from legacy BFRS application

        fin_year: 2006          --> first part of '2006/2007'
        col_type: 'count'       --> annotated values or 
                  'total_count' --> aggregated values
    """
    try:
        reader = csv.reader(open(settings.HISTORICAL_CAUSE_CSV_FILE), delimiter=',', quotechar='"')
        hdr = reader.next()
        hdr = [hdr[0]] + [int(i.split('/')[0]) for i in hdr if '/' in i] # converts '2006/2007' --> int('2006')
        idx = hdr.index(fin_year)

        if hdr[idx+10] != fin_year:
            # check idx + 10 is also equal to fin_year
            logger.error("Cannot find 2nd fin_year (percentage column) in CSV header: {}, {}".format(fin_year, hdr))
            return [], []

        count_list = [] 
        perc_list = [] 
        for i in list(reader):
            if len(i) == 0 or i[0].startswith('#'):
                # ignore comments or blanks lines in csv file
                continue

            if i[0] != 'Total' and col_type=='count':
                cause = Cause.objects.filter(name=i[0])
                if cause:
                    cause_id = cause[0].id
                else:
                    if not [j for j in MISSING_MAP if not j.has_key(i[0])]:
                        MISSING_MAP.append( dict(name=i[0], error='Cause {0}, Missing from BFRS Enum list. Please Request OIM to add Cause={0}'.format(i[0])))
                    continue
                count_list.append( dict(cause_id=cause_id, count=int(i[idx])) )
                perc_list.append( dict(cause_id=cause_id, count=int(i[idx+10])) )
            if i[0] == 'Total' and col_type=='total_count':
                return dict(count_total=int(i[idx])), dict(count_total=int(i[idx+10])) 

        return count_list, perc_list

    except ValueError, e:
        logger.error("Cannot find fin_year in CSV header: {}, {}, {}".format(fin_year, hdr, e))

    except IndexError, e:
        logger.error("Cannot find 2nd fin_year (percentage column) in CSV header: {}, {}, {}".format(fin_year, hdr, e))

    except IOError, e:
        logger.error("Cannot Open CSV file: {}, {}".format(settings.HISTORICAL_CAUSE_CSV_FILE, e))

    except Exception, e:
        logger.error("Error reading column from CSV file: {}, {}, {}".format(fin_year, settings.HISTORICAL_CAUSE_CSV_FILE, e))

    return [], []


class BushfireReport():
    def __init__(self, reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.ministerial_auth = MinisterialReportAuth(self.reporting_year)
        self.ministerial_268 = MinisterialReport268(self.reporting_year)
        self.ministerial = MinisterialReport(self.ministerial_auth, self.ministerial_268,self.reporting_year)
        self.quarterly = QuarterlyReport(self.reporting_year)
        self.by_tenure = BushfireByTenureReport(self.reporting_year)
        self.by_cause = BushfireByCauseReport(self.reporting_year)
        self.region_by_tenure = BushfireByRegionByTenureReport(self.reporting_year)
        self.indicator = BushfireIndicator(self.reporting_year)
        self.by_cause_10YrAverage = Bushfire10YrAverageReport(self.reporting_year)

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.ministerial.get_excel_sheet(rpt_date, book)
        self.ministerial_auth.get_excel_sheet(rpt_date, book)
        self.ministerial_268.get_excel_sheet(rpt_date, book)
        self.quarterly.get_excel_sheet(rpt_date, book)
        self.by_tenure.get_excel_sheet(rpt_date, book)
        self.by_cause.get_excel_sheet(rpt_date, book)
        self.region_by_tenure.get_excel_sheet(rpt_date, book)
        self.indicator.get_excel_sheet(rpt_date, book)
        self.by_cause_10YrAverage.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'bushfire_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.ministerial.get_excel_sheet(rpt_date, book)
        self.ministerial_auth.get_excel_sheet(rpt_date, book)
        self.ministerial_268.get_excel_sheet(rpt_date, book)
        self.quarterly.get_excel_sheet(rpt_date, book)
        self.by_tenure.get_excel_sheet(rpt_date, book)
        self.by_cause.get_excel_sheet(rpt_date, book)
        self.region_by_tenure.get_excel_sheet(rpt_date, book)
        self.indicator.get_excel_sheet(rpt_date, book)
        self.by_cause_10YrAverage.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 1')
        book.save(response)

        return response


class MinisterialReport():
    """
    Report for Combined (Authorised and active 268b) fires. This is the sum of MinisterialAuth and Ministerial268b.
    """
    def __init__(self, ministerial_auth=None, ministerial_268=None, reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.ministerial_auth = ministerial_auth if ministerial_auth else MinisterialReportAuth(self.reporting_year)
        self.ministerial_268 = ministerial_268 if ministerial_268 else MinisterialReport268(self.reporting_year)
        self.rpt_map, self.item_map = self.create()

    def create(self):
        rpt_map_auth = self.ministerial_auth.rpt_map
        rpt_map_268 = self.ministerial_268.rpt_map
        item_map_auth = self.ministerial_auth.item_map
        item_map_268 = self.ministerial_268.item_map

        rpt_map = []
        item_map = {}
        for region in get_sorted_regions(True):
            map_auth = [i for i in rpt_map_auth if i.has_key(region.name)][0]
            map_268  = [i for i in rpt_map_268 if i.has_key(region.name)][0]
            rpt_map.append({
                region.name: dict(
                    pw_tenure=map_auth[region.name]['pw_tenure'] + map_268[region.name]['pw_tenure'],
                    area_pw_tenure=map_auth[region.name]['area_pw_tenure'] + map_268[region.name]['area_pw_tenure'],
                    total_all_tenure=map_auth[region.name]['total_all_tenure'] + map_268[region.name]['total_all_tenure'],
                    total_area=map_auth[region.name]['total_area'] + map_268[region.name]['total_area']
                )
            })

        key = 'Sub Total (Forest)'
        map_auth = [i for i in rpt_map_auth if i.has_key(key)][0]
        map_268  = [i for i in rpt_map_268 if i.has_key(key)][0]
        rpt_map.append({
            key: dict(
                pw_tenure=map_auth[key]['pw_tenure'] + map_268[key]['pw_tenure'],
                area_pw_tenure=map_auth[key]['area_pw_tenure'] + map_268[key]['area_pw_tenure'],
                total_all_tenure=map_auth[key]['total_all_tenure'] + map_268[key]['total_all_tenure'],
                total_area=map_auth[key]['total_area'] + map_268[key]['total_area']
            )
        })

        item_map['forest_pw_tenure'] = item_map_auth['forest_pw_tenure'] + item_map_268['forest_pw_tenure']
        item_map['forest_area_pw_tenure'] = item_map_auth['forest_area_pw_tenure'] + item_map_268['forest_area_pw_tenure']
        item_map['forest_total_all_tenure'] = item_map_auth['forest_total_all_tenure'] + item_map_268['forest_total_all_tenure'] 
        item_map['forest_total_area'] = item_map_auth['forest_total_area'] + item_map_268['forest_total_area']

        rpt_map.append(
            {'': ''}
        )

        for region in get_sorted_regions(False):
            map_auth = [i for i in rpt_map_auth if i.has_key(region.name)][0]
            map_268  = [i for i in rpt_map_268 if i.has_key(region.name)][0]
            rpt_map.append({
                region.name: dict(
                    pw_tenure=map_auth[region.name]['pw_tenure'] + map_268[region.name]['pw_tenure'],
                    area_pw_tenure=map_auth[region.name]['area_pw_tenure'] + map_268[region.name]['area_pw_tenure'],
                    total_all_tenure=map_auth[region.name]['total_all_tenure'] + map_268[region.name]['total_all_tenure'],
                    total_area=map_auth[region.name]['total_area'] + map_268[region.name]['total_area']
                )
            })

        key = 'Sub Total (Non Forest)'
        map_auth = [i for i in rpt_map_auth if i.has_key(key)][0]
        map_268  = [i for i in rpt_map_268 if i.has_key(key)][0]
        rpt_map.append({
            key: dict(
                pw_tenure=map_auth[key]['pw_tenure'] + map_268[key]['pw_tenure'],
                area_pw_tenure=map_auth[key]['area_pw_tenure'] + map_268[key]['area_pw_tenure'],
                total_all_tenure=map_auth[key]['total_all_tenure'] + map_268[key]['total_all_tenure'],
                total_area=map_auth[key]['total_area'] + map_268[key]['total_area']
            )
        })

        item_map['nonforest_total_all_tenure'] = item_map_auth['nonforest_total_all_tenure'] + item_map_268['nonforest_total_all_tenure']
        item_map['nonforest_total_area'] = item_map_auth['nonforest_total_area'] + item_map_268['nonforest_total_area']
                
        key = 'GRAND TOTAL'
        map_auth = [i for i in rpt_map_auth if i.has_key(key)][0]
        map_268  = [i for i in rpt_map_268 if i.has_key(key)][0]
        rpt_map.append({
            key: dict(
                pw_tenure=map_auth[key]['pw_tenure'] + map_268[key]['pw_tenure'],
                area_pw_tenure=map_auth[key]['area_pw_tenure'] + map_268[key]['area_pw_tenure'],
                total_all_tenure=map_auth[key]['total_all_tenure'] + map_268[key]['total_all_tenure'],
                total_area=map_auth[key]['total_area'] + map_268[key]['total_area']
            )
        })

        return rpt_map, item_map

    def export_final_csv(self, request, queryset):
        writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

        writer.writerow([
            "Region",
            "DBCA Interest",
            "Area DBCA Interest",
            "Total All Area",
            "Total Area",
        ])

        for row in self.rpt_map:
            for region, data in row.iteritems():
                writer.writerow([
                    region,
                    data['pw_tenure'],
                    data['area_pw_tenure'],
                    data['total_all_tenure'],
                    data['total_area'],
                ])
        return response

    def get_excel_sheet(self, rpt_date, book=Workbook()):
        # book = Workbook()
        sheet1 = book.add_sheet('Ministerial Report')
        sheet1 = book.get_sheet('Ministerial Report')

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Ministerial Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Total All Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Total Area", style=style_bold_gen)

        for row in self.rpt_map:
            for region, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if region == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in region.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), region, style=style_bold_gen)
                    row.write(col_no(), data['pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_area)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal_area)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)
        
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "See the Ministerial Report (Auth) tab for information re bushfires excluded from the area figures (not from the count figures) above.", style=style_normal)
        #book.save("/tmp/foobar.xls")
        #return sheet1

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/ministerial_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'ministerial_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        print '{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Interest', 'Area DBCA Interest', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                print '{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)

    def pdflatex(self, request, form_data):

        now = timezone.localtime(timezone.now())
        #report_date = now.strptime(request.GET.get('date'), '%Y-%m-%d').date()
        report_date = now

        #template = request.GET.get("template", "pfp")
        template = "ministerial_report"
        response = HttpResponse(content_type='application/pdf')
        filename = template + ".pdf"
        timestamp = now.isoformat().rsplit(
            ".")[0].replace(":", "")
        if template == "ministerial_report":
            downloadname = "ministerial_report_" + report_date.strftime('%Y-%m-%d') + ".pdf"
        else:
            downloadname = "ministerial_report_" + template + "_" + report_date.strftime('%Y-%m-%d') + ".pdf"
        error_response = HttpResponse(content_type='text/html')
        errortxt = downloadname.replace(".pdf", ".errors.txt.html")
        error_response['Content-Disposition'] = (
            '{0}; filename="{1}"'.format(
            "inline", errortxt))

        subtitles = {
            "ministerial_report": "Ministerial Report",
            #"form268a": "268a - Planned Burns",
        }
        embed = False if request.GET.get("embed") == "false" else True

        context = {
            'user': request.user.get_full_name(),
            'report_date': report_date.strftime('%e %B %Y').strip(),
            'time': report_date.strftime('%H:%M'),
            'current_finyear': self.reporting_year,
            'rpt_map': self.rpt_map,
            'item_map': self.item_map,
            'form': form_data,
            'embed': embed,
            'headers': request.GET.get("headers", True),
            'title': request.GET.get("title", "Bushfire Reporting System"),
            'subtitle': subtitles.get(template, ""),
            'timestamp': now,
            'downloadname': downloadname,
            'settings': settings,
            'baseurl': request.build_absolute_uri("/")[:-1]
        }
        disposition = "attachment"
        #disposition = "inline"
        response['Content-Disposition'] = (
            '{0}; filename="{1}"'.format(
                disposition, downloadname))

        folder = None
        try:
            folder,pdf_file = generate_pdf("latex/{}.tex".format(template),context=context,request=request,check_output=False)
            with open(pdf_file) as f:
                response.write(f.read())
            logger.debug("Finally: returning PDF response.")
            return response
        finally:
            if folder:
                shutil.rmtree(folder)


class MinisterialReport268():
    """
    Report for active 268b bushfires only
    """
    def __init__(self,reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.rpt_map, self.item_map = self.create()

    def get_268_data(self, dbca_initial_control=None):
        """ Retrieves the 268b fires from PBS and Aggregates the Area and Number count by region """
        qs_regions = get_sorted_regions()

        if dbca_initial_control:
            # get the fires managed by DBCA
            outstanding_fires = list(Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED], initial_control=Agency.DBCA,reporting_year__lte=self.reporting_year).values_list('fire_number', flat=True))
        else:
            outstanding_fires = list(Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED],reporting_year__lte=self.reporting_year).values_list('fire_number', flat=True))

        pbs_fires_dict = get_pbs_bushfires(outstanding_fires) or []

        if not dbca_initial_control:
            self.pbs_fires_dict = pbs_fires_dict
            #logger.info("self.pbs_fires_dict: " + str(self.pbs_fires_dict))
            self.found_fires = [i['fire_id'] for i in self.pbs_fires_dict]
            self.missing_fires = list(set(outstanding_fires).difference(self.found_fires)) # fire_numbers not returned from PB

        rpt_map = {}
        for i in pbs_fires_dict:                                                                       
            region_id = i['region']

            exists = [i for r in qs_regions if r.id==region_id]
            if exists:
                if rpt_map.has_key(region_id):
                    rpt_map[region_id]['area'] = rpt_map[region_id]['area'] + float(i['area'])
                    rpt_map[region_id]['number'] = rpt_map[region_id]['number'] + 1
                            
                else:
                    rpt_map[region_id] = {
                        'area' : float(i['area']),
                        'number' : 1
                    }

            else:
                raise Exception("PBS Region id({}) Not Found in BFRS".format(region_id))

        return rpt_map

    def create(self):
        # Group By Region

        data_268 = self.get_268_data()
        data_268_pw = self.get_268_data('DBCA')

        rpt_map = []
        item_map = {}
        net_forest_pw_tenure      = 0
        net_forest_area_pw_tenure = 0
        net_forest_total_all_tenure = 0
        net_forest_total_area     = 0

        for region in get_sorted_regions(True):
            if data_268_pw.has_key(region.id):
                pw_tenure      = data_268_pw[region.id]['number']
                area_pw_tenure = data_268_pw[region.id]['area']
            else:
                pw_tenure      = 0
                area_pw_tenure = 0.0

            if data_268.has_key(region.id):
                total_all_tenure = data_268[region.id]['number']
                total_area       = data_268[region.id]['area']
            else:
                total_all_tenure = 0
                total_area       = 0.0

            rpt_map.append(
                {region.name: dict(pw_tenure=pw_tenure, area_pw_tenure=area_pw_tenure, total_all_tenure=total_all_tenure, total_area=total_area)}
            )
                
            net_forest_pw_tenure      += pw_tenure 
            net_forest_area_pw_tenure += area_pw_tenure
            net_forest_total_all_tenure += total_all_tenure
            net_forest_total_area     += total_area

        rpt_map.append(
            {'Sub Total (Forest)': dict(pw_tenure=net_forest_pw_tenure, area_pw_tenure=net_forest_area_pw_tenure, total_all_tenure=net_forest_total_all_tenure, total_area=net_forest_total_area)}
        )

        item_map['forest_pw_tenure'] = net_forest_pw_tenure
        item_map['forest_area_pw_tenure'] = net_forest_area_pw_tenure
        item_map['forest_total_all_tenure'] = net_forest_total_all_tenure
        item_map['forest_total_area'] = net_forest_total_area

        # add a white space/line between forest and non-forest region tabulated info
        rpt_map.append(
            {'': ''}
        )

        net_nonforest_pw_tenure      = 0
        net_nonforest_area_pw_tenure = 0
        net_nonforest_total_all_tenure = 0
        net_nonforest_total_area     = 0

        for region in get_sorted_regions(False):
            if data_268_pw.has_key(region.id):
                pw_tenure      = data_268_pw[region.id]['number']
                area_pw_tenure = data_268_pw[region.id]['area']
            else:
                pw_tenure      = 0
                area_pw_tenure = 0.0

            if data_268.has_key(region.id):
                total_all_tenure = data_268[region.id]['number']
                total_area       = data_268[region.id]['area']
            else:
                total_all_tenure = 0
                total_area       = 0.0

            rpt_map.append(
                {region.name: dict(pw_tenure=pw_tenure, area_pw_tenure=area_pw_tenure, total_all_tenure=total_all_tenure, total_area=total_area)}
            )
                
            net_nonforest_pw_tenure      += pw_tenure 
            net_nonforest_area_pw_tenure += area_pw_tenure
            net_nonforest_total_all_tenure += total_all_tenure
            net_nonforest_total_area     += total_area

        rpt_map.append(
            {'Sub Total (Non Forest)': dict(pw_tenure=net_nonforest_pw_tenure, area_pw_tenure=net_nonforest_area_pw_tenure, total_all_tenure=net_nonforest_total_all_tenure, total_area=net_nonforest_total_area)}
        )

        item_map['nonforest_total_all_tenure'] = net_nonforest_total_all_tenure
        item_map['nonforest_total_area'] = net_nonforest_total_area
                
        rpt_map.append(
            {'GRAND TOTAL': dict(
                pw_tenure=net_forest_pw_tenure + net_nonforest_pw_tenure, 
                area_pw_tenure=net_forest_area_pw_tenure + net_nonforest_area_pw_tenure, 
                total_all_tenure=net_forest_total_all_tenure + net_nonforest_total_all_tenure, 
                total_area=net_forest_total_area + net_nonforest_total_area
            )}
        )
                
        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        # book = Workbook()
        sheet1 = book.add_sheet('Ministerial Report (268)')
        sheet1 = book.get_sheet('Ministerial Report (268)')

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Ministerial Report 268')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Total All Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Total Area", style=style_bold_gen)

        for row in self.rpt_map:
            for region, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if region == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in region.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), region, style=style_bold_gen)
                    row.write(col_no(), data['pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_area)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal_area)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Outstanding Fires (Contributing)", style=style_bold_gen)
        hdr.write(col_no(), "Area (ha)", style=style_bold_area)
        for data in self.pbs_fires_dict:
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), data['fire_id'], style=style_normal)
            row.write(col_no(), float(data['area']), style=style_normal_area)

        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Outstanding Fires (Non-contributing)", style=style_bold_gen)
        for fire_id in self.missing_fires:
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), fire_id, style=style_normal)

        #book.save("/tmp/foobar.xls")
        #return sheet1

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/ministerial_268_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'ministerial_268_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response


class MinisterialReportAuth():
    """
    Report for Authorised fires Only
    """
    def __init__(self, reporting_year=None, overlap_ids=[]):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.overlap_ids = overlap_ids
        self.rpt_map, self.item_map, self.excluded_bf_info = self.create()

    def create(self):
        rpt_map = []
        item_map = {}
        net_forest_pw_tenure      = 0
        net_forest_area_pw_tenure = 0
        net_forest_total_all_area = 0
        net_forest_total_area     = 0
        excluded_bfs_general_info = {}
        excluded_bfs_region_info = {}
        excluded_bfs_tenure_info = {}

        count_sql = """
        SELECT r.region_id,count(*)
        FROM 
            ((SELECT a.region_id,a.id
            FROM reporting_bushfire a JOIN bfrs_tenure t ON a.tenure_id = t.id
            WHERE a.report_status IN {report_statuses} AND a.reporting_year={reporting_year} AND a.fire_not_found=false {{agency_condition}}
            )
            UNION
            (SELECT b.region_id,b.id
            FROM reporting_bushfire b JOIN reporting_bushfire c ON b.valid_bushfire_id = c.id AND c.report_status IN {report_statuses} AND c.reporting_year={reporting_year} AND c.fire_not_found=false JOIN bfrs_tenure t ON b.tenure_id = t.id 
            WHERE b.report_status = {status_merged}  {{agency_condition}}
            )) as r
        group by r.region_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            reporting_year = self.reporting_year,
            status_merged = Bushfire.STATUS_MERGED
        )

        area_sql = """
        SELECT bf.region_id, SUM(ab.area) AS total_all_regions_area, SUM(bf.area) AS total_area
        FROM reporting_bushfire bf JOIN reporting_areaburnt ab ON bf.id = ab.bushfire_id JOIN bfrs_tenure t ON ab.tenure_id = t.id
        WHERE bf.report_status IN {report_statuses} AND bf.reporting_year={reporting_year} AND bf.fire_not_found=false AND t.report_group='ALL REGIONS'  {{agency_condition}} 
        GROUP BY bf.region_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED, Bushfire.STATUS_REVIEWED]])),
            reporting_year = self.reporting_year
        )

        dbca_count_data = {}
        total_count_data = {}

        dbca_area_data = {}
        total_area_data = {}

        with connection.cursor() as cursor:
            sql = count_sql.format(agency_condition = "AND t.dbca_interest IS TRUE")
            cursor.execute(sql)
            for result in cursor.fetchall():
                dbca_count_data[result[0]] = result[1] or 0

            sql = count_sql.format(agency_condition = "")
            cursor.execute(sql)
            for result in cursor.fetchall():
                total_count_data[result[0]] = result[1] or 0

            sql = area_sql.format(agency_condition = "AND t.dbca_interest IS TRUE")
            cursor.execute(sql)
            for result in cursor.fetchall():
                dbca_area_data[result[0]] = result[1] or 0

            sql = area_sql.format(agency_condition = "")
            logger.info("sql: " + sql)
            cursor.execute(sql)
            for result in cursor.fetchall():
                total_area_data[result[0]] = result[1] or 0
        logger.info("total_area_data: " + str(total_area_data))
        for region in get_sorted_regions(True):
            pw_tenure      = dbca_count_data.get(region.id, 0)
            area_pw_tenure = round(dbca_area_data.get(region.id, 0), 2) 
            total_all_area = total_count_data.get(region.id, 0)
            total_area     = round(total_area_data.get(region.id, 0), 2)

            rpt_map.append(
                {region.name: dict(pw_tenure=pw_tenure, area_pw_tenure=area_pw_tenure, total_all_tenure=total_all_area, total_area=total_area)}
            )
                
            net_forest_pw_tenure      += pw_tenure 
            net_forest_area_pw_tenure += area_pw_tenure
            net_forest_total_all_area += total_all_area
            net_forest_total_area     += total_area

        rpt_map.append(
            {'Sub Total (Forest)': dict(pw_tenure=net_forest_pw_tenure, area_pw_tenure=net_forest_area_pw_tenure, total_all_tenure=net_forest_total_all_area, total_area=net_forest_total_area)}
        )

        item_map['forest_pw_tenure'] = net_forest_pw_tenure
        item_map['forest_area_pw_tenure'] = net_forest_area_pw_tenure
        item_map['forest_total_all_tenure'] = net_forest_total_all_area
        item_map['forest_total_area'] = net_forest_total_area

        # add a white space/line between forest and non-forest region tabulated info
        rpt_map.append(
            {'': ''}
        )

        net_nonforest_pw_tenure      = 0
        net_nonforest_area_pw_tenure = 0
        net_nonforest_total_all_area = 0
        net_nonforest_total_area     = 0

        for region in get_sorted_regions(False):
            pw_tenure      = dbca_count_data.get(region.id,0)
            area_pw_tenure = round(dbca_area_data.get(region.id,0), 2) 
            total_all_area = total_count_data.get(region.id,0)
            total_area     = round(total_area_data.get(region.id,0), 2)

            rpt_map.append(
                {region.name: dict(pw_tenure=pw_tenure, area_pw_tenure=area_pw_tenure, total_all_tenure=total_all_area, total_area=total_area)}
            )
                
            net_nonforest_pw_tenure      += pw_tenure 
            net_nonforest_area_pw_tenure += area_pw_tenure
            net_nonforest_total_all_area += total_all_area
            net_nonforest_total_area     += total_area

        rpt_map.append(
            {'Sub Total (Non Forest)': dict(pw_tenure=net_nonforest_pw_tenure, area_pw_tenure=net_nonforest_area_pw_tenure, total_all_tenure=net_nonforest_total_all_area, total_area=net_nonforest_total_area)}
        )

        item_map['nonforest_total_all_tenure'] = net_nonforest_total_all_area
        item_map['nonforest_total_area'] = net_nonforest_total_area
                
        rpt_map.append(
            {'GRAND TOTAL': dict(
                pw_tenure=net_forest_pw_tenure + net_nonforest_pw_tenure, 
                area_pw_tenure=net_forest_area_pw_tenure + net_nonforest_area_pw_tenure, 
                total_all_tenure=net_forest_total_all_area + net_nonforest_total_all_area, 
                total_area=net_forest_total_area + net_nonforest_total_area
            )}
        )
        
        # Excluded bushfires
        excluded_bf_info = {
            "general":            excluded_bfs_general_info,
            "region_info":      excluded_bfs_region_info,
            "tenure_info":      excluded_bfs_tenure_info
            }
                
        return rpt_map, item_map, excluded_bf_info

    def export_final_csv(self, request, queryset):
        writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

        writer.writerow([
            "Region",
            "DBCA Interest",
            "Area DBCA Interest",
            "Total All Area",
            "Total Area",
        ])

        for row in self.rpt_map:
            for region, data in row.iteritems():
                writer.writerow([
                    region,
                    data['pw_tenure'],
                    data['area_pw_tenure'],
                    data['total_all_tenure'],
                    data['total_area'],
                ])
        return response

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        # book = Workbook()
        sheet1 = book.add_sheet('Ministerial Report (Auth)')
        sheet1 = book.get_sheet('Ministerial Report (Auth)')

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Ministerial Report (Authorised)')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Total All Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Total Area", style=style_bold_gen)

        for row in self.rpt_map:
            for region, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if region == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in region.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), region, style=style_bold_gen)
                    row.write(col_no(), data['pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_area)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal_area)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)


    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/ministerial_auth_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'ministerial_auth_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        print '{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Interest', 'Area DBCA Interest', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                print '{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)

    def pdflatex(self, request, form_data):
        now = timezone.localtime(timezone.now())
        report_date = now
        template = "ministerial_auth_report"
        response = HttpResponse(content_type='application/pdf')
        filename = template + ".pdf"
        timestamp = now.isoformat().rsplit(
            ".")[0].replace(":", "")
        if template == "ministerial_auth_report":
            downloadname = "ministerial_auth_report_" + report_date.strftime('%Y-%m-%d') + ".pdf"
        else:
            downloadname = "ministerial_auth_report_" + template + "_" + report_date.strftime('%Y-%m-%d') + ".pdf"
        error_response = HttpResponse(content_type='text/html')
        errortxt = downloadname.replace(".pdf", ".errors.txt.html")
        error_response['Content-Disposition'] = (
            '{0}; filename="{1}"'.format(
            "inline", errortxt))

        subtitles = {
            "ministerial_report": "Ministerial Report",
            #"form268a": "268a - Planned Burns",
        }
        embed = False if request.GET.get("embed") == "false" else True

        context = {
            'user': request.user.get_full_name(),
            'report_date': report_date.strftime('%e %B %Y').strip(),
            'time': report_date.strftime('%H:%M'),
            'current_finyear': self.reporting_year,
            'rpt_map': self.rpt_map,
            'item_map': self.item_map,
            'form': form_data,
            'embed': embed,
            'headers': request.GET.get("headers", True),
            'title': request.GET.get("title", "Bushfire Reporting System"),
            'subtitle': subtitles.get(template, ""),
            'timestamp': now,
            'downloadname': downloadname,
            'settings': settings,
            'baseurl': request.build_absolute_uri("/")[:-1]
        }
        disposition = "attachment"
        #disposition = "inline"
        response['Content-Disposition'] = (
            '{0}; filename="{1}"'.format(
                disposition, downloadname))

        folder = None
        try:
            folder,pdf_file = generate_pdf("latex/{}.tex".format(template),context=context,request=request,check_output=False)
            with open(pdf_file) as f:
                response.write(f.read())
            logger.debug("Finally: returning PDF response.")
            return response
        finally:
            if folder:
                shutil.rmtree(folder)


class QuarterlyReport():
    def __init__(self, reporting_year=None, overlap_ids=[]):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.overlap_ids = overlap_ids
        self.rpt_map, self.item_map = self.create()
        #logger.info("overlap_ids: " + str(overlap_ids))
        
    def create(self):
        """
        To Test:
            from bfrs.reports import QuarterlyReport
            q=QuarterlyReport()
            q.display()
        """
        rpt_map = []
        item_map = {}

        count_sql = """
        SELECT COUNT(*)
        FROM 
          ((SELECT bf1.region_id, bf1.id
          FROM reporting_bushfire bf1 JOIN bfrs_region r ON bf1.region_id = r.id AND r.forest_region = {{forest_region}} JOIN bfrs_tenure t ON bf1.tenure_id = t.id
          WHERE bf1.report_status IN {report_statuses} AND bf1.reporting_year = {reporting_year} AND bf1.fire_not_found=False {{agency_condition}}
          )
          UNION
          (SELECT bf2.region_id, bf2.id
          FROM reporting_bushfire bf2 
              JOIN bfrs_region r2 ON bf2.region_id = r2.id AND r2.forest_region = {{forest_region}}
              JOIN reporting_bushfire bf3 ON bf2.valid_bushfire_id = bf3.id AND bf3.report_status IN {report_statuses} AND bf3.reporting_year = {reporting_year} AND bf3.fire_not_found=false 
              JOIN bfrs_tenure t ON bf2.tenure_id = t.id
          WHERE bf2.report_status = {status_merged} {{agency_condition}}
          )) AS x
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            reporting_year = self.reporting_year,
            status_merged = Bushfire.STATUS_MERGED
        )

        area_sql = """
        SELECT SUM(ab.area) AS total_all_regions_area, SUM(bf.area) AS total_area 
        FROM reporting_bushfire bf JOIN bfrs_region r ON bf.region_id = r.id JOIN reporting_areaburnt ab ON bf.id = ab.bushfire_id JOIN bfrs_tenure t ON ab.tenure_id = t.id
        WHERE bf.report_status IN {report_statuses} AND bf.reporting_year = {reporting_year} AND bf.fire_not_found=False AND r.forest_region = {{forest_region}} {{agency_condition}} AND t.report_group = 'ALL REGIONS'
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            reporting_year = self.reporting_year
        )

        with connection.cursor() as cursor:
            cursor.execute(count_sql.format(
                forest_region = 'true',
                agency_condition =  "AND t.dbca_interest IS TRUE"
            ))
            result = cursor.fetchone()
            forest_pw_tenure = result[0] or 0
            logger.info("Quarterly: forest region + DBCA interest count complete")

            cursor.execute(area_sql.format(
                forest_region = 'true',
                agency_condition = "AND t.dbca_interest IS TRUE"
            ))
            result = cursor.fetchone()
            forest_area_pw_tenure = result[0] or 0
            logger.info("Quarterly: forest region + DBCA interest area complete")

            cursor.execute(count_sql.format(
                forest_region = 'true',
                agency_condition = "AND t.dbca_interest IS NOT TRUE"
            ))
            result = cursor.fetchone()
            forest_non_pw_tenure = result[0] or 0
            logger.info("Quarterly: forest region + Non DBCA interest count complete")

            cursor.execute(area_sql.format(
                forest_region = 'true',
                agency_condition = "AND t.dbca_interest IS NOT TRUE"
            ))
            result = cursor.fetchone()
            forest_area_non_pw_tenure = result[0] or 0
            logger.info("Quarterly: forest region + Non DBCA interest area complete")

            forest_tenure_total = forest_pw_tenure + forest_non_pw_tenure 
            forest_area_total = forest_area_pw_tenure + forest_area_non_pw_tenure

            rpt_map.append(
                {'Forest Regions': dict(
                    pw_tenure=forest_pw_tenure, area_pw_tenure=forest_area_pw_tenure, 
                    non_pw_tenure=forest_non_pw_tenure, area_non_pw_tenure=forest_area_non_pw_tenure, 
                    total_all_tenure=forest_tenure_total, total_area=forest_area_total
                )}
            )

            cursor.execute(count_sql.format(
                forest_region = 'false',
                agency_condition = "AND t.dbca_interest IS TRUE"
            ))
            result = cursor.fetchone()
            nonforest_pw_tenure = result[0] or 0
            logger.info("Quarterly: Non forest region + DBCA interest count complete")

            cursor.execute(area_sql.format(
                forest_region = 'false',
                agency_condition = "AND t.dbca_interest IS TRUE"
            ))
            result = cursor.fetchone()
            nonforest_area_pw_tenure = result[0] or 0
            logger.info("Quarterly: Non forest region + DBCA interest area complete")

            cursor.execute(count_sql.format(
                forest_region = 'false',
                agency_condition = "AND t.dbca_interest IS NOT TRUE"
            ))
            result = cursor.fetchone()
            nonforest_non_pw_tenure = result[0] or 0
            logger.info("Quarterly: Non forest region + non DBCA interest count complete")

            cursor.execute(area_sql.format(
                forest_region = 'false',
                agency_condition = "AND t.dbca_interest IS NOT TRUE"
            ))
            result = cursor.fetchone()
            nonforest_area_non_pw_tenure = result[0] or 0
            logger.info("Quarterly: Non forest region + Non DBCA interest area complete")

            nonforest_tenure_total = nonforest_pw_tenure + nonforest_non_pw_tenure 
            nonforest_area_total = nonforest_area_pw_tenure + nonforest_area_non_pw_tenure

            rpt_map.append(
                {'Non Forest Regions': dict(
                    pw_tenure=nonforest_pw_tenure, area_pw_tenure=nonforest_area_pw_tenure, 
                    non_pw_tenure=nonforest_non_pw_tenure, area_non_pw_tenure=nonforest_area_non_pw_tenure, 
                    total_all_tenure=nonforest_tenure_total, total_area=nonforest_area_total
                )}
            )

        rpt_map.append(
            {'TOTAL': dict(
                pw_tenure=forest_pw_tenure + nonforest_pw_tenure, area_pw_tenure=forest_area_pw_tenure + nonforest_area_pw_tenure, 
                non_pw_tenure=forest_non_pw_tenure + nonforest_non_pw_tenure, area_non_pw_tenure=forest_area_non_pw_tenure + nonforest_area_non_pw_tenure, 
                total_all_tenure=forest_tenure_total + nonforest_tenure_total, total_area=forest_area_total + nonforest_area_total
            )}
        )

        logger.info("Quarterly: create complete")        
        return rpt_map, item_map

    def escape_burns(self):
        #return Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, reporting_year=self.reporting_year, cause__name__icontains='escape')
        #return Bushfire.objects.filter(authorised_by__isnull=False, reporting_year=self.reporting_year, cause__name__icontains='escape').exclude(report_status=Bushfire.STATUS_INVALIDATED)
        return Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED], reporting_year=self.reporting_year,fire_not_found=False, cause__name__icontains='escape')

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        # book = Workbook()
        sheet1 = book.add_sheet('Quarterly Report')
        sheet1 = book.get_sheet('Quarterly Report')

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Quarterly Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Non DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Area Non DBCA Interest", style=style_bold_gen)
        hdr.write(col_no(), "Total All Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Total Area", style=style_bold_gen)

        for row in self.rpt_map:
            for region, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if region == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in region.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), region, style=style_bold_gen)
                    row.write(col_no(), data['pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_area)
                    row.write(col_no(), data['non_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_non_pw_tenure'], style=style_bold_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_area)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal_area)
                    row.write(col_no(), data['non_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['area_non_pw_tenure'], style=style_normal_area)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal)
                    row.write(col_no(), data['total_area'], style=style_normal_area)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

        escape_burns = self.escape_burns()
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(0, 'Escape Fires', style=style_bold_gen)
        hdr.write(1, escape_burns.count() )

        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Bushfire Number", style=style_bold_gen)
        hdr.write(col_no(), "Name", style=style_bold_gen)
        hdr.write(col_no(), "Cause", style=style_bold_gen)
        hdr.write(col_no(), "Prescribed Burn ID", style=style_bold_gen)
        for bushfire in escape_burns:
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), bushfire.fire_number)
            row.write(col_no(), bushfire.name)
            row.write(col_no(), bushfire.cause.report_name)
            row.write(col_no(), bushfire.prescribed_burn_id)

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/quarterly_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'quarterly_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Interest', 'Area DBCA Interest', 'Non DBCA Interest', 'Area Non DBCA Interest', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                if region and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['non_pw_tenure'], data['area_non_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)
                else:
                    print


class BushfireByTenureReport():
    def __init__(self,reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.rpt_map, self.item_map, self.other_report_group_fires_info = self.create()
        logger.info("Starting BushfireByTenureReport")

    def create(self):
        # Group By Region
        #qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED)
        report_group_sql = """
        SELECT DISTINCT report_group, report_group_order FROM bfrs_tenure WHERE report_group_order > 0 ORDER BY report_group_order
        """
        report_name_sql = """
        SELECT DISTINCT report_name, report_order FROM bfrs_tenure WHERE report_group = '{report_group}' ORDER BY report_order
        """
        count_sql = """
        SELECT b.report_name, count(*) 
        FROM (
            (SELECT 
                a1.tenure_id,
                a1.fire_number
            FROM reporting_bushfire a1
            WHERE a1.report_status IN {report_statuses} AND a1.reporting_year = {{year}} AND a1.fire_not_found = false
            )
            UNION
            (SELECT 
                b1.tenure_id,
                b1.fire_number
            FROM reporting_bushfire b1 
                JOIN reporting_bushfire b2 ON b1.valid_bushfire_id = b2.id AND b2.report_status IN {report_statuses} AND b2.reporting_year = {{year}} AND b2.fire_not_found = false
            WHERE b1.report_status = {status_merged}
            )
         ) a JOIN bfrs_tenure b ON a.tenure_id = b.id
        WHERE b.report_group='{{report_group}}'
        GROUP BY b.report_name,b.report_order
        ORDER BY b.report_order
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED, Bushfire.STATUS_REVIEWED]])),
            status_merged = Bushfire.STATUS_MERGED
        )

        area_sql = """
        SELECT t.report_name, SUM(ab.area) AS area 
        FROM reporting_bushfire bf JOIN reporting_areaburnt ab ON bf.id = ab.bushfire_id JOIN bfrs_tenure t ON ab.tenure_id = t.id
        WHERE bf.report_status IN {report_statuses} AND bf.reporting_year = {{year}} AND bf.fire_not_found = false AND t.report_group = '{{report_group}}'
        GROUP BY t.report_name, t.report_order
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]]))
        )
        
        other_report_group_sql = """
        SELECT bf.id, bf.name, bf.fire_number, r.name
        FROM reporting_bushfire bf JOIN reporting_areaburnt ab ON bf.id = ab.bushfire_id JOIN bfrs_region r ON bf.region_id = r.id
        WHERE ab.tenure_id = 20 AND bf.report_status in {report_statuses} AND bf.reporting_year = {year} AND bf.fire_not_found = false AND ab.area >= 1;
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            year = self.reporting_year
        )

        rpt_map = []
        
        report_groups = []
        with connection.cursor() as cursor:
            cursor.execute(report_group_sql)
            for result in cursor.fetchall():
                report_groups.append(result[0])

            for report_group in report_groups:
                counts = []
                areas = []
                rpt_group_map = []
                rpt_map.append((report_group, rpt_group_map))
                for y in (self.reporting_year - 2, self.reporting_year - 1, self.reporting_year):
                    year_counts = {"total":0}
                    counts.append(year_counts)
                    cursor.execute(count_sql.format(year=y, report_group=report_group))
                    for result in cursor.fetchall():
                        year_counts[result[0]] = result[1] or 0
                        year_counts["total"] += result[1] or 0

                    year_areas = {"total":0}
                    areas.append(year_areas)
                    cursor.execute(area_sql.format(year=y, report_group=report_group))
                    for result in cursor.fetchall():
                        year_areas[result[0]] = result[1] or 0
                        year_areas["total"] += result[1] or 0

                cursor.execute(report_name_sql.format(report_group=report_group))
                for result in cursor.fetchall():
                    report_name = result[0]
                    rpt_group_map.append(
                        {report_name: dict(
                            count2=counts[0].get(report_name,0), 
                            count1=counts[1].get(report_name,0), 
                            count0=counts[2].get(report_name,0), 
                            area2=areas[0].get(report_name,0), 
                            area1=areas[1].get(report_name,0), 
                            area0=areas[2].get(report_name,0)
                        )}
                    )
                
                rpt_group_map.append(
                    {'Total': dict(
                        count2=counts[0].get("total",0), 
                        count1=counts[1].get("total",0), 
                        count0=counts[2].get("total",0), 
                        area2=areas[0].get("total",0), 
                        area1=areas[1].get("total",0), 
                        area0=areas[2].get("total",0)
                    )}
                )
                
                # 'Other' report group polys >= 1 ha
                other_report_group_fires_info = {}
                cursor.execute(other_report_group_sql)
                for result in cursor.fetchall():
                    other_report_group_fires_info[result[0]] = (result[1], result[2], result[3])
                
        logger.info("BushfireByTenureReport create complete")
        return rpt_map, None, other_report_group_fires_info

    def get_excel_sheet(self, rpt_date, book=Workbook()):
        year0 = str(self.reporting_year) + '/' + str(self.reporting_year+1)
        year1 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year2 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        # book = Workbook()
        sheet1 = book.add_sheet('Bushfire By Tenure Report')
        sheet1 = book.get_sheet('Bushfire By Tenure Report')

#        # font BOLD
#        style = XFStyle() 
#        font = Font()
#        font.bold = True
#        style.font = font
#
#        # font BOLD and Center Aligned
#        style_center = XFStyle()
#        font = Font()
#        font.bold = True
#        style_center.font = font
#        style_center.alignment.horz = Alignment.HORZ_CENTER


        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Bushfire By Tenure Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        for report_group, rpt_group_map in self.rpt_map:
            hdr = sheet1.row(row_no())
            hdr = sheet1.row(row_no())
            row = row_no()
            sheet1.write_merge(row, row, 1, 3, "Number", style_bold)
            sheet1.write_merge(row, row, 4, 6, "Area (ha)", style_bold)
            hdr = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            hdr.write(col_no(), report_group, style=style_bold_gen)
            hdr.write(col_no(), year2, style=style_bold_gen)
            hdr.write(col_no(), year1, style=style_bold_gen)
            hdr.write(col_no(), year0, style=style_bold_gen)

            hdr.write(col_no(), year2, style=style_bold_gen)
            hdr.write(col_no(), year1, style=style_bold_gen)
            hdr.write(col_no(), year0, style=style_bold_gen)

            for row in rpt_group_map:
                for tenure, data in row.iteritems():

                    row = sheet1.row(row_no())
                    col_no = lambda c=count(): next(c)
                    if tenure == '':
                        #row = sheet1.row(row_no())
                        continue
                    elif 'total' in tenure.lower():
                        #row = sheet1.row(row_no())
                        row.write(col_no(), tenure, style=style_bold_gen)
                        row.write(col_no(), data['count2'] if data['count2'] > 0 else '', style=style_bold_gen)
                        row.write(col_no(), data['count1'] if data['count1'] > 0 else '', style=style_bold_gen)
                        row.write(col_no(), data['count0'], style=style_bold_gen)
                        row.write(col_no(), data['area2'] if data['area2'] > 0 else '', style=style_bold_area)
                        row.write(col_no(), data['area1'] if data['area1'] > 0 else '', style=style_bold_area)
                        row.write(col_no(), data['area0'], style=style_bold_area)
                    else:
                        row.write(col_no(), tenure, style=style_normal )
                        row.write(col_no(), data['count2'] if data['count2'] > 0 else '', style=style_normal_int)
                        row.write(col_no(), data['count1'] if data['count1'] > 0 else '', style=style_normal_int)
                        row.write(col_no(), data['count0'], style=style_normal_int)
                        row.write(col_no(), data['area2'] if data['area2'] > 0 else '', style=style_normal_area)
                        row.write(col_no(), data['area1'] if data['area1'] > 0 else '', style=style_normal_area)
                        row.write(col_no(), data['area0'], style=style_normal_area)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)
        
        # 'OTHER' REPORT GROUP FIRES
        if len(self.other_report_group_fires_info) > 0:
            col_no = lambda c=count(): next(c)
            hdr = sheet1.row(row_no())
            hdr = sheet1.row(row_no())
            note = "The following fires have a tenure component which comes under the 'OTHER' category and have an area >= 1 ha.  It is likely they extend into SA or the NT and may need a manual check."
            hdr.write(col_no(), note, style=style_normal)
            col_no = lambda c=count(): next(c)
            hdr = sheet1.row(row_no())
            hdr.write(col_no(),  "ID",  style=style_bold_int)
            hdr.write(col_no(),  "Name",  style=style_bold_int)
            hdr.write(col_no(),  "Fire Number",  style=style_bold_int)
            hdr.write(col_no(),  "Designated region",  style=style_bold_int)
            for fire in self.other_report_group_fires_info:
                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                row.write(col_no(), str(fire), style = style_normal )
                row.write(col_no(), self.other_report_group_fires_info[fire][0], style = style_normal )
                row.write(col_no(), self.other_report_group_fires_info[fire][1], style = style_normal )
                row.write(col_no(), self.other_report_group_fires_info[fire][2], style = style_normal )

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_by_tenure_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'bushfire_by_tenure_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        year0 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year1 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        year2 = str(self.reporting_year-3) + '/' + str(self.reporting_year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Tenure', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for tenure, data in row.iteritems():
                if tenure and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(tenure, data['count2'], data['count1'], data['count0'], data['area2'], data['area1'], data['area0']).expandtabs(20)
                else:
                    print


class BushfireByCauseReport():
    def __init__(self,reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.rpt_map, self.item_map = self.create()
        logger.info("Starting BushfireByCauseReport")

    def create(self):
        rpt_map = []
        item_map = {}

        count_sql = """
        SELECT a.cause_id, COUNT(*)
        FROM ( 
            (SELECT COALESCE(a1.cause_id, 9) AS cause_id, a1.id
            FROM reporting_bushfire a1
            WHERE a1.report_status IN {report_statuses} AND a1.reporting_year = {{reporting_year}} AND a1.fire_not_found = false
            )
            UNION
            (SELECT COALESCE(b1.cause_id, 9) AS cause_id, b1.id
            FROM reporting_bushfire b1
                JOIN reporting_bushfire b2 ON b1.valid_bushfire_id = b2.id AND b2.report_status IN {report_statuses} AND b2.reporting_year = {{reporting_year}} AND b2.fire_not_found = false
            WHERE b1.report_status = {status_merged}
            )
          ) AS a
        GROUP BY cause_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            status_merged = Bushfire.STATUS_MERGED
        )

        area_sql = """
        SELECT COALESCE(a.cause_id,  9) AS cause_id, SUM(b.area) AS total_all_regions_area, SUM(a.area) AS total_area
        FROM reporting_bushfire a JOIN reporting_areaburnt b ON a.id = b.bushfire_id JOIN bfrs_tenure c ON b.tenure_id = c.id
        WHERE a.report_status IN {report_statuses} AND a.reporting_year = {{reporting_year}} AND a.fire_not_found = false AND c.report_group = 'ALL REGIONS'
        GROUP BY cause_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]]))
        )

        year_count_list = []
        year_total_count_list = []
        
        all_causes =  Cause.objects.all().order_by('report_order')

        with connection.cursor() as cursor:
            for year in range(self.reporting_year,self.reporting_year - 3,-1):
                year_count_data = {}
                year_count_list.append(year_count_data)
                year_total_count = 0
                if year >= 2017:
                    cursor.execute(count_sql.format(reporting_year=year))
                    for result in cursor.fetchall():
                        year_count_data[result[0]] = result[1] or 0
                        year_total_count += result[1] or 0
                else:
                    data = read_col(year,'count')[0]
                    for cause in all_causes:
                        row = [d for d in data if d.get('cause_id')==cause.id]
                        if len(row) > 0:
                            year_count_data[cause.id] = row[0].get('count') or 0
                            year_total_count += (row[0].get('count') or 0)
                        else:
                            year_count_data[cause.id] = 0
                year_total_count_list.append(year_total_count)
        for cause in all_causes:
            if rpt_map and cause.report_name in rpt_map[-1]:
                for i in range(0,len(year_count_list),1):
                    rpt_map[-1][cause.report_name]["count{}".format(i)] = rpt_map[-1][cause.report_name]["count{}".format(i)] + year_count_list[i].get(cause.id,0)
                    if year_total_count_list[i] == 0:
                        rpt_map[-1][cause.report_name]["perc{}".format(i)] = 0
                    else:
                        rpt_map[-1][cause.report_name]["perc{}".format(i)] = rpt_map[-1][cause.report_name]["count{}".format(i)] * 100 / (year_total_count_list[i] * 1.0)

            else:
                report_data = {}
                for i in range(0,len(year_count_list),1):
                    report_data["count{}".format(i)] = year_count_list[i].get(cause.id,0)
                    if year_total_count_list[i] == 0:
                        report_data["perc{}".format(i)] = 0
                    else:
                        report_data["perc{}".format(i)] = year_count_list[i].get(cause.id,0) * 100 / (year_total_count_list[i] * 1.0)
                rpt_map.append(
                    {cause.report_name: report_data}
                )
                
        report_total_data = {}
        for i in range(0,len(year_total_count_list),1):
            report_total_data["count{}".format(i)] = year_total_count_list[i]
            if year_total_count_list[i] == 0:
                report_total_data["perc{}".format(i)] = 0
            else:
                report_total_data["perc{}".format(i)] = year_total_count_list[i] * 100 / (year_total_count_list[i] * 1.0)

        rpt_map.append(
            {'Total': report_total_data}
        )
        logger.info("BushfireByCauseReport create complete" )
        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):
        year0 = str(self.reporting_year) + '/' + str(self.reporting_year+1)
        year1 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year2 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        # book = Workbook()
        sheet1 = book.add_sheet('Bushfire By Cause Report')
        sheet1 = book.get_sheet('Bushfire By Cause Report')

        # font BOLD
        style = XFStyle() 
        font = Font()
        font.bold = True
        style.font = font

        # font BOLD and Center Aligned
        style_center = XFStyle()
        font = Font()
        font.bold = True
        style_center.font = font
        style_center.alignment.horz = Alignment.HORZ_CENTER


        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style)
        hdr.write(1, 'Bushfire By Cause Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 1, 3, "Number", style_center)
        sheet1.write_merge(row, row, 4, 6, "Percent %", style_center)
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "ALL REGIONS", style=style)
        hdr.write(col_no(), year2, style=style)
        hdr.write(col_no(), year1, style=style)
        hdr.write(col_no(), year0, style=style)

        hdr.write(col_no(), year2, style=style)
        hdr.write(col_no(), year1, style=style)
        hdr.write(col_no(), year0, style=style)
        for row in self.rpt_map:
            for tenure, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if tenure == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in tenure.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), tenure, style=style_bold_gen)
                    row.write(col_no(), data['count2'], style=style_bold_gen)
                    row.write(col_no(), data['count1'], style=style_bold_gen)
                    row.write(col_no(), data['count0'], style=style_bold_gen)
                    row.write(col_no(), data['perc2'], style=style_bold_percentage)
                    row.write(col_no(), data['perc1'], style=style_bold_percentage)
                    row.write(col_no(), data['perc0'], style=style_bold_percentage)
                else:
                    row.write(col_no(), tenure, style=style_bold_gen )
                    row.write(col_no(), data['count2'], style=style_normal)
                    row.write(col_no(), data['count1'], style=style_normal)
                    row.write(col_no(), data['count0'], style=style_normal)
                    row.write(col_no(), data['perc2'], style=style_normal_percentage)
                    row.write(col_no(), data['perc1'], style=style_normal_percentage)
                    row.write(col_no(), data['perc0'], style=style_normal_percentage)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

        if MISSING_MAP:
            col_no = lambda c=count(): next(c)
            hdr = sheet1.row(row_no())
            hdr = sheet1.row(row_no())
            row = row_no()
            sheet1.write_merge(row, row, 0, 2, "NOTE: Errors in report", style_bold_red)
            for item in MISSING_MAP:
                hdr = sheet1.row(row_no())
                hdr.write(col_no(), item.get('name'), style=style_bold_yellow)
                hdr.write(col_no(), item.get('error'), style=style_bold_yellow)

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_by_cause_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'bushfire_by_cause_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        year0 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year1 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        year2 = str(self.reporting_year-3) + '/' + str(self.reporting_year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Cause', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for cause, data in row.iteritems():
                if cause and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(cause, data['count2'], data['count1'], data['count0'], data['perc2'], data['perc1'], data['perc0']).expandtabs(25)
                else:
                    print


class BushfireByRegionByTenureReport():
    def __init__(self, reporting_year=None, overlap_ids=[]):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.overlap_ids = overlap_ids
        logger.info("Startiing RegionByTenureReport; overlap ids: " + str(self.overlap_ids))
        self.rpt_map, self.tenure_names = self.create()

    def create(self):
        tenure_name_sql = """
        SELECT distinct report_name, report_order FROM bfrs_tenure WHERE report_group = 'ALL REGIONS' ORDER BY report_order
        """
        count_sql = """
        SELECT a.region_id, b.report_name, count(*)
        FROM (
            (SELECT a1.region_id, a1.tenure_id, a1.id
            FROM reporting_bushfire a1
            WHERE a1.report_status in {report_statuses} AND a1.reporting_year={{year}} AND a1.fire_not_found = false
            ) 
            UNION 
            (SELECT b1.region_id, b1.tenure_id, b1.id
            FROM reporting_bushfire b1
                JOIN reporting_bushfire b2 ON b1.valid_bushfire_id = b2.id AND b2.report_status IN {report_statuses} AND b2.reporting_year = {{year}} AND b2.fire_not_found = false
            WHERE b1.report_status = {status_merged}
            ) 
         ) AS a
            JOIN bfrs_tenure b ON a.tenure_id = b.id JOIN bfrs_region r ON a.region_id = r.id
            WHERE r.dbca AND b.report_group='ALL REGIONS'
        GROUP BY a.region_id,b.report_name, b.report_order
        ORDER BY a.region_id, b.report_name
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED, Bushfire.STATUS_REVIEWED]])),
            status_merged = Bushfire.STATUS_MERGED
        )
        
        area_sql = """
        SELECT ab.region_id, t.report_name, SUM(ab.area) AS area 
        FROM reporting_bushfire bf JOIN reporting_areaburnt ab ON bf.id = ab.bushfire_id JOIN bfrs_tenure t on ab.tenure_id = t.id JOIN bfrs_region r ON ab.region_id = r.id
        WHERE bf.report_status in {report_statuses} AND bf.reporting_year = {{year}} AND bf.fire_not_found = False AND t.report_group = 'ALL REGIONS' AND r.dbca
        GROUP BY ab.region_id, t.report_name, t.report_order
        ORDER BY ab.region_id, t.report_name
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]]))
        )

        rpt_map = []
        count_data = {}
        area_data = {}
        tenure_names = []
        
        with connection.cursor() as cursor:
            cursor.execute(tenure_name_sql)
            for result in cursor.fetchall():
                tenure_names.append(result[0])

            cursor.execute(count_sql.format(year=self.reporting_year))
            for result in cursor.fetchall():
                region_id = result[0]
                tenure_name = result[1]
                report_count = result[2] or 0

                if region_id not in count_data:
                    count_data[region_id] = {}
                count_data[region_id][tenure_name] = count_data[region_id].get(tenure_name,0) + report_count
            logger.info("Region by Tenure: count complete")
            #cursor.execute(area_sql.format(year=self.reporting_year, excluded_ids=str(excluded_ids)[1:-1]))
            cursor.execute(area_sql.format(year=self.reporting_year))
            for result in cursor.fetchall():
                region_id = result[0]
                tenure_name = result[1]
                report_area = result[2] or 0

                if region_id not in area_data:
                    area_data[region_id] = {}
                area_data[region_id][tenure_name] = area_data[region_id].get(tenure_name, 0) + report_area
        logger.info("Region by Tenure: area complete")
        
        tenure_count_total_forest={}
        tenure_area_total_forest = {}
        for region in get_sorted_regions(True):
            region_count_data = count_data.get(region.id,{})
            region_area_data = area_data.get(region.id,{})
            region_data = {}
            rpt_map.append((region.name,region_data))
            region_count_total = 0
            region_area_total = 0
            for tenure_name in tenure_names:
                region_data[tenure_name]=dict(count = region_count_data.get(tenure_name,0),area=region_area_data.get(tenure_name,0))
                region_count_total += region_count_data.get(tenure_name,0)
                region_area_total += region_area_data.get(tenure_name,0)

                tenure_count_total_forest[tenure_name] = tenure_count_total_forest.get(tenure_name,0) + region_count_data.get(tenure_name,0)
                tenure_area_total_forest[tenure_name] = tenure_area_total_forest.get(tenure_name,0) + region_area_data.get(tenure_name,0)
                tenure_count_total_forest["Total"] = tenure_count_total_forest.get("Total",0) + region_count_data.get(tenure_name,0)
                tenure_area_total_forest["Total"] = tenure_area_total_forest.get("Total",0) + region_area_data.get(tenure_name,0)

            region_data["Total"] = dict(count=region_count_total,area=region_area_total)
        total_data = {}
        rpt_map.append(("Sub Total (Forest)",total_data))
        for tenure_name in tenure_names + ["Total"]:
            total_data[tenure_name]=dict(count = tenure_count_total_forest.get(tenure_name,0),area=tenure_area_total_forest.get(tenure_name,0))

        tenure_count_total_nonforest={}
        tenure_area_total_nonforest = {}
        for region in get_sorted_regions(False):
            region_count_data = count_data.get(region.id,{})
            region_area_data = area_data.get(region.id,{})
            region_data = {}
            rpt_map.append((region.name,region_data))
            region_count_total = 0
            region_area_total = 0
            for tenure_name in tenure_names:
                region_data[tenure_name]=dict(count = region_count_data.get(tenure_name,0),area=region_area_data.get(tenure_name,0))
                region_count_total += region_count_data.get(tenure_name,0)
                region_area_total += region_area_data.get(tenure_name,0)

                tenure_count_total_nonforest[tenure_name] = tenure_count_total_nonforest.get(tenure_name,0) + region_count_data.get(tenure_name,0)
                tenure_area_total_nonforest[tenure_name] = tenure_area_total_nonforest.get(tenure_name,0) + region_area_data.get(tenure_name,0)
                tenure_count_total_nonforest["Total"] = tenure_count_total_nonforest.get("Total",0) + region_count_data.get(tenure_name,0)
                tenure_area_total_nonforest["Total"] = tenure_area_total_nonforest.get("Total",0) + region_area_data.get(tenure_name,0)

            region_data["Total"] = dict(count=region_count_total,area=region_area_total)
        total_data = {}
        rpt_map.append(("Sub Total (Non Forest)",total_data))
        for tenure_name in tenure_names + ["Total"]:
            total_data[tenure_name]=dict(count = tenure_count_total_nonforest.get(tenure_name,0),area=tenure_area_total_nonforest.get(tenure_name,0))

        total_data = {}
        rpt_map.append(("Grand Total (All Regions)",total_data))
        for tenure_name in tenure_names + ["Total"]:
            total_data[tenure_name]=dict(
                count = tenure_count_total_nonforest.get(tenure_name,0) + tenure_count_total_forest.get(tenure_name,0),
                area = tenure_area_total_nonforest.get(tenure_name,0) + tenure_area_total_forest.get(tenure_name,0)
            )

        return rpt_map, tenure_names

    def get_excel_sheet(self, rpt_date, book=Workbook()):
        # book = Workbook()
        sheet1 = book.add_sheet('Bushfire Region By Tenure')
        sheet1 = book.get_sheet('Bushfire Region By Tenure')

        # font BOLD
        style = XFStyle() 
        font = Font()
        font.bold = True
        style.font = font

        # font BOLD and Center Aligned
        style_center = XFStyle()
        font = Font()
        font.bold = True
        style_center.font = font
        style_center.alignment.horz = Alignment.HORZ_CENTER

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style)
        hdr.write(1, 'Bushfire Region By Tenure Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 0, 1, "Bushfire Region By Tenure", style_center)
        hdr = sheet1.row(row_no())

        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)
        row.write(col_no(), '')
        row.write(col_no(), '' )
        for name in self.tenure_names:
            row.write(col_no(), name, style=style)
        row.write(col_no(), "Total", style=style)

        for region, region_data in self.rpt_map:
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), region, style=style_bold_gen)
            row.write(col_no(), 'Area', style=style_bold_gen)
            for tenure_name in self.tenure_names: # loops through all tenures for given region
                row.write(col_no(), round(region_data.get(tenure_name,{}).get('area',0),2), style=style_bold_area if "total" in region.lower() else style_normal_area )

            row.write(col_no(), round(region_data.get("Total",{}).get('area',0),2), style=style_bold_area )
            
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), '' )
            row.write(col_no(), 'Number', style=style_bold_gen)
            for tenure_name in self.tenure_names: # loops through all tenures for given region
                row.write(col_no(), region_data.get(tenure_name,{}).get('count',0), style=style_bold_int if "total" in region.lower() else style_normal_int )

            row.write(col_no(), region_data.get("Total",{}).get('count',0), style=style_bold_int )

            row = sheet1.row(row_no())

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)
        

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_regionbytenure_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """
        rpt_date = datetime.now()
        filename = 'bushfire_regionbytenure_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        for data in self.rpt_map:
            print ', '.join([str(i['count']) for i in data])
            print ', '.join([str(i['area']) for i in data])
            print


class Bushfire10YrAverageReport():
    def __init__(self,reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.rpt_map, self.item_map = self.create()
        logger.info("Starting Bushfire10YrAverageReport")

    def create(self):
        rpt_map = []
        item_map = {}

        count_sql = """
        SELECT a.cause_id, COUNT(*)
        FROM (
            (SELECT COALESCE(a1.cause_id, 9) AS cause_id, a1.id
            FROM reporting_bushfire a1
            WHERE a1.report_status IN {report_statuses} AND a1.reporting_year = {{reporting_year}} AND a1.fire_not_found = false
            )
            UNION
            (SELECT COALESCE(b1.cause_id, 9) AS cause_id, b1.id
            FROM reporting_bushfire b1
               JOIN reporting_bushfire b2 ON b1.valid_bushfire_id = b2.id AND b2.report_status IN {report_statuses} AND b2.reporting_year = {{reporting_year}} AND b2.fire_not_found = false
            WHERE b1.report_status = {status_merged}
            )
         ) AS a
        GROUP BY a.cause_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED, Bushfire.STATUS_REVIEWED]])),
            status_merged = Bushfire.STATUS_MERGED
        )

        area_sql = """
        SELECT COALESCE(a.cause_id, 9) AS cause_id, SUM(b.area) AS total_all_regions_area, SUM(a.area) AS total_area
        FROM reporting_bushfire a JOIN reporting_areaburnt b ON a.id = b.bushfire_id JOIN bfrs_tenure c ON b.tenure_id = c.id
        WHERE a.report_status IN {report_statuses} AND a.reporting_year = {{reporting_year}} AND a.fire_not_found = false AND c.report_group = 'ALL REGIONS'
        GROUP BY a.cause_id
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]]))
        )

        year_count_list = []
        year_total_count_list = []

        total_count = 0
        total_count_avg = 0
        
        all_causes =  Cause.objects.all().order_by('report_order')

        with connection.cursor() as cursor:
            for year in range(self.reporting_year,self.reporting_year - 10,-1):
                year_count_data = {}
                year_count_list.append(year_count_data)
                year_total_count = 0
                if year >= 2017:
                    cursor.execute(count_sql.format(reporting_year=year))
                    for result in cursor.fetchall():
                        year_count_data[result[0]] = result[1] or 0
                        year_total_count += result[1] or 0
                else:
                    data = read_col(year,'count')[0]
                    for cause in all_causes:
                        row = [d for d in data if d.get('cause_id')==cause.id]
                        if len(row) > 0:
                            year_count_data[cause.id] = row[0].get('count') or 0
                            year_total_count += (row[0].get('count') or 0)
                        else:
                            year_count_data[cause.id] = 0
                year_total_count_list.append(year_total_count)
                total_count += year_total_count

        total_count_avg = round(total_count/(len(year_count_list) * 1.0))
        
        for cause in all_causes:
            if rpt_map and cause.report_name in rpt_map[-1]:
                for i in range(0,len(year_count_list),1):
                    rpt_map[-1][cause.report_name]["count{}".format(i)] = rpt_map[-1][cause.report_name]["count{}".format(i)] + year_count_list[i].get(cause.id,0)
                    if year_total_count_list[i] == 0:
                        rpt_map[-1][cause.report_name]["perc{}".format(i)] = 0
                    else:
                        rpt_map[-1][cause.report_name]["perc{}".format(i)] = rpt_map[-1][cause.report_name]["count{}".format(i)] * 100 / (year_total_count_list[i] * 1.0)
                    rpt_map[-1][cause.report_name]["total_count"] += year_count_list[i].get(cause.id,0)

            else:
                report_data = {"total_count":0}
                for i in range(0,len(year_count_list),1):
                    report_data["count{}".format(i)] = year_count_list[i].get(cause.id,0)
                    if year_total_count_list[i] == 0:
                        report_data["perc{}".format(i)] = 0
                    else:
                        report_data["perc{}".format(i)] = year_count_list[i].get(cause.id,0) * 100 / (year_total_count_list[i] * 1.0)
                    report_data["total_count"] += year_count_list[i].get(cause.id,0)
                rpt_map.append(
                    {cause.report_name: report_data}
                )

        for m in rpt_map:
            for data in m.values():
                data["count_avg"] = round(data["total_count"] / (len(year_count_list) * 1.0))
                if total_count_avg == 0:
                    data["perc_avg"] = 0
                else:
                    data["perc_avg"] = data["count_avg"] * 100 / (total_count_avg * 1.0)

                

        report_total_data = {"count_avg":total_count_avg,"perc_avg":total_count * 100 / (total_count * 1.0)}

        for i in range(0,len(year_total_count_list),1):
            report_total_data["count{}".format(i)] = year_total_count_list[i]
            if year_total_count_list[i] == 0:
               report_total_data["perc{}".format(i)] = 0
            else:
               report_total_data["perc{}".format(i)] = year_total_count_list[i] * 100 / (year_total_count_list[i] * 1.0)

        rpt_map.append(
            {'Total': report_total_data}
        )
        logger.info("Bushfire10YrAverageReport create complete")
        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):
        year0 = str(self.reporting_year) + '/' + str(self.reporting_year+1)
        year1 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year2 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        year3 = str(self.reporting_year-3) + '/' + str(self.reporting_year-2)
        year4 = str(self.reporting_year-4) + '/' + str(self.reporting_year-3)
        year5 = str(self.reporting_year-5) + '/' + str(self.reporting_year-4)
        year6 = str(self.reporting_year-6) + '/' + str(self.reporting_year-5)
        year7 = str(self.reporting_year-7) + '/' + str(self.reporting_year-6)
        year8 = str(self.reporting_year-8) + '/' + str(self.reporting_year-7)
        year9 = str(self.reporting_year-9) + '/' + str(self.reporting_year-8)

        # book = Workbook()
        sheet1 = book.add_sheet('Bushfire Causes 10Yr Average')
        sheet1 = book.get_sheet('Bushfire Causes 10Yr Average')

        # font BOLD
        style = XFStyle() 
        font = Font()
        font.bold = True
        style.font = font

        # font BOLD and Center Aligned
        style_center = XFStyle()
        font = Font()
        font.bold = True
        style_center.font = font
        style_center.alignment.horz = Alignment.HORZ_CENTER


        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style)
        hdr.write(1, 'Bushfire Causes 10Yr Average')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 1, 10, "Number", style_center)
        sheet1.write_merge(row, row, 11, 20, "Percent %", style_center)
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "ALL REGIONS", style=style)
        hdr.write(col_no(), year9, style=style)
        hdr.write(col_no(), year8, style=style)
        hdr.write(col_no(), year7, style=style)
        hdr.write(col_no(), year6, style=style)
        hdr.write(col_no(), year5, style=style)
        hdr.write(col_no(), year4, style=style)
        hdr.write(col_no(), year3, style=style)
        hdr.write(col_no(), year2, style=style)
        hdr.write(col_no(), year1, style=style)
        hdr.write(col_no(), year0, style=style)

        hdr.write(col_no(), year9, style=style)
        hdr.write(col_no(), year8, style=style)
        hdr.write(col_no(), year7, style=style)
        hdr.write(col_no(), year6, style=style)
        hdr.write(col_no(), year5, style=style)
        hdr.write(col_no(), year4, style=style)
        hdr.write(col_no(), year3, style=style)
        hdr.write(col_no(), year2, style=style)
        hdr.write(col_no(), year1, style=style)
        hdr.write(col_no(), year0, style=style)

        for row in self.rpt_map:
            for cause, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if cause == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in cause.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), cause, style=style)
                    row.write(col_no(), data['count9'], style=style_bold_gen)
                    row.write(col_no(), data['count8'], style=style_bold_gen)
                    row.write(col_no(), data['count7'], style=style_bold_gen)
                    row.write(col_no(), data['count6'], style=style_bold_gen)
                    row.write(col_no(), data['count5'], style=style_bold_gen)
                    row.write(col_no(), data['count4'], style=style_bold_gen)
                    row.write(col_no(), data['count3'], style=style_bold_gen)
                    row.write(col_no(), data['count2'], style=style_bold_gen)
                    row.write(col_no(), data['count1'], style=style_bold_gen)
                    row.write(col_no(), data['count0'], style=style_bold_gen)
                    row.write(col_no(), data['perc9'], style=style_bold_percentage)
                    row.write(col_no(), data['perc8'], style=style_bold_percentage)
                    row.write(col_no(), data['perc7'], style=style_bold_percentage)
                    row.write(col_no(), data['perc6'], style=style_bold_percentage)
                    row.write(col_no(), data['perc5'], style=style_bold_percentage)
                    row.write(col_no(), data['perc4'], style=style_bold_percentage)
                    row.write(col_no(), data['perc3'], style=style_bold_percentage)
                    row.write(col_no(), data['perc2'], style=style_bold_percentage)
                    row.write(col_no(), data['perc1'], style=style_bold_percentage)
                    row.write(col_no(), data['perc0'], style=style_bold_percentage)

                else:
                    row.write(col_no(), cause )
                    row.write(col_no(), data['count9'], style=style_normal)
                    row.write(col_no(), data['count8'], style=style_normal)
                    row.write(col_no(), data['count7'], style=style_normal)
                    row.write(col_no(), data['count6'], style=style_normal)
                    row.write(col_no(), data['count5'], style=style_normal)
                    row.write(col_no(), data['count4'], style=style_normal)
                    row.write(col_no(), data['count3'], style=style_normal)
                    row.write(col_no(), data['count2'], style=style_normal)
                    row.write(col_no(), data['count1'], style=style_normal)
                    row.write(col_no(), data['count0'], style=style_normal)
                    row.write(col_no(), data['perc9'], style=style_normal_percentage)
                    row.write(col_no(), data['perc8'], style=style_normal_percentage)
                    row.write(col_no(), data['perc7'], style=style_normal_percentage)
                    row.write(col_no(), data['perc6'], style=style_normal_percentage)
                    row.write(col_no(), data['perc5'], style=style_normal_percentage)
                    row.write(col_no(), data['perc4'], style=style_normal_percentage)
                    row.write(col_no(), data['perc3'], style=style_normal_percentage)
                    row.write(col_no(), data['perc2'], style=style_normal_percentage)
                    row.write(col_no(), data['perc1'], style=style_normal_percentage)
                    row.write(col_no(), data['perc0'], style=style_normal_percentage)

        if MISSING_MAP:
            col_no = lambda c=count(): next(c)
            hdr = sheet1.row(row_no())
            hdr = sheet1.row(row_no())
            row = row_no()
            sheet1.write_merge(row, row, 0, 2, "NOTE: Errors in report", style_bold_red)
            for item in MISSING_MAP:
                hdr = sheet1.row(row_no())
                hdr.write(col_no(), item.get('name'), style=style_bold_yellow)
                hdr.write(col_no(), item.get('error'), style=style_bold_yellow)

        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 0, 2, "Ten Year Average", style_center)
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "ALL REGIONS", style=style)
        hdr.write(col_no(), "Number", style=style)
        hdr.write(col_no(), "Percent (%)", style=style)

        for row in self.rpt_map:
            for cause, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if cause == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in cause.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), cause, style=style_bold_gen)
                    row.write(col_no(), data['count_avg'], style=style_bold_gen)
                    row.write(col_no(), data['perc_avg'], style=style_bold_percentage)
                else:
                    row.write(col_no(), cause, style=style_normal)
                    row.write(col_no(), data['count_avg'], style=style_normal)
                    row.write(col_no(), data['perc_avg'], style=style_normal_percentage)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)


    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_cause_10yr_average_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'bushfire_by_cause_10yr_average_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        year0 = str(self.reporting_year-1) + '/' + str(self.reporting_year)
        year1 = str(self.reporting_year-2) + '/' + str(self.reporting_year-1)
        year2 = str(self.reporting_year-3) + '/' + str(self.reporting_year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Cause', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for cause, data in row.iteritems():
                if cause and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(cause, data['count2'], data['count1'], data['count0'], data['perc2'], data['perc1'], data['perc0']).expandtabs(25)
                else:
                    print


class BushfireIndicator():
    def __init__(self,reporting_year=None):
        self.reporting_year = current_finyear() if (reporting_year is None or reporting_year >= current_finyear()) else reporting_year
        self.rpt_map, self.item_map = self.create()
        logger.info("Starting BushfireIndicator")

    def create(self):
        # Group By Region
        #qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, reporting_year=self.reporting_year, region__in=Region.objects.filter(forest_region=False), first_attack__name='DBCA P&W')
        #qs = Bushfire.objects.filter(authorised_by__isnull=False, reporting_year=self.reporting_year, region__in=Region.objects.filter(forest_region=False), first_attack__name='DBCA P&W').exclude(report_status=Bushfire.STATUS_INVALIDATED)
        """
        qs = Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED], reporting_year=self.reporting_year,fire_not_found=False, region__in=get_sorted_regions(True), first_attack=Agency.DBCA)
        qs1 = qs.aggregate(count=Count('id'), area=Sum('area') ) 
        qs2 = qs.filter(area__lt=2.0).aggregate(count=Count('id'), area=Sum('area') ) 
        count1 = qs1.get('count') if qs1.get('count') else 0
        count2 = qs2.get('count') if qs2.get('count') else 0
        """


        count_sql = """
        select count(*)
        from (
            (select a1.id,a1.area
            from reporting_bushfire a1
            where a1.report_status in {report_statuses} and a1.reporting_year={reporting_year} and a1.fire_not_found=false and a1.region_id in ({regions}) and a1.first_attack_id = {first_attack_agency}
            )
            union
            (select b1.id,b2.area
            from reporting_bushfire b1
               join reporting_bushfire b2 on b1.valid_bushfire_id = b2.id and b2.report_status in {report_statuses} and b2.reporting_year={reporting_year} and b2.region_id in ({regions}) and b2.fire_not_found=false and b2.first_attack_id = {first_attack_agency}
            where b1.report_status = {status_merged} 
            )
         ) as a
         {{filter}}
        """.format(
            report_statuses="({})".format(",".join([str(i) for i in [Bushfire.STATUS_FINAL_AUTHORISED,Bushfire.STATUS_REVIEWED]])),
            status_merged = Bushfire.STATUS_MERGED,
            regions = ",".join([str(r.id) for r in get_sorted_regions(True)]),
            reporting_year = self.reporting_year,
            first_attack_agency = Agency.DBCA.id
        )

        count1 = 0
        count2 = 0
        with connection.cursor() as cursor:
            cursor.execute(count_sql.format(filter=""))
            result = cursor.fetchone()
            count1 = result[0] or 0

            cursor.execute(count_sql.format(filter=" where a.area < 2.0"))
            result = cursor.fetchone()
            count2 = result[0] or 0

        rpt_map = []
        item_map = {}
        rpt_map.append({'No of bushfires in the Forest Regions where DBCA was the initial attack agency': dict(count=count1)})
        rpt_map.append({'No of bushfires in the Forest Regions <2ha, where DBCA was the initial attack agency': dict(count=count2)})
        if count1 == 0:
            rpt_map.append({'Percentage': dict(count=0)})
        else:
            rpt_map.append({'Percentage': dict(count=round(count2*100./count1, 2))})
        logger.info("BushfireIndicator create complete")
        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        # book = Workbook()
        sheet1 = book.add_sheet('Bushfire Indicator')
        sheet1 = book.get_sheet('Bushfire Indicator')

        # font BOLD
        style = XFStyle() 
        font = Font()
        font.bold = True
        style.font = font

        # font BOLD and Center Aligned
        style_center = XFStyle()
        font = Font()
        font.bold = True
        style_center.font = font
        style_center.alignment.horz = Alignment.HORZ_CENTER


        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style)
        hdr.write(1, 'Bushfire Indicator Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style)
        hdr.write(1, self.reporting_year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, reporting_year=self.reporting_year).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 0, 1, "Bushfire Indicator", style_center)
        hdr = sheet1.row(row_no())

        for row in self.rpt_map:
            for key, data in row.iteritems():

                sheet_row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if key == '':
                    #sheet_row = sheet1.row(row_no())
                    continue
                elif 'total' in key.lower():
                    #sheet_row = sheet1.row(row_no())
                    sheet_row.write(col_no(), key, style=style_bold_gen)
                    sheet_row.write(col_no(), data['count'], style=style_bold_gen)
                elif 'percentage' in key.lower():
                    #sheet_row = sheet1.row(row_no())
                    sheet_row.write(col_no(), key, style=style_bold_gen)
                    sheet_row.write(col_no(), data['count'], style=style_bold_percentage)
                else:
                    sheet_row.write(col_no(), key, style=style_normal)
                    sheet_row.write(col_no(), data['count'], style=style_normal)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

    def write_excel(self):
        rpt_date = datetime.now()
        book = Workbook()
        self.get_excel_sheet(rpt_date, book)
        filename = '/tmp/bushfire_indicator_report_{}.xls'.format(rpt_date.strftime('%d-%b-%Y'))
        book.save(filename)

    def export(self):
        """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

        rpt_date = datetime.now()
        filename = 'bushfire_indicator_report_{}.xls'.format(rpt_date.strftime('%d%b%Y'))
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = 'attachment; filename=' + filename

        book = Workbook()
        self.get_excel_sheet(rpt_date, book)

        book.add_sheet('Sheet 2')
        book.save(response)

        return response

    def display(self):
        print '{}\t{}'.format('', 'Number').expandtabs(20)
        for row in self.rpt_map:
            for key, data in row.iteritems():
                if key and data:
                    print '{}\t{}'.format(key, data['count']).expandtabs(25)
                else:
                    print


def export_outstanding_fires(request, region_id, queryset):
    """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """
    #regions = Region.objects.filter(id=region_id) if region_id else Region.objects.all()
    regions = Region.objects.filter(id=region_id) if region_id else Region.objects.filter(dbca=True)
    region_name = regions[0].name if region_id else 'All-Regions'

    rpt_date = datetime.now()
    filename = 'outstanding_fires_{}_{}.xls'.format(region_name, rpt_date.strftime('%d%b%Y'))
    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = 'attachment; filename=' + filename

    book = Workbook()
    for region in regions:
        outstanding_fires(book, region, queryset, rpt_date)

    book.add_sheet('Sheet 2')
    book.save(response)

    return response

def email_outstanding_fires(region_id=None):
    """ Executed from the command line, returns an Excel WB attachment via email """
    qs = Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED])
    rpt_date = datetime.now()

    for row in settings.OUTSTANDING_FIRES_EMAIL:
        for region_name,email_to in row.iteritems():

            try:
                region = Region.objects.get(name=region_name)
            except:
                region = None
                traceback.print_exc()

            if region:
                f = StringIO()
                book = Workbook()
                total_reports = outstanding_fires(book, region, qs, rpt_date)
                book.add_sheet('Sheet 2')
                book.save(f)

                if total_reports == 0:
                    subject = 'Outstanding Fires Report - {} - {} - No Outstanding Fire'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 
                    body = 'Outstanding Fires Report - {} - {} - No Outstanding Fire'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 
                elif total_reports == 1:
                    subject = 'Outstanding Fires Report - {} - {} - 1 Outstanding Fire'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 
                    body = 'Outstanding Fires Report - {} - {} - 1 Outstanding Fire'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 
                else:
                    subject = 'Outstanding Fires Report - {} - {} - {} Outstanding Fires'.format(region_name, rpt_date.strftime('%d-%b-%Y'),total_reports) 
                    body = 'Outstanding Fires Report - {} - {} - {} Outstanding Fires'.format(region_name, rpt_date.strftime('%d-%b-%Y'),total_reports) 

                message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=email_to, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
                if total_reports > 0:
                    filename = 'outstanding_fires_{}_{}.xls'.format(region_name.replace(' ', '').lower(), rpt_date.strftime('%d-%b-%Y'))
                    message.attach(filename, f.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") #get the stream and set the correct mimetype

                message.send()

def outstanding_fires(book, region, queryset, rpt_date):
    qs = queryset.filter(region_id=region.id)
    sheet1 = book.add_sheet(region.name)

    col_no = lambda c=count(): next(c)
    row_no = lambda c=count(): next(c)
    sheet1 = book.get_sheet(region.name)

    hdr = sheet1.row(row_no())
    hdr.write(0, 'Report Date')
    hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

    hdr = sheet1.row(row_no())
    hdr.write(0, 'Region')
    hdr.write(1, region.name)

    hdr = sheet1.row(row_no())
    hdr = sheet1.row(row_no())
    hdr.write(col_no(), "Fire Number")
    hdr.write(col_no(), "Name")
    hdr.write(col_no(), "Date Detected")
    hdr.write(col_no(), "Duty Officer")
    hdr.write(col_no(), "Date Contained")
    hdr.write(col_no(), "Date Controlled")
    hdr.write(col_no(), "Date Inactive")

    #row_no = lambda c=count(5): next(c)
    total_reports = 0
    for obj in qs:
        total_reports += 1
        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)

        row.write(col_no(), obj.fire_number )
        row.write(col_no(), obj.name)
        row.write(col_no(), obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else '' )
        row.write(col_no(), obj.duty_officer.get_full_name() if obj.duty_officer else '' )
        row.write(col_no(), obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else '' )
        row.write(col_no(), obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else '' )
        row.write(col_no(), obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else '' )

    return total_reports

export_outstanding_fires.short_description = u"Outstanding Fires"

def calculate_report_tables(request):
    print "starting calculate report tables"
    url = request.META.get('HTTP_REFERER')
    with connection.cursor() as csr:
        csr.execute("""
--------------------------------------------------------------------
--reporting_bushfire and reporting_areaburnt CREATION AND INDEXES
---------------------------------------------------------------------
DROP TABLE IF EXISTS reporting_bushfire;
CREATE TABLE reporting_bushfire AS SELECT * FROM bfrs_bushfire;

--CREATE INDEX idx_reporting_bushfire_origin ON reporting_bushfire USING GIST(origin_point);
DROP INDEX IF EXISTS idx_reporting_bushfire_tenure;
CREATE INDEX idx_reporting_bushfire_tenure ON reporting_bushfire (tenure_id);
DROP INDEX IF EXISTS idx_reporting_bushfire_region;
CREATE INDEX idx_reporting_bushfire_region ON reporting_bushfire (region_id);
DROP INDEX IF EXISTS idx_reporting_bushfire_rpt_status;
CREATE INDEX idx_reporting_bushfire_rpt_status ON reporting_bushfire (report_status);
DROP INDEX IF EXISTS idx_reporting_bushfire_rpt_year;
CREATE INDEX idx_reporting_bushfire_rpt_year ON reporting_bushfire (reporting_year);

DROP TABLE IF EXISTS reporting_areaburnt;
CREATE TABLE reporting_areaburnt AS SELECT * FROM bfrs_areaburnt;
ALTER TABLE reporting_areaburnt DROP CONSTRAINT IF EXISTS reporting_areaburnt_bushfire_id_tenure_id_key;
ALTER TABLE reporting_areaburnt ADD COLUMN region_id Integer;
ALTER TABLE reporting_areaburnt ADD COLUMN has_fire_boundary Boolean;
CREATE INDEX idx_reporting_areaburnt_tenure ON reporting_areaburnt(tenure_id);
CREATE INDEX idx_reporting_areaburnt_bushfire ON reporting_areaburnt(bushfire_id);
CREATE INDEX idx_reporting_areaburnt_region ON reporting_areaburnt(region_id);
DELETE FROM reporting_areaburnt WHERE bushfire_id IN
    (SELECT id FROM reporting_bushfire WHERE fire_boundary IS NOT NULL);
UPDATE reporting_areaburnt ab SET region_id = (SELECT bf.region_id FROM reporting_bushfire bf WHERE ab.bushfire_id = bf.id);
UPDATE reporting_areaburnt SET has_fire_boundary = False;

--make valid geometries (NB checked cadastre_for_bfrs and no invalid geometries
UPDATE reporting_bushfire SET fire_boundary = ST_CollectionExtract(ST_MakeValid(fire_boundary), 3) WHERE NOT ST_IsValid(fire_boundary);
UPDATE reporting_state_forest SET shape = ST_CollectionExtract(ST_MakeValid(shape), 3) WHERE NOT ST_IsValid(shape);
UPDATE reporting_cadastre SET shape = ST_CollectionExtract(ST_MakeValid(shape), 3) WHERE NOT ST_IsValid(shape);
UPDATE reporting_dept_managed SET geometry = ST_CollectionExtract(ST_MakeValid(geometry), 3) WHERE NOT ST_IsValid(geometry);
UPDATE reporting_dept_interest SET geometry = ST_CollectionExtract(ST_MakeValid(geometry), 3) WHERE NOT ST_IsValid(geometry);

----------------------------------------
--GET REGION-CROSSING FIRES
----------------------------------------
DROP TABLE IF EXISTS reporting_crossregion_fires;
CREATE TABLE reporting_crossregion_fires AS SELECT DISTINCT bf.id FROM reporting_bushfire bf JOIN bfrs_region r ON ST_Overlaps(bf.fire_boundary, r.geometry);
DROP INDEX IF EXISTS idx_reporting_crossregion_fires;
CREATE INDEX idx_reporting_crossregion_fires ON reporting_crossregion_fires(id);

---------------------------------------    
--UCL/Other Crown/Private Property 13 min
---------------------------------------

--insert recalculated 'other crown' / UCL / Freehold 
--Other Crown 5min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 19, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'Other Crown Land' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
    
--UCL 5min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 25, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'UCL' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);
    
--Freehold 15s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, cad.shape), 900914))/10000)::numeric,2), bf.id, 18, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape)
    WHERE brc_fms_legend = 'Freehold' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);

--UPDATE tenure_id FOR IGNITION POINTS IN UCL, FREEHOLD AND OTHER CROWN
UPDATE reporting_bushfire bf SET tenure_id = 19 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'Other Crown Land');

UPDATE reporting_bushfire bf SET tenure_id = 18 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'Freehold');

UPDATE reporting_bushfire bf SET tenure_id = 25 WHERE bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_cadastre cad WHERE ST_Within(bf.origin_point, cad.shape) AND cad.brc_fms_legend = 'UCL');


-------------------------------------------
--DEPT LAND
---------------------------------------------
--INTEREST 20s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, di.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_dept_interest di ON ST_Intersects(bf.fire_boundary, di.geometry) JOIN bfrs_tenure t ON di.category = t.name
    WHERE bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);

--MANAGED 3min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, dm.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_dept_managed dm ON ST_Intersects(bf.fire_boundary, dm.geometry) JOIN bfrs_tenure t ON dm.category = t.name
    WHERE dm.category <> 'State Forest' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);

--UPDATE tenure_id FOR OLD 'Other' TENURE IN DEPT-MANAGED LAND
UPDATE reporting_bushfire
SET tenure_id = t_id
FROM (SELECT bf.id AS bf_id, t.id AS t_id FROM reporting_bushfire bf, reporting_dept_managed dm 
JOIN bfrs_tenure t ON dm.category = t.name
WHERE tenure_id = 20
AND st_within(bf.origin_point, dm.geometry)) AS sqry
WHERE id = bf_id;

--------------------------------------------------
--STATE FOREST 20s
--------------------------------------------------
--Hardwood 4s
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, sf.shape), 900914))/10000)::numeric,2), bf.id, 26, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape)
    WHERE fbr_fire_report_classification = 'Native Hardwood' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);

--Softwood 1s    
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, sf.shape), 900914))/10000)::numeric,2), bf.id, 27, bf.region_id, True
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape)
    WHERE fbr_fire_report_classification = 'State - Coniferous' AND bf.report_status IN (3, 4) AND NOT bf.fire_not_found AND bf.id NOT IN (SELECT id FROM reporting_crossregion_fires);

--where NOT has_fire_boundary
UPDATE reporting_areaburnt
SET tenure_id = 27 WHERE id IN
(SELECT ab.id
FROM reporting_areaburnt ab JOIN reporting_bushfire bf ON ab.bushfire_id = bf.id 
JOIN reporting_state_forest sf ON ST_Within(bf.origin_point, sf.shape)
WHERE ab.tenure_id = 3 AND NOT has_fire_boundary AND sf.fbr_fire_report_classification = 'State - Coniferous');

--remaining '3's should be 26
UPDATE reporting_areaburnt
SET tenure_id = 26 WHERE id IN
(SELECT ab.id
FROM reporting_areaburnt ab JOIN reporting_bushfire bf ON ab.bushfire_id = bf.id 
JOIN reporting_state_forest sf ON ST_Within(bf.origin_point, sf.shape)
WHERE ab.tenure_id = 3 AND NOT has_fire_boundary AND sf.fbr_fire_report_classification = 'Native Hardwood');

DELETE FROM reporting_areaburnt WHERE tenure_id = 3;

--UPDATE STATE FOREST IGNITION POINTS
UPDATE reporting_bushfire bf SET tenure_id = 26 WHERE bf.tenure_id = 3 AND bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_state_forest sf WHERE ST_Within(bf.origin_point, sf.shape) AND sf.fbr_fire_report_classification = 'Native Hardwood');

UPDATE reporting_bushfire bf SET tenure_id = 27 WHERE bf.tenure_id = 3 AND bf.id IN 
(SELECT id FROM reporting_bushfire bf, reporting_state_forest sf WHERE ST_Within(bf.origin_point, sf.shape) AND sf.fbr_fire_report_classification = 'State - Coniferous');

---------------------------------------
--ADD IN INFO FOR REGION-CROSSING FIRES 20min in total
---------------------------------------
--SA/NT: insert into reporting_areaburnt the SA/NT components of trans-state fires (this is done USING r.name = t.name) 1 min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(bf.fire_boundary, r.geometry), 900914))/10000)::numeric,2),
bf.id, t.id, r.id, True
FROM reporting_bushfire bf JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON r.name = t.name;
    
--insert into reporting_areaburnt the Prvt Prpty / UCL / Other Crown Land components of trans-region fires (13 min)
--Other Crown Land
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 19, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'Other Crown Land' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) AND r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--UCL 3 min
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 25, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'UCL' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) AND r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--Private Property (Freehold)   30s OK
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 18, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, cad.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_cadastre cad ON ST_Intersects(bf.fire_boundary, cad.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE brc_fms_legend = 'Freehold' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--State Forest (Hardwood) (4s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 26, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, sf.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE fbr_fire_report_classification = 'Native Hardwood' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;

--State Forest (Softwood) (4s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id, has_fire_boundary)
SELECT area, bushfire_id, 27, region_id, True
FROM (
    SELECT SUM(ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, sf.shape), r.geometry), 900914))/10000)::numeric, 2)) AS area,
    bf.id as bushfire_id, r.id as region_id
    FROM reporting_bushfire bf JOIN reporting_state_forest sf ON ST_Intersects(bf.fire_boundary, sf.shape) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry)
    WHERE fbr_fire_report_classification = 'State - Coniferous' AND bf.id IN (SELECT id FROM reporting_crossregion_fires) and r.dbca
    GROUP BY bf.id, r.id) AS sqry;
    
--insert into reporting_areaburnt the Interest Tenure components of trans-region fires (8s)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, di.geometry), r.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, r.id
    FROM reporting_bushfire bf JOIN reporting_dept_interest di ON ST_Intersects(bf.fire_boundary, di.geometry) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON di.category = t.name
    WHERE bf.id IN (SELECT id FROM reporting_crossregion_fires);

--insert into reporting_areaburnt the Managed Tenure components of trans-region fires (1:19)
INSERT INTO reporting_areaburnt (area, bushfire_id, tenure_id, region_id)
    SELECT ROUND((ST_Area(ST_Transform(ST_Intersection(ST_Intersection(bf.fire_boundary, dm.geometry), r.geometry), 900914))/10000)::numeric,2),
    bf.id, t.id, r.id
    FROM reporting_bushfire bf JOIN reporting_dept_managed dm ON ST_Intersects(bf.fire_boundary, dm.geometry) JOIN bfrs_region r ON ST_Intersects(bf.fire_boundary, r.geometry) JOIN bfrs_tenure t ON dm.category = t.name
    WHERE dm.category <> 'State Forest'  AND bf.id IN (SELECT id FROM reporting_crossregion_fires);
    """)
    print "finished calculate report tables"
    return HttpResponseRedirect(url)
