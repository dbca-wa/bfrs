from io import BytesIO

from django.db import connection, transaction
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from datetime import datetime
from email.mime.application import MIMEApplication
import pandas as pd

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Generates a discrepancy report for a financial year"

    FILENAME = "Discrepancy EOFY {financial_year}.xlsx"
    DISCREPANCY_SHEET_NAME = "Discrepancy Report"
    ALL_DATA_SHEET_NAME = "All Data"
    EMAIL_SUBJECT = "Spatial Area Discrepancy Report {financial_year}"
    EMAIL_CONTENT = "Discrepancy Report EOFY {financial_year}"
    SHEET_DISCREPANCY_SQL = """
        SELECT
                *,
                spatial_geometry_total_area - bfrs_area_yellow AS diff_bfrs_area_yellow,
                spatial_geometry_total_area - reporting_area_grey AS diff_reporting_area_grey
        FROM (
                SELECT
                        id,
                        fire_number,
                        ROUND((ST_Area(ST_Transform(fire_boundary, 900914)) / 10000)::numeric, 2) AS spatial_geometry_total_area,
        (
                                SELECT
                                        sum(area)
                                FROM
                                        bfrs_areaburnt
                                WHERE
                                        bushfire_id = bf.id) AS bfrs_area_yellow,
        (
                                        SELECT
                                                sum(area)
                                        FROM
                                                reporting_areaburnt
                                        WHERE
                                                bushfire_id = bf.id) AS reporting_area_grey
                                FROM
                                        bfrs_bushfire AS bf
                                WHERE
                                        bf.reporting_year = %s
                                        AND bf.report_status IN (3, 4)) AS bfrs_spatial_compare
        WHERE
                spatial_geometry_total_area != bfrs_area_yellow
                OR spatial_geometry_total_area != reporting_area_grey;
    """
    SHEET_ALL_DATA_SQL = """
        SELECT
                id,
                fire_number,
                ROUND((ST_Area(ST_Transform(fire_boundary, 900914)) / 10000)::numeric, 2) AS spatial_geometry_total_area,
        (
                        SELECT
                                sum(area)
                        FROM
                                bfrs_areaburnt
                        WHERE
                                bushfire_id = bf.id) AS bfrs_area_yellow,
        (
                        SELECT
                                sum(area)
                        FROM
                                reporting_areaburnt
                        WHERE
                                bushfire_id = bf.id) AS reporting_area_grey
        FROM
                bfrs_bushfire AS bf
        WHERE
                bf.reporting_year = %s
                AND bf.report_status IN (3, 4);
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the command in dry run mode without sending out emails.",
        )
        parser.add_argument(
            "--financial-year",
            type=int,
            default=timezone.now().year,
            help="Specify the financial year for the report. If not provided, the current year will be used.",
        )
        return super().add_arguments(parser)

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        financial_year = options.get("financial_year", self.get_financial_year())
        params = [financial_year]

        logger.info(
            f"Generating discrepancy reports for financial year {financial_year} ..."
        )
        success = 0

        # Execute SQL queries
        with connection.cursor() as cursor:
            cursor.execute(self.SHEET_DISCREPANCY_SQL, params)
            rows_discrepancy = cursor.fetchall()
            # Get discrepancy column names
            columns_discrepancy = [col[0] for col in cursor.description]

            cursor.execute(self.SHEET_ALL_DATA_SQL, params)
            rows_all_data = cursor.fetchall()
            # Get all data column names
            columns_all_data = [col[0] for col in cursor.description]

        logger.info("Discrepancy reports generated successfully.")

        # Convert rows to pandas DataFrames
        df_discrepancy = pd.DataFrame(rows_discrepancy, columns=columns_discrepancy)
        df_all_data = pd.DataFrame(rows_all_data, columns=columns_all_data)

        if dry_run:
            logger.info("Dry run mode is enabled. No changes will be made.")

            logger.info(f"Discrepancy report for financial year {financial_year}:")
            logger.info(df_discrepancy)
            logger.info(f"All data report for financial year {financial_year}:")
            logger.info(df_all_data)
            success = 1
        else:
            filename = self.FILENAME.format(financial_year=financial_year)
            output = BytesIO()
            # Create Excel file
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_discrepancy.to_excel(
                    writer, sheet_name=self.DISCREPANCY_SHEET_NAME, index=False
                )
                df_all_data.to_excel(
                    writer, sheet_name=self.ALL_DATA_SHEET_NAME, index=False
                )
            output.seek(0)  # Reset the pointer to the beginning of the BytesIO object
            file = MIMEApplication(output.read(), name=filename)
            file["Content-Disposition"] = f'attachment; filename="{filename}"'

            # Send report via email
            success = self.send_notification_email(
                subject=self.EMAIL_SUBJECT.format(financial_year=financial_year),
                content=self.EMAIL_CONTENT.format(financial_year=financial_year),
                financial_year=financial_year,
                attachments=[file],
            )

        # Done
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDiscrepancy Report for financial year {financial_year} generated successfully."
            )
            if success == 1
            else self.style.ERROR(
                f"\nFailed to generate Discrepancy Report for financial year {financial_year}."
            )
        )

    def get_financial_year(self):
        """
        Get the current financial year based on the current date.
        """

        today = datetime.now()
        if today.month >= 7:  # From July to December
            return today.year
        else:  # From January to June
            return today.year - 1

    def send_notification_email(
        self,
        subject="Financial Year Report",
        content="Discrepancy Report EOFY",
        financial_year="N/A",
        attachments=[],
    ):
        template = "bfrs/email/discrepancy_report_eofy.html"
        user_email = "karsten.prehn@dbca.wa.gov.au"
        to_email = settings.DISCREPANCY_REPORT_EMAIL

        logger.info(f"Sending discrepancy report to {', '.join(to_email)} ...")

        if len(to_email) == 0:
            logger.warning("No discrepancy report recipient email address found.")
            return 0

        context = {
            "content": content,
            "user_email": user_email,
            "external_email": False,
            "to_email": to_email,
            "financial_year": financial_year,
        }

        body = render_to_string(template, context=context)

        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.FROM_EMAIL,
            to=to_email,
        )
        for attachment in attachments:
            message.attach(attachment)
        message.content_subtype = "html"
        ret = message.send()

        logger.info(
            f"Email sent to {to_email} with subject '{content}' and return code {ret}"
        )

        return ret
