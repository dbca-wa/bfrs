from django.db import connection
from bfrs.models import Bushfire, Region, District, Tenure, Cause, current_finyear
from bfrs.utils import get_pbs_bushfires
from django.db.models import Count, Sum
from django.db.models.query import QuerySet
from datetime import datetime
from xlwt import Workbook, Font, XFStyle, Alignment, Pattern, Style
from itertools import count
import unicodecsv

from django.http import HttpResponse
from django.core.mail import send_mail
from cStringIO import StringIO
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
import os
import subprocess
import csv

from django.template.loader import render_to_string

import logging
logger = logging.getLogger(__name__)

DISCLAIMER = 'Any discrepancies between the total and the sum of the individual values is due to rounding.'
MISSING_MAP = []


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
style_bold_int     = style(bold=True, horz_align=Alignment.HORZ_CENTER)
style_bold         = style(bold=True, num_fmt='#,##0', horz_align=Alignment.HORZ_CENTER)
style_bold_float   = style(bold=True, num_fmt='#,##0.00')
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
    def __init__(self):
        self.ministerial_auth = MinisterialReportAuth()
        self.ministerial_268 = MinisterialReport268()
        self.ministerial = MinisterialReport(self.ministerial_auth, self.ministerial_268)
        self.quarterly = QuarterlyReport()
        self.by_tenure = BushfireByTenureReport()
        self.by_cause = BushfireByCauseReport()
        self.region_by_tenure = RegionByTenureReport()
        self.indicator = BushfireIndicator()
        self.by_cause_10YrAverage = Bushfire10YrAverageReport()

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
    def __init__(self, ministerial_auth=None, ministerial_268=None):
        self.ministerial_auth = ministerial_auth if ministerial_auth else MinisterialReportAuth()
        self.ministerial_268 = ministerial_268 if ministerial_268 else MinisterialReport268()
        self.rpt_map, self.item_map = self.create()

    def create(self):
        rpt_map_auth = self.ministerial_auth.rpt_map
        rpt_map_268 = self.ministerial_268.rpt_map
        item_map_auth = self.ministerial_auth.item_map
        item_map_268 = self.ministerial_268.item_map

        rpt_map = []
        item_map = {}
        for region in Region.objects.filter(forest_region=True).order_by('id'):
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

        for region in Region.objects.filter(forest_region=False).order_by('id'):
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
            "DBCA Tenure",
            "Area DBCA Tenure",
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
        hdr.write(1, current_finyear())

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Tenure", style=style_bold_gen)
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
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_gen)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

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
        print '{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Tenure', 'Area DBCA Tenure', 'Total All Area', 'Total Area').expandtabs(20)
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
        #texname = template + ".tex"
        #filename = template + ".pdf"
        texname = template + "_" + request.user.username + ".tex"
        filename = template + "_" + request.user.username + ".pdf"
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
            'current_finyear': current_finyear(),
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

        directory = os.path.join(settings.MEDIA_ROOT, 'ministerial_report' + os.sep)
        if not os.path.exists(directory):
            logger.debug("Making a new directory: {}".format(directory))
            os.makedirs(directory)

        logger.debug('Starting  render_to_string step')
        err_msg = None
        try:
            output = render_to_string("latex/" + template + ".tex", context, request=request)
        except Exception as e:
            import traceback
            err_msg = u"PDF tex template render failed (might be missing attachments):"
            logger.debug(err_msg + "\n{}".format(e))

            error_response.write(err_msg + "\n\n{0}\n\n{1}".format(e,traceback.format_exc()))
            return error_response

        with open(directory + texname, "w") as f:
            f.write(output.encode('utf-8'))
            logger.debug("Writing to {}".format(directory + texname))

        logger.debug("Starting PDF rendering process ...")
        cmd = ['latexmk', '-cd', '-f', '-silent', '-pdf', directory + texname]
        #cmd = ['latexmk', '-cd', '-f', '-pdf', directory + texname]
        logger.debug("Running: {0}".format(" ".join(cmd)))
        subprocess.call(cmd)

        logger.debug("Cleaning up ...")
        cmd = ['latexmk', '-cd', '-c', directory + texname]
        logger.debug("Running: {0}".format(" ".join(cmd)))
        subprocess.call(cmd)

        logger.debug("Reading PDF output from {}".format(filename))
        response.write(open(directory + filename).read())
        logger.debug("Finally: returning PDF response.")
        return response




