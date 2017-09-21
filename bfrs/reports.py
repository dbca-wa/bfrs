from django.db import connection
from bfrs.models import Bushfire, Region, current_finyear
from django.db.models import Count, Sum
from datetime import datetime
from xlwt import Workbook, Font, XFStyle
from itertools import count
import unicodecsv

from django.http import HttpResponse
from django.core.mail import send_mail
from cStringIO import StringIO
from django.core.mail import EmailMessage
from django.conf import settings


class MinisterialReport():
    def __init__(self):
        self.rpt_map = self.create()

    def create(self):
        # Group By Region
        qs=Bushfire.objects.filter(report_status__gte=Bushfire.STATUS_FINAL_AUTHORISED, year=current_finyear()).values('region_id')
        qs1=qs.filter(initial_control__name='DBCA P&W').annotate(dbca_count=Count('region_id'), dbca_sum=Sum('area') )
        qs2=qs.exclude(initial_control__isnull=True).annotate(total_count=Count('region_id'), total_sum=Sum('area') )

        net_pw_tenure      = 0
        net_area_pw_tenure = 0
        net_total_all_area = 0
        net_total_area     = 0
        rpt_map = []
        try:
            for region in Region.objects.all().order_by('id'):
                row1 = qs1.get(region_id=region.id) if qs1.filter(region_id=region.id).count() > 0 else {}
                row2 = qs2.get(region_id=region.id) if qs2.filter(region_id=region.id).count() > 0 else {}

                pw_tenure      = row1['dbca_count'] if row1.has_key('dbca_count') and row1['dbca_count'] else 0
                area_pw_tenure = round(row1['dbca_sum'], 2) if row1.has_key('dbca_sum') and row1['dbca_sum'] else 0
                total_all_area = row2['total_count'] if row2.has_key('total_count') and row2['total_count'] else 0
                total_area     = round(row2['total_sum'], 2) if row2.has_key('total_sum') and row2['total_sum'] else 0

                rpt_map.append(
                    {region.name: dict(pw_tenure=pw_tenure, area_pw_tenure=area_pw_tenure, total_all_tenure=total_all_area, total_area=total_area)}
                )
                    
                net_pw_tenure      += pw_tenure 
                net_area_pw_tenure += area_pw_tenure
                net_total_all_area += total_all_area
                net_total_area     += total_area
        except:
            import ipdb; ipdb.set_trace()

        rpt_map.append(
            {'Total': dict(pw_tenure=net_pw_tenure, area_pw_tenure=net_area_pw_tenure, total_all_tenure=net_total_all_area, total_area=net_total_area)}
        )
                
        return rpt_map

    def export_final_csv(self, request, queryset):
        writer = unicodecsv.writer(response, quoting=unicodecsv.QUOTE_ALL)

        writer.writerow([
            "Region",
            "PW Tenure",
            "Area PW Tenure",
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

        style = XFStyle()
        # font
        font = Font()
        font.bold = True
        style.font = font

        col_no = lambda c=count(): next(c)
        row_no = lambda c=count(): next(c)

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report Date')
        hdr.write(1, rpt_date.strftime('%d-%b-%Y'))

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Report')
        hdr.write(1, 'Ministerial Report')

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Fin Year')
        hdr.write(1, current_finyear())

        hdr = sheet1.row(row_no())
        hdr.write(0, 'Missing Final')
        hdr.write(1, Bushfire.objects.filter(report_status=Bushfire.STATUS_INITIAL_AUTHORISED, year=current_finyear()).count() )

        hdr = sheet1.row(row_no())
        hdr = sheet1.row(row_no())
        hdr.write(col_no(), "Region", style=style)
        hdr.write(col_no(), "PW Tenure", style=style)
        hdr.write(col_no(), "Area PW Tenure", style=style)
        hdr.write(col_no(), "Total All Area", style=style)
        hdr.write(col_no(), "Total Area", style=style)

        for row in self.rpt_map:
            for region, data in row.iteritems():

                row = sheet1.row(row_no())
                col_no = lambda c=count(): next(c)
                if region == 'Total':
                    row = sheet1.row(row_no())
                    row.write(col_no(), region, style=style)
                    row.write(col_no(), data['pw_tenure'], style=style)
                    row.write(col_no(), data['area_pw_tenure'], style=style)
                    row.write(col_no(), data['total_all_tenure'], style=style)
                    row.write(col_no(), data['total_area'], style=style)
                else:
                    row.write(col_no(), region )
                    row.write(col_no(), data['pw_tenure'])
                    row.write(col_no(), data['area_pw_tenure'])
                    row.write(col_no(), data['total_all_tenure'])
                    row.write(col_no(), data['total_area'])

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
        print '{}\t{}\t{}\t{}\t{}'.format('Region', 'PW Tenure', 'Area PW Tenure', 'Total All Area', 'Total Area').expandtabs(20)
        for row in self.rpt_map:
            for region, data in row.iteritems():
                print '{}\t{}\t{}\t{}\t{}'.format(region, data['pw_tenure'], data['area_pw_tenure'], data['total_all_tenure'], data['total_area']).expandtabs(20)


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
#        import ipdb; ipdb.set_trace()

#        result_list = []
#        for row in cursor.fetchall():
#            print row
#            p = self.model(id=row[0], name=row[1], fire_number=row[2])
#            p.num_bushfires = row[3]
#            result_list.append(p)
#    return result_list

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

                #import ipdb; ipdb.set_trace()
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


