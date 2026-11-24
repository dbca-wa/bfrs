import tempfile
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string
from django.conf import settings

from bfrs.models import Bushfire
from bfrs import utils

# Create your tests here.

@override_settings(
    ALLOW_EMAIL_NOTIFICATION=True,
    EMAIL_EXCLUSIONS=[],
    EMAIL_DELIVERY="on",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_INSTANCE="TEST",
    ENV_TYPE="PROD",
    FROM_EMAIL="from@example.com",
    CC_EMAIL=["cc@example.com"],
    BCC_EMAIL=["bcc@example.com"],
    SUPPORT_EMAIL=["support@example.com"],
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": False,
        "OPTIONS": {
            "loaders": [("django.template.loaders.locmem.Loader", {
                "test_email.html": "<p>Test {{ bushfire.fire_number }}</p>",
            })],
        },
    }],
)
class SendEmailTests(SimpleTestCase):
    def setUp(self):
        self.context = {
            "bushfire": SimpleNamespace(fire_number="TEST-1"),
            "subject": "Test notification",
            "template": "test_email.html",
            "to_email": ["to@example.com"],
            "user_email": "user@example.com",
        }

    @patch("wagov_utils.components.utils.email.email_log")
    def test_sends_html_text_recipients_and_attachment(self, email_log):
        with tempfile.NamedTemporaryFile() as attachment:
            attachment.write(b"attachment content")
            attachment.flush()
            self.context["attachments"] = [(attachment.name, "test.pdf", "application/pdf")]
            self.assertEqual(utils.send_email(self.context), (True, ""))

        message = mail.outbox[0]
        self.assertEqual(message.from_email, "from@example.com")
        self.assertEqual(message.to, ["to@example.com"])
        self.assertEqual(message.cc, ["cc@example.com", "user@example.com"])
        self.assertEqual(message.bcc, ["bcc@example.com"])
        self.assertEqual(message.body, "Test TEST-1")
        self.assertEqual(message.alternatives[0].content, "<p>Test TEST-1</p>")
        self.assertEqual(message.attachments[0].content, b"attachment content")
        self.assertTrue(any("Successfully sent to mail gateway" in call.args[0]
                            for call in email_log.call_args_list))

    @override_settings(EMAIL_DELIVERY="off")
    @patch("wagov_utils.components.utils.email.email_log")
    @patch("bfrs.utils.support_email")
    def test_delivery_off_does_not_send_support_email(self, support_email, email_log):
        self.assertEqual(utils.send_email(self.context), (False, "Email delivery is disabled."))
        self.assertFalse(getattr(mail, "outbox", []))
        support_email.assert_not_called()
        email_log.assert_called()

    @override_settings(EMAIL_DELIVERY="off", CC_EMAIL=[], BCC_EMAIL=[])
    @patch("wagov_utils.components.utils.email.email_log")
    @patch("bfrs.utils.support_email")
    def test_delivery_off_without_recipients_does_not_send_support_email(self, support_email, email_log):
        self.context["to_email"] = []
        self.context["user_email"] = None
        self.assertEqual(utils.send_email(self.context), (False, "Email delivery is disabled."))
        support_email.assert_not_called()

    def test_writes_email_log(self):
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(BASE_DIR=directory):
                self.assertEqual(utils.send_email(self.context), (True, ""))
            with open(os.path.join(directory, "logs", "email.log")) as log:
                contents = log.read()
        self.assertIn("Test notification:['to@example.com']:test_email.html", contents)
        self.assertIn("Successfully sent to mail gateway", contents)

    @override_settings(ALLOW_EMAIL_NOTIFICATION=False)
    @patch("wagov_utils.components.utils.email.email_log")
    def test_notifications_disabled(self, email_log):
        self.assertEqual(utils.send_email(self.context), (False, "Email notification feature is disabled."))
        email_log.assert_not_called()

    @override_settings(EMAIL_EXCLUSIONS=["TEST-1"])
    @patch("wagov_utils.components.utils.email.email_log")
    def test_excluded_bushfire(self, email_log):
        self.assertEqual(utils.send_email(self.context), (False, "Email notification for this bushfire is disabled."))
        email_log.assert_not_called()

    @patch("wagov_utils.components.utils.email.email_log")
    @patch("bfrs.utils.support_email")
    @patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=RuntimeError("SMTP failure"))
    def test_send_failure_notifies_support(self, send_messages, support_email, email_log):
        self.assertEqual(utils.send_email(self.context), (False, ""))
        support_email.assert_called_once()
        self.assertTrue(any("Error Sending - SMTP failure" in call.args[0]
                            for call in email_log.call_args_list))

    @override_settings(CC_EMAIL=[], BCC_EMAIL=[])
    @patch("bfrs.utils.support_email")
    def test_no_recipients_reports_failure(self, support_email):
        self.context["to_email"] = []
        self.context["user_email"] = None
        self.assertEqual(utils.send_email(self.context), (False, ""))
        support_email.assert_called_once()

def test_fire_bombing(bushfire=None):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,str):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    foldername,pdf_filename = utils.generate_pdf("latex/fire_bombing_request_form.tex",context={"bushfire":bushfire,"graphic_folder":settings.LATEX_GRAPHIC_FOLDER})

    print("pdf_filename = {}".format(pdf_filename))

def test_send_fire_bomging_req_email(bushfire=None,user_email=None):
    if isinstance(bushfire,int):
        bushfire = Bushfire.objects.get(id = bushfire)
    elif isinstance(bushfire,str):
        bushfire = Bushfire.objects.get(fire_number = bushfire)
    else:
        bushfire = Bushfire.objects.all().first()
    utils.send_fire_bomging_req_email({
        "bushfire":bushfire, 
        "user_email":user_email,
        "request":None,
    })