class MinisterialReport268():
    """
    Report for active 268b bushfires only
    """
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def get_268_data(self, dbca_initial_control=None):
        """ Retrieves the 268b fires from PBS and Aggregates the Area and Number count by region """
        qs_regions = Region.objects.all()

        if dbca_initial_control:
            # get the fires managed by DBCA
            outstanding_fires = list(Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED], initial_control__name__icontains='DBCA').values_list('fire_number', flat=True))
        else:
            outstanding_fires = list(Bushfire.objects.filter(report_status__in=[Bushfire.STATUS_INITIAL_AUTHORISED]).values_list('fire_number', flat=True))

        forest_regions = list(qs_regions.filter(forest_region=True).values_list('id', flat=True))
        pbs_fires_dict = get_pbs_bushfires(outstanding_fires)

        if not dbca_initial_control:
            self.pbs_fires_dict = pbs_fires_dict
            self.found_fires = [i['fire_id'] for i in self.pbs_fires_dict]
            self.missing_fires = list(set(outstanding_fires).difference(self.found_fires)) # fire_numbers not returned from PB

        rpt_map = {}
        for i in pbs_fires_dict:                                                                       
            region_id = i['region']

            exists = [i for r in qs_regions if r.id==region_id]
            if exists:
                if rpt_map.has_key(region_id):
                    area = rpt_map.get(region_id)['area'] + float(i['area'])
                    number = rpt_map.get(region_id)['number'] + 1
                            
                else:
                    area = float(i['area'])
                    number = 1

            else:
                area = 0.0
                number = 0

            rpt_map.update({region_id: dict(area=area, number=number)})

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

        for region in Region.objects.filter(forest_region=True).order_by('id'):
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

        for region in Region.objects.filter(forest_region=False).order_by('id'):
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
        hdr.write(1, current_finyear())

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Tenure", style=style_bold_gen)
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
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_gen)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Outstanding Fires (Contributing)", style=style_bold_gen)
        hdr.write(col_no(), "Area (ha)", style=style_bold_gen)
        for data in self.pbs_fires_dict:
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), data['fire_id'], style=style_normal)
            row.write(col_no(), float(data['area']), style=style_normal)

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
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        # Group By Region
        qs=Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).values('region_id')
        qs1=qs.filter(initial_control__name='DBCA P&W').annotate(dbca_count=Count('region_id'), dbca_sum=Sum('area') )
        qs2=qs.exclude(initial_control__isnull=True).annotate(total_count=Count('region_id'), total_sum=Sum('area') )

        rpt_map = []
        item_map = {}
        net_forest_pw_tenure      = 0
        net_forest_area_pw_tenure = 0
        net_forest_total_all_area = 0
        net_forest_total_area     = 0

        for region in Region.objects.filter(forest_region=True).order_by('id'):
            row1 = qs1.get(region_id=region.id) if qs1.filter(region_id=region.id).count() > 0 else {}
            row2 = qs2.get(region_id=region.id) if qs2.filter(region_id=region.id).count() > 0 else {}

            pw_tenure      = row1['dbca_count'] if row1.has_key('dbca_count') and row1['dbca_count'] else 0
            area_pw_tenure = round(row1['dbca_sum'], 2) if row1.has_key('dbca_sum') and row1['dbca_sum'] else 0
            total_all_area = row2['total_count'] if row2.has_key('total_count') and row2['total_count'] else 0
            total_area     = round(row2['total_sum'], 2) if row2.has_key('total_sum') and row2['total_sum'] else 0

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
        for region in Region.objects.filter(forest_region=False).order_by('id'):
            row1 = qs1.get(region_id=region.id) if qs1.filter(region_id=region.id).count() > 0 else {}
            row2 = qs2.get(region_id=region.id) if qs2.filter(region_id=region.id).count() > 0 else {}

            pw_tenure      = row1['dbca_count'] if row1.has_key('dbca_count') and row1['dbca_count'] else 0
            area_pw_tenure = round(row1['dbca_sum'], 2) if row1.has_key('dbca_sum') and row1['dbca_sum'] else 0
            total_all_area = row2['total_count'] if row2.has_key('total_count') and row2['total_count'] else 0
            total_area     = round(row2['total_sum'], 2) if row2.has_key('total_sum') and row2['total_sum'] else 0

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
                
        return rpt_map, item_map

    def export_final_csv(self, request, queryset):
        writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

        writer.writerow([
            "Region",
            "DBCA Tenure",
            "Area DBCA Tenure",
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
        hdr.write(1, current_finyear())

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Tenure", style=style_bold_gen)
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
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_gen)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal_int)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal_int)
                    row.write(col_no(), data['total_area'], style=style_normal)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

        #book.save("/tmp/foobar.xls")
        #return sheet1

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
        print '{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Tenure', 'Area DBCA Tenure', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                print '{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)

    def pdflatex(self, request, form_data):

        now = timezone.localtime(timezone.now())
        #report_date = now.strptime(request.GET.get('date'), '%Y-%m-%d').date()
        report_date = now

        #template = request.GET.get("template", "pfp")
        template = "ministerial_auth_report"
        response = HttpResponse(content_type='application/pdf')
        #texname = template + ".tex"
        #filename = template + ".pdf"
        texname = template + "_" + request.user.username + ".tex"
        filename = template + "_" + request.user.username + ".pdf"
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
            'current_finyear': current_finyear(),
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

        directory = os.path.join(settings.MEDIA_ROOT, 'ministerial_report' + os.sep)
        if not os.path.exists(directory):
            logger.debug("Making a new directory: {}".format(directory))
            os.makedirs(directory)

        logger.debug('Starting  render_to_string step')
        err_msg = None
        try:
            output = render_to_string("latex/" + template + ".tex", context, request=request)
        except Exception as e:
            import traceback
            err_msg = u"PDF tex template render failed (might be missing attachments):"
            logger.debug(err_msg + "\n{}".format(e))

            error_response.write(err_msg + "\n\n{0}\n\n{1}".format(e,traceback.format_exc()))
            return error_response

        with open(directory + texname, "w") as f:
            f.write(output.encode('utf-8'))
            logger.debug("Writing to {}".format(directory + texname))

        logger.debug("Starting PDF rendering process ...")
        cmd = ['latexmk', '-cd', '-f', '-silent', '-pdf', directory + texname]
        #cmd = ['latexmk', '-cd', '-f', '-pdf', directory + texname]
        logger.debug("Running: {0}".format(" ".join(cmd)))
        subprocess.call(cmd)

        logger.debug("Cleaning up ...")
        cmd = ['latexmk', '-cd', '-c', directory + texname]
        logger.debug("Running: {0}".format(" ".join(cmd)))
        subprocess.call(cmd)

        logger.debug("Reading PDF output from {}".format(filename))
        response.write(open(directory + filename).read())
        logger.debug("Finally: returning PDF response.")
        return response

def _ministerial_report():
    with connection.cursor() as cursor:
        cursor.execute("""
        with detail as 
        (
            select 
            r.name as region,
            count(case when a.name ilike 'dbca%' then 1 else null end) as PW_Tenure,
            sum(case when a.name ilike 'dbca%' then b.area else null end) as Area_PW_Tenure,
            count(b.id) as Total_All_Tenure,
            sum(b.area) as Total_Area
                
            FROM bfrs_bushfire b
            INNER JOIN bfrs_region r on r.id = b.region_id
            INNER JOIN bfrs_agency a on a.id = b.initial_control_id
            
            GROUP BY r.name
            ORDER BY r.name
        ), 
        total as 
        (
            SELECT
                cast('Total' as varchar),
                sum(PW_Tenure) as PW_Tenure,
                sum(Area_PW_Tenure) as Area_PW_Tenure,
                sum(Total_All_Tenure) as Total_All_Tenure,
                sum(Total_Area) as Total_Area
            FROM detail
        )
        select * from detail
        union all
        select * from total
        """)
        return cursor.fetchall()

#        results = list(cursor.fetchall())
#        return results

#        result_list = []
#        for row in cursor.fetchall():
#            print row
#            p = self.model(id=row[0], name=row[1], fire_number=row[2])
#            p.num_bushfires = row[3]
#            result_list.append(p)
#    return result_list

class QuarterlyReport():
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        """
        To Test:
            from bfrs.reports import QuarterlyReport
            q=QuarterlyReport()
            q.display()
        """
        rpt_map = []
        item_map = {}
        qs=Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).values('region_id')

        qs_forest_pw = qs.filter(region__in=Region.objects.filter(forest_region=True)).filter(initial_control__name='DBCA P&W').aggregate(count=Count('region_id'), area=Sum('area') )
        qs_forest_non_pw = qs.filter(region__in=Region.objects.filter(forest_region=True)).exclude(initial_control__name='DBCA P&W').aggregate(count=Count('region_id'), area=Sum('area') )
        forest_pw_tenure = qs_forest_pw.get('count') if qs_forest_pw.get('count') else 0.0
        forest_area_pw_tenure = qs_forest_pw.get('area') if qs_forest_pw.get('area') else 0.0
        forest_non_pw_tenure = qs_forest_non_pw.get('count') if qs_forest_non_pw.get('count') else 0.0
        forest_area_non_pw_tenure = qs_forest_non_pw.get('area') if qs_forest_non_pw.get('area') else 0.0
        forest_tenure_total = forest_pw_tenure + forest_non_pw_tenure 
        forest_area_total = forest_area_pw_tenure + forest_area_non_pw_tenure
        rpt_map.append(
            {'Forest Regions': dict(
                pw_tenure=forest_pw_tenure, area_pw_tenure=forest_area_pw_tenure, 
                non_pw_tenure=forest_non_pw_tenure, area_non_pw_tenure=forest_area_non_pw_tenure, 
                total_all_tenure=forest_tenure_total, total_area=forest_area_total
            )}
        )

        qs_nonforest_pw = qs.filter(region__in=Region.objects.filter(forest_region=False)).filter(initial_control__name='DBCA P&W').aggregate(count=Count('region_id'), area=Sum('area') )
        qs_nonforest_non_pw = qs.filter(region__in=Region.objects.filter(forest_region=False)).exclude(initial_control__name='DBCA P&W').aggregate(count=Count('region_id'), area=Sum('area') )
        nonforest_pw_tenure = qs_nonforest_pw.get('count') if qs_nonforest_pw.get('count') else 0.0
        nonforest_area_pw_tenure = qs_nonforest_pw.get('area') if qs_nonforest_pw.get('area') else 0.0
        nonforest_non_pw_tenure = qs_nonforest_non_pw.get('count') if qs_nonforest_non_pw.get('count') else 0.0
        nonforest_area_non_pw_tenure = qs_nonforest_non_pw.get('area') if qs_nonforest_non_pw.get('area') else 0.0
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

        return rpt_map, item_map

    def escape_burns(self):
        return Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear(), cause__name__icontains='escape')

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
        hdr.write(1, current_finyear())

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style_bold_gen)
        hdr.write(col_no(), "DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Area DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Non DBCA Tenure", style=style_bold_gen)
        hdr.write(col_no(), "Area Non DBCA Tenure", style=style_bold_gen)
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
                    row.write(col_no(), data['area_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['non_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['area_non_pw_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_all_tenure'], style=style_bold_gen)
                    row.write(col_no(), data['total_area'], style=style_bold_gen)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'], style=style_normal)
                    row.write(col_no(), data['area_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['non_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['area_non_pw_tenure'], style=style_normal)
                    row.write(col_no(), data['total_all_tenure'], style=style_normal)
                    row.write(col_no(), data['total_area'], style=style_normal)

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
            row.write(col_no(), bushfire.cause.name)
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
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Region', 'DBCA Tenure', 'Area PDBCA Tenure', 'Non DBCA Tenure', 'Area Non DBCA Tenure', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                if region and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['non_pw_tenure'], data['area_non_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)
                else:
                    print

class BushfireByTenureReport():
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        # Group By Region
        year = current_finyear()
        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED)
        qs0 = qs.filter(year=year).values('tenure_id').annotate(count=Count('tenure_id'), area=Sum('area') )
        qs1 = qs.filter(year=year-1).values('tenure_id').annotate(count=Count('tenure_id'), area=Sum('area') )
        qs2 = qs.filter(year=year-2).values('tenure_id').annotate(count=Count('tenure_id'), area=Sum('area') )

        rpt_map = []
        item_map = {}
        net_count0 = 0
        net_count1 = 0
        net_count2 = 0
        net_area0  = 0
        net_area1  = 0
        net_area2  = 0

        for tenure in Tenure.objects.all().order_by('id'):
            row0 = qs0.get(tenure_id=tenure.id) if qs0.filter(tenure_id=tenure.id).count() > 0 else {}
            row1 = qs1.get(tenure_id=tenure.id) if qs1.filter(tenure_id=tenure.id).count() > 0 else {}
            row2 = qs2.get(tenure_id=tenure.id) if qs2.filter(tenure_id=tenure.id).count() > 0 else {}

            count0 = row0.get('count') if row0.get('count') else 0
            area0  = row0.get('area') if row0.get('area') else 0

            count1 = row1.get('count') if row1.get('count') else 0
            area1  = row1.get('area') if row1.get('area') else 0

            count2 = row2.get('count') if row2.get('count') else 0
            area2  = row2.get('area') if row2.get('area') else 0

            rpt_map.append(
                {tenure.name: dict(count2=count2, count1=count1, count0=count0, area2=area2, area1=area1, area0=area0)}
            )
                
            net_count0      += count0 
            net_count1      += count1 
            net_count2      += count2 
            net_area0       += area0 
            net_area1       += area1 
            net_area2       += area2 

        rpt_map.append(
            {'Total': dict(count2=net_count2, count1=net_count1, count0=net_count0, area2=net_area2, area1=net_area1, area0=net_area0)}
        )

        # add a white space/line between forest and non-forest region tabulated info
        #rpt_map.append(
        #    {'': ''}
        #)

        return rpt_map, item_map



    def get_excel_sheet(self, rpt_date, book=Workbook()):

        year = current_finyear()
        year0 = str(year) + '/' + str(year+1)
        year1 = str(year-1) + '/' + str(year)
        year2 = str(year-2) + '/' + str(year-1)
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


        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date', style=style_bold_gen)
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report', style=style_bold_gen)
        hdr.write(1, 'Bushfire By Tenure Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style_bold_gen)
        hdr.write(1, year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style_bold_gen)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 1, 3, "Number", style_bold)
        sheet1.write_merge(row, row, 4, 6, "Area (ha)", style_bold)
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "ALL REGIONS", style=style_bold_gen)
        hdr.write(col_no(), year2, style=style_bold_gen)
        hdr.write(col_no(), year1, style=style_bold_gen)
        hdr.write(col_no(), year0, style=style_bold_gen)

        hdr.write(col_no(), year2, style=style_bold_gen)
        hdr.write(col_no(), year1, style=style_bold_gen)
        hdr.write(col_no(), year0, style=style_bold_gen)

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
                    row.write(col_no(), data['count2'] if data['count2'] > 0 else '', style=style_bold_gen)
                    row.write(col_no(), data['count1'] if data['count1'] > 0 else '', style=style_bold_gen)
                    row.write(col_no(), data['count0'], style=style_bold_gen)
                    row.write(col_no(), data['area2'] if data['area2'] > 0 else '', style=style_bold_gen)
                    row.write(col_no(), data['area1'] if data['area1'] > 0 else '', style=style_bold_gen)
                    row.write(col_no(), data['area0'], style=style_bold_gen)
                else:
                    row.write(col_no(), tenure, style=style_normal )
                    row.write(col_no(), data['count2'] if data['count2'] > 0 else '', style=style_normal_int)
                    row.write(col_no(), data['count1'] if data['count1'] > 0 else '', style=style_normal_int)
                    row.write(col_no(), data['count0'], style=style_normal_int)
                    row.write(col_no(), data['area2'] if data['area2'] > 0 else '', style=style_normal)
                    row.write(col_no(), data['area1'] if data['area1'] > 0 else '', style=style_normal)
                    row.write(col_no(), data['area0'], style=style_normal)

        # DISCLAIMER
        col_no = lambda c=count(): next(c)
        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), DISCLAIMER, style=style_normal)

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
        year = current_finyear()
        year0 = str(year-1) + '/' + str(year)
        year1 = str(year-2) + '/' + str(year-1)
        year2 = str(year-3) + '/' + str(year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Tenure', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for tenure, data in row.iteritems():
                if tenure and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(tenure, data['count2'], data['count1'], data['count0'], data['area2'], data['area1'], data['area0']).expandtabs(20)
                else:
                    print

class BushfireByCauseReport():
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        # Group By Region
        year = current_finyear()
        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED)
        qs0 = qs.filter(year=year).values('cause_id').annotate(count=Count('cause_id'), area=Sum('area') ) # NOTE area not actually used anywhere in this report - can discard if we want!
        qs1 = qs.filter(year=year-1).values('cause_id').annotate(count=Count('cause_id'), area=Sum('area') ) if year-1 >= 2017 else read_col(year-1, 'count')[0]
        qs2 = qs.filter(year=year-2).values('cause_id').annotate(count=Count('cause_id'), area=Sum('area') ) if year-2 >= 2017 else read_col(year-2, 'count')[0]

        qs0_total = qs.filter(year=year).aggregate(count_total=Count('cause_id'), area_total=Sum('area') )
        qs1_total = qs.filter(year=year-1).aggregate(count_total=Count('cause_id'), area_total=Sum('area') ) if year-1 >= 2017 else read_col(year-1, 'total_count')[0]
        qs2_total = qs.filter(year=year-2).aggregate(count_total=Count('cause_id'), area_total=Sum('area') ) if year-2 >= 2017 else read_col(year-2, 'total_count')[0]

        count_total0 = qs0_total.get('count_total') if qs0_total.get('count_total') else 0
        count_total1 = qs1_total.get('count_total') if qs1_total.get('count_total') else 0
        count_total2 = qs2_total.get('count_total') if qs2_total.get('count_total') else 0

        rpt_map = []
        item_map = {}
        net_count0 = 0
        net_count1 = 0
        net_count2 = 0
        net_perc0 = 0
        net_perc1 = 0
        net_perc2 = 0
        net_area0  = 0
        net_area1  = 0
        net_area2  = 0

        def get_row(qs, cause):
            if isinstance(qs, QuerySet):
                return qs.get(cause_id=cause.id) if qs.filter(cause_id=cause.id).count() > 0 else {}# if isinstance(qs1, Queryset) else 
            else:
                row = [d for d in qs if d.get('cause_id')==cause.id]
                return row[0] if len(row) > 0 else {}

        for cause in Cause.objects.all().order_by('id'):
            row0 = qs0.get(cause_id=cause.id) if qs0.filter(cause_id=cause.id).count() > 0 else {}
            row1 = get_row(qs1, cause)
            row2 = get_row(qs2, cause)

            count0 = row0.get('count') if row0.get('count') else 0
            perc0  = round(count0 * 100. / count_total0, 2) if count_total0 > 0 else 0
            area0  = row0.get('area') if row0.get('area') else 0

            count1 = row1.get('count') if row1.get('count') else 0
            perc1  = round(count1 * 100. / count_total1, 2) if count_total1 > 0 else 0
            area1  = row1.get('area') if row1.get('area') else 0

            count2 = row2.get('count') if row2.get('count') else 0
            perc2  = round(count2 * 100. / count_total2, 2) if count_total2 > 0 else 0
            area2  = row2.get('area') if row2.get('area') else 0

            rpt_map.append(
                {cause.name: dict(
                    count2=count2, count1=count1, count0=count0, 
                    perc2=perc2, perc1=perc1, perc0=perc0, 
                    area2=area2, area1=area1, area0=area0
                )}
            )
                
            net_count0 += count0 
            net_count1 += count1 
            net_count2 += count2 
            net_perc0  += perc0 
            net_perc1  += perc1 
            net_perc2  += perc2 
            net_area0  += area0 
            net_area1  += area1 
            net_area2  += area2 

        rpt_map.append(
            {'Total': dict(
                count2=net_count2, count1=net_count1, count0=net_count0, 
                perc2=round(net_perc2, 0), perc1=round(net_perc1, 0), perc0=round(net_perc0, 0), 
                area2=net_area2, area1=net_area1, area0=net_area0
            )}
        )

        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        year = current_finyear()
        year0 = str(year) + '/' + str(year+1)
        year1 = str(year-1) + '/' + str(year)
        year2 = str(year-2) + '/' + str(year-1)
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
        hdr.write(1, year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

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
                    row.write(col_no(), data['perc2'], style=style_bold_gen)
                    row.write(col_no(), data['perc1'], style=style_bold_gen)
                    row.write(col_no(), data['perc0'], style=style_bold_gen)
                else:
                    row.write(col_no(), tenure, style=style_bold_gen )
                    row.write(col_no(), data['count2'], style=style_normal)
                    row.write(col_no(), data['count1'], style=style_normal)
                    row.write(col_no(), data['count0'], style=style_normal)
                    row.write(col_no(), data['perc2'], style=style_normal)
                    row.write(col_no(), data['perc1'], style=style_normal)
                    row.write(col_no(), data['perc0'], style=style_normal)

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
        year = current_finyear()
        year0 = str(year-1) + '/' + str(year)
        year1 = str(year-2) + '/' + str(year-1)
        year2 = str(year-3) + '/' + str(year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Cause', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for cause, data in row.iteritems():
                if cause and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(cause, data['count2'], data['count1'], data['count0'], data['perc2'], data['perc1'], data['perc0']).expandtabs(25)
                else:
                    print

class RegionByTenureReport():
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):

        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear())
        qs = qs.values('region_id','tenure_id').order_by('region_id','tenure_id').annotate(count=Count('tenure_id'), area=Sum('area') )

        rpt_map = []
        item_map = {}
        for region in Region.objects.all().order_by('id'):
            tmp_list=[]                       
            for tenure in Tenure.objects.all().order_by('id'):
                ls = [i for i in qs if i['tenure_id']==tenure.id and i['region_id']==region.id]
                if ls:
                    tmp_list.append(ls[0])
                else:
                    tmp_list.append(dict(tenure_id=tenure.id, region_id=region.id, count=0, area=0))

            rpt_map.append(tmp_list)

        return rpt_map, item_map

    @property
    def all_map(self):
        return Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).aggregate(count=Count('id'), area=Sum('area') )

    @property
    def region_map(self):

        def contains_id(id):
            """ Returns dict tuple if id contained in qs """
            id_dict = [i for i in qs if i.get('region_id')==id]
            return id_dict[0] if id_dict else False

        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).values('region_id').annotate(count=Count('region_id'), area=Sum('area') )
        regions = {}
        for region in Region.objects.all().order_by('id'):

            id_dict = contains_id(region.id)
            if id_dict:
                regions[region.id] = dict(count=id_dict['count'], area=id_dict['area'])
            else:
                regions[region.id] = dict(count=0, area=0)
                
        return regions

    @property
    def tenure_map(self):

        def contains_id(id):
            """ Returns dict tuple if id contained in qs """
            id_dict = [i for i in qs if i.get('tenure_id')==id]
            return id_dict[0] if id_dict else False

        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).values('tenure_id').annotate(count=Count('tenure_id'), area=Sum('area') )
        tenures = {}
        for tenure in Tenure.objects.all().order_by('id'):
            id_dict = contains_id(tenure.id)
            if id_dict:
                tenures[tenure.id] = dict(count=id_dict['count'], area=id_dict['area'])
            else:
                tenures[tenure.id] = dict(count=0, area=0)
 
        return tenures

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        year = current_finyear()
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
        hdr.write(1, year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 0, 1, "Bushfire Region By Tenure", style_center)
        hdr = sheet1.row(row_no())

        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)
        row.write(col_no(), '')
        row.write(col_no(), '' )
        for i in Tenure.objects.all().order_by('id'):
            row.write(col_no(), i.name, style=style)
        row.write(col_no(), "Total", style=style)

        no_regions = Region.objects.all().count()
        no_tenures = Tenure.objects.all().count()
        all_map = self.all_map
        region_map = self.region_map
        tenure_map = self.tenure_map
        region_ids=[region.id for region in Region.objects.all().order_by('id')]
        for region in self.rpt_map:
            region_id = region_ids.pop(0)
            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), Region.objects.get(id=region_id).name, style=style_bold_gen)
            row.write(col_no(), 'Area', style=style_bold_gen)
            tenure_id = 1
            for tenure in region: # loops through all tenures for given region
                row.write(col_no(), tenure['area'], style=style_normal )

            
            # Right-most 'Total Column' - Area
            row.write(col_no(), region_map[region_id]['area'], style=style_bold_gen )


            row = sheet1.row(row_no())
            col_no = lambda c=count(): next(c)
            row.write(col_no(), '' )
            row.write(col_no(), 'Number', style=style_bold_gen)
            for i in region:
                row.write(col_no(), i['count'], style=style_normal)

            # Right-most 'Total Column' - Number
            row.write(col_no(), region_map[region_id]['count'], style=style_bold_gen)

            row = sheet1.row(row_no())

        # Last Two Rows - 'Grand Total' rows - Area
        col_no = lambda c=count(): next(c)
        row = sheet1.row(row_no())
        row.write(col_no(), 'Grand Total (All Regions)', style=style)
        row.write(col_no(), 'Area (ha)', style=style)
        for tenure_id in tenure_map:
            row.write(col_no(), tenure_map[tenure_id]['area'], style=style_bold_gen)
        # Bottom-Right Two Cells - Total for entire matrix - Area
        row.write(col_no(), all_map.get('area'), style=style_bold_gen)

        # Last Two Rows - 'Grand Total' rows - Number
        col_no = lambda c=count(): next(c)
        row = sheet1.row(row_no())
        row.write(col_no(), '', style=style)
        row.write(col_no(), 'Number', style=style_bold_gen)
        for tenure_id in tenure_map:
            row.write(col_no(), tenure_map[tenure_id]['count'], style=style_bold_gen)
        # Bottom-Right Two Cells - Total for entire matrix - Number
        row.write(col_no(), all_map.get('count'), style=style_bold_gen)

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

    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        # Group By Region
        year = current_finyear()
        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED)

        qs0 = qs.filter(year=year).values('cause_id').annotate(count=Count('cause_id') )
        qs1 = qs.filter(year=year-1).values('cause_id').annotate(count=Count('cause_id') ) if year-1 >= 2017 else read_col(year-1, 'count')[0]
        qs2 = qs.filter(year=year-2).values('cause_id').annotate(count=Count('cause_id') ) if year-2 >= 2017 else read_col(year-2, 'count')[0]
        qs3 = qs.filter(year=year-3).values('cause_id').annotate(count=Count('cause_id') ) if year-3 >= 2017 else read_col(year-3, 'count')[0]
        qs4 = qs.filter(year=year-4).values('cause_id').annotate(count=Count('cause_id') ) if year-4 >= 2017 else read_col(year-4, 'count')[0]
        qs5 = qs.filter(year=year-5).values('cause_id').annotate(count=Count('cause_id') ) if year-5 >= 2017 else read_col(year-5, 'count')[0]
        qs6 = qs.filter(year=year-6).values('cause_id').annotate(count=Count('cause_id') ) if year-6 >= 2017 else read_col(year-6, 'count')[0]
        qs7 = qs.filter(year=year-7).values('cause_id').annotate(count=Count('cause_id') ) if year-7 >= 2017 else read_col(year-7, 'count')[0]
        qs8 = qs.filter(year=year-8).values('cause_id').annotate(count=Count('cause_id') ) if year-8 >= 2017 else read_col(year-8, 'count')[0]
        qs9 = qs.filter(year=year-9).values('cause_id').annotate(count=Count('cause_id') ) if year-9 >= 2017 else read_col(year-9, 'count')[0]

        qs0_total = qs.filter(year=year).aggregate(count_total=Count('cause_id') )
        qs1_total = qs.filter(year=year-1).aggregate(count_total=Count('cause_id') ) if year-1 >= 2017 else read_col(year-1, 'total_count')[0]
        qs2_total = qs.filter(year=year-2).aggregate(count_total=Count('cause_id') ) if year-2 >= 2017 else read_col(year-2, 'total_count')[0]
        qs3_total = qs.filter(year=year-3).aggregate(count_total=Count('cause_id') ) if year-3 >= 2017 else read_col(year-3, 'total_count')[0]
        qs4_total = qs.filter(year=year-4).aggregate(count_total=Count('cause_id') ) if year-4 >= 2017 else read_col(year-4, 'total_count')[0]
        qs5_total = qs.filter(year=year-5).aggregate(count_total=Count('cause_id') ) if year-5 >= 2017 else read_col(year-5, 'total_count')[0]
        qs6_total = qs.filter(year=year-6).aggregate(count_total=Count('cause_id') ) if year-6 >= 2017 else read_col(year-6, 'total_count')[0]
        qs7_total = qs.filter(year=year-7).aggregate(count_total=Count('cause_id') ) if year-7 >= 2017 else read_col(year-7, 'total_count')[0]
        qs8_total = qs.filter(year=year-8).aggregate(count_total=Count('cause_id') ) if year-8 >= 2017 else read_col(year-8, 'total_count')[0]
        qs9_total = qs.filter(year=year-9).aggregate(count_total=Count('cause_id') ) if year-9 >= 2017 else read_col(year-9, 'total_count')[0]

        count_total0 = qs0_total.get('count_total') if qs0_total.get('count_total') else 0
        count_total1 = qs1_total.get('count_total') if qs1_total.get('count_total') else 0
        count_total2 = qs2_total.get('count_total') if qs2_total.get('count_total') else 0
        count_total3 = qs3_total.get('count_total') if qs3_total.get('count_total') else 0
        count_total4 = qs4_total.get('count_total') if qs4_total.get('count_total') else 0
        count_total5 = qs5_total.get('count_total') if qs5_total.get('count_total') else 0
        count_total6 = qs6_total.get('count_total') if qs6_total.get('count_total') else 0
        count_total7 = qs7_total.get('count_total') if qs7_total.get('count_total') else 0
        count_total8 = qs8_total.get('count_total') if qs8_total.get('count_total') else 0
        count_total9 = qs9_total.get('count_total') if qs9_total.get('count_total') else 0

        rpt_map = []
        item_map = {}
        net_count0 = 0; net_perc0 = 0
        net_count1 = 0; net_perc1 = 0
        net_count2 = 0; net_perc2 = 0
        net_count3 = 0; net_perc3 = 0
        net_count4 = 0; net_perc4 = 0
        net_count5 = 0; net_perc5 = 0
        net_count6 = 0; net_perc6 = 0
        net_count7 = 0; net_perc7 = 0
        net_count8 = 0; net_perc8 = 0
        net_count9 = 0; net_perc9 = 0
        net_count_avg = 0; net_perc_avg = 0

        def get_row(qs, cause):
            if isinstance(qs, QuerySet):
                return qs.get(cause_id=cause.id) if qs.filter(cause_id=cause.id).count() > 0 else {}# if isinstance(qs1, Queryset) else 
            else:
                row = [d for d in qs if d.get('cause_id')==cause.id]
                return row[0] if len(row) > 0 else {}
                
        for cause in Cause.objects.all().order_by('id'):
            row0 = qs0.get(cause_id=cause.id) if qs0.filter(cause_id=cause.id).count() > 0 else {}
            row1 = get_row(qs1, cause)
            row2 = get_row(qs2, cause)
            row3 = get_row(qs3, cause)
            row4 = get_row(qs4, cause)
            row5 = get_row(qs5, cause)
            row6 = get_row(qs6, cause)
            row7 = get_row(qs7, cause)
            row8 = get_row(qs8, cause)
            row9 = get_row(qs9, cause)

            count0 = row0.get('count') if row0.get('count') else 0
            perc0  = round(count0 * 100. / count_total0, 2) if count_total0 > 0 else 0

            count1 = row1.get('count') if row1.get('count') else 0
            perc1  = round(count1 * 100. / count_total1, 2) if count_total1 > 0 else 0

            count2 = row2.get('count') if row2.get('count') else 0
            perc2  = round(count2 * 100. / count_total2, 2) if count_total2 > 0 else 0

            count3 = row3.get('count') if row3.get('count') else 0
            perc3  = round(count3 * 100. / count_total3, 2) if count_total3 > 0 else 0

            count4 = row4.get('count') if row4.get('count') else 0
            perc4  = round(count4 * 100. / count_total4, 2) if count_total4 > 0 else 0

            count5 = row5.get('count') if row5.get('count') else 0
            perc5  = round(count5 * 100. / count_total5, 2) if count_total5 > 0 else 0

            count6 = row6.get('count') if row6.get('count') else 0
            perc6  = round(count6 * 100. / count_total6, 2) if count_total6 > 0 else 0

            count7 = row7.get('count') if row7.get('count') else 0
            perc7  = round(count7 * 100. / count_total7, 2) if count_total7 > 0 else 0

            count8 = row8.get('count') if row8.get('count') else 0
            perc8  = round(count8 * 100. / count_total8, 2) if count_total8 > 0 else 0

            count9 = row9.get('count') if row9.get('count') else 0
            perc9  = round(count9 * 100. / count_total9, 2) if count_total9 > 0 else 0

            count_avg = (count0 + count1 + count2 + count3 + count4 + count5 + count6 + count7 + count8 + count9)/10.
            perc_avg = (perc0 + perc1 + perc2 + perc3 + perc4 + perc5 + perc6 + perc7 + perc8 + perc9)/10.


            rpt_map.append(
                {cause.name: dict(
                    count2=count2, count1=count1, count0=count0, count3=count3, count4=count4, count5=count5, count6=count6, count7=count7, count8=count8, count9=count9,
                    perc2=perc2, perc1=perc1, perc0=perc0, perc3=perc3, perc4=perc4, perc5=perc5, perc6=perc6, perc7=perc7, perc8=perc8, perc9=perc9,
                    count_avg=count_avg, perc_avg=perc_avg
                )}
            )
                
            net_count0 += count0; net_perc0  += perc0
            net_count1 += count1; net_perc1  += perc1
            net_count2 += count2; net_perc2  += perc2
            net_count3 += count3; net_perc3  += perc3
            net_count4 += count4; net_perc4  += perc4
            net_count5 += count5; net_perc5  += perc5
            net_count6 += count6; net_perc6  += perc6
            net_count7 += count7; net_perc7  += perc7
            net_count8 += count8; net_perc8  += perc8
            net_count9 += count9; net_perc9  += perc9
            net_count_avg += count_avg
            net_perc_avg += perc_avg

        rpt_map.append(
            {'Total': dict(
                count9=net_count9, count8=net_count8, count7=net_count7, count6=net_count6, count5=net_count5, count4=net_count4, count3=net_count3, count2=net_count2, count1=net_count1, count0=net_count0, 
                perc9=round(net_perc9, 0), perc8=round(net_perc8, 0), perc7=round(net_perc7, 0), perc6=round(net_perc6, 0), perc5=round(net_perc5, 0), perc4=round(net_perc4, 0), perc3=round(net_perc3, 0), perc2=round(net_perc2, 0), perc1=round(net_perc1, 0), perc0=round(net_perc0, 0),
                count_avg=net_count_avg, perc_avg=net_perc_avg
            )}
        )

        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        year = current_finyear()
        year0 = str(year) + '/' + str(year+1)
        year1 = str(year-1) + '/' + str(year)
        year2 = str(year-2) + '/' + str(year-1)
        year3 = str(year-3) + '/' + str(year-2)
        year4 = str(year-4) + '/' + str(year-3)
        year5 = str(year-5) + '/' + str(year-4)
        year6 = str(year-6) + '/' + str(year-5)
        year7 = str(year-7) + '/' + str(year-6)
        year8 = str(year-8) + '/' + str(year-7)
        year9 = str(year-9) + '/' + str(year-8)

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
        hdr.write(1, year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

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
                    row.write(col_no(), data['perc9'], style=style_bold_gen)
                    row.write(col_no(), data['perc8'], style=style_bold_gen)
                    row.write(col_no(), data['perc7'], style=style_bold_gen)
                    row.write(col_no(), data['perc6'], style=style_bold_gen)
                    row.write(col_no(), data['perc5'], style=style_bold_gen)
                    row.write(col_no(), data['perc4'], style=style_bold_gen)
                    row.write(col_no(), data['perc3'], style=style_bold_gen)
                    row.write(col_no(), data['perc2'], style=style_bold_gen)
                    row.write(col_no(), data['perc1'], style=style_bold_gen)
                    row.write(col_no(), data['perc0'], style=style_bold_gen)

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
                    row.write(col_no(), data['perc9'], style=style_normal)
                    row.write(col_no(), data['perc8'], style=style_normal)
                    row.write(col_no(), data['perc7'], style=style_normal)
                    row.write(col_no(), data['perc6'], style=style_normal)
                    row.write(col_no(), data['perc5'], style=style_normal)
                    row.write(col_no(), data['perc4'], style=style_normal)
                    row.write(col_no(), data['perc3'], style=style_normal)
                    row.write(col_no(), data['perc2'], style=style_normal)
                    row.write(col_no(), data['perc1'], style=style_normal)
                    row.write(col_no(), data['perc0'], style=style_normal)

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
                    row.write(col_no(), data['perc_avg'], style=style_bold_gen)
                else:
                    row.write(col_no(), cause, style=style_normal)
                    row.write(col_no(), data['count_avg'], style=style_normal)
                    row.write(col_no(), data['perc_avg'], style=style_normal)

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
        year = current_finyear()
        year0 = str(year-1) + '/' + str(year)
        year1 = str(year-2) + '/' + str(year-1)
        year2 = str(year-3) + '/' + str(year-2)
        print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format('Cause', year2, year1, year0,  year2, year1, year0).expandtabs(20)
        for row in self.rpt_map:
            for cause, data in row.iteritems():
                if cause and data:
                    print '{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(cause, data['count2'], data['count1'], data['count0'], data['perc2'], data['perc1'], data['perc0']).expandtabs(25)
                else:
                    print

class BushfireIndicator():
    def __init__(self):
        self.rpt_map, self.item_map = self.create()

    def create(self):
        # Group By Region
        year = current_finyear()
        qs = Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear(), region__in=Region.objects.filter(forest_region=False), initial_control__name='DBCA P&W')
        qs1 = qs.aggregate(count=Count('id'), area=Sum('area') ) 
        qs2 = qs.filter(area__lte=2.0).aggregate(count=Count('id'), area=Sum('area') ) 
        count1 = qs1.get('count') if qs1.get('count') else 0
        count2 = qs2.get('count') if qs2.get('count') else 0

        rpt_map = []
        item_map = {}
        rpt_map.append({'No of bushfires in the Forest Regions where DBCA was the initial attack agency': dict(count=count1)})
        rpt_map.append({'No of bushfires in the Forest Regions <2ha, where DBCA was the initial attack agency': dict(count=count2)})
        rpt_map.append({'Percentage': dict(count=round(count2*100./count1, 2))})

        return rpt_map, item_map

    def get_excel_sheet(self, rpt_date, book=Workbook()):

        year = current_finyear()
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
        hdr.write(1, 'Bushfire By Cause Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year', style=style)
        hdr.write(1, year)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final', style=style)
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        row = row_no()
        sheet1.write_merge(row, row, 0, 1, "Bushfire Indicator", style_center)
        hdr = sheet1.row(row_no())

        for row in self.rpt_map:
            for key, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if key == '':
                    #row = sheet1.row(row_no())
                    continue
                elif 'total' in key.lower() or 'percentage' in key.lower():
                    #row = sheet1.row(row_no())
                    row.write(col_no(), key, style=style_bold_gen)
                    row.write(col_no(), data['count'], style=style_bold_gen)
                else:
                    row.write(col_no(), key, style=style_normal)
                    row.write(col_no(), data['count'], style=style_normal)

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
        year = current_finyear()
        print '{}\t{}'.format('', 'Number').expandtabs(20)
        for row in self.rpt_map:
            for key, data in row.iteritems():
                if key and data:
                    print '{}\t{}'.format(key, data['count']).expandtabs(25)
                else:
                    print






def export_outstanding_fires(request, region_id, queryset):
    """ Executed from the Overview page in BFRS, returns an Excel WB as a HTTP Response object """

    regions = Region.objects.filter(id=region_id) if region_id else Region.objects.all()
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

            region = Region.objects.get(name=region_name)
            if region:
                f = StringIO()
                book = Workbook()
                outstanding_fires(book, region, qs, rpt_date)
                book.add_sheet('Sheet 2')
                book.save(f)

                subject = 'Outstanding Fires Report - {} - {}'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 
                body = 'Outstanding Fires Report - {} - {}'.format(region_name, rpt_date.strftime('%d-%b-%Y')) 

                filename = 'outstanding_fires_{}_{}.xls'.format(region_name.replace(' ', '').lower(), rpt_date.strftime('%d-%b-%Y'))

                message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=email_to, cc=settings.CC_EMAIL, bcc=settings.BCC_EMAIL)
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
    for obj in qs:
        row = sheet1.row(row_no())
        col_no = lambda c=count(): next(c)

        row.write(col_no(), obj.fire_number )
        row.write(col_no(), obj.name)
        row.write(col_no(), obj.fire_detected_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_detected_date else '' )
        row.write(col_no(), obj.duty_officer.get_full_name() if obj.duty_officer else '' )
        row.write(col_no(), obj.fire_contained_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_contained_date else '' )
        row.write(col_no(), obj.fire_controlled_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_controlled_date else '' )
        row.write(col_no(), obj.fire_safe_date.strftime('%Y-%m-%d %H:%M:%S') if obj.fire_safe_date else '' )
export_outstanding_fires.short_description = u"Outstanding Fires"


