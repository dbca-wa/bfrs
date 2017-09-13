from __future__ import absolute_import

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.encoding import force_text

import csv
import time
import pytz
import json
import email
import struct
import logging
import requests
from imaplib import IMAP4_SSL
from datetime import datetime
import lxml.html
import sys
import os

from bfrs.models import Bushfire
from bfrs.utils import serialize_bushfire, create_admin_user
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)
BATCH_SIZE = 600

class DeferredIMAP():
    '''
    Convenience class for maintaining
    a bit of state about an IMAP server
    and handling logins/logouts.
    Note instances aren't threadsafe.
    '''
    def __init__(self, host, user, password, email_folder):
        self.deletions = []
        self.moved_uat = []
        self.moved_dev = []
        self.moved_test = []
        self.flags = []
        self.host = host
        self.user = user
        self.password = password
        self.email_folder = email_folder

    def login(self):
        self.imp = IMAP4_SSL(self.host)
        self.imp.login(self.user, self.password)
        #self.imp.select("INBOX")
        resp = self.imp.select(self.email_folder)
        if resp[0] != 'OK':
            logger.error("Could not get Mail Folder: {}".format(resp[1]))
            sys.exit()
        if 'bfrs-prod' not in os.getcwd() and settings.HARVEST_EMAIL_FOLDER.lower() == 'inbox':
            logger.error("NON PROD BFRS Server accessing BFRS Email Inbox: {}".format(os.getcwd()))
            sys.exit()



    def logout(self, expunge=False):
        if expunge:
            self.imp.expunge
        self.imp.close()
        self.imp.logout()

    def flush(self):
        self.login()
        if self.moved_uat:
            logger.info("Moving {} NON-PROD emails to UAT folder.".format(len(self.moved_uat)))
            self.imp.copy(",".join(self.moved_uat), 'INBOX/UAT')
            self.imp.store(",".join(self.moved_uat), '+FLAGS', r'(\Deleted)')
        if self.moved_dev:
            logger.info("Moving {} NON-PROD emails to DEV folder.".format(len(self.moved_dev)))
            self.imp.copy(",".join(self.moved_dev), 'INBOX/DEV')
            self.imp.store(",".join(self.moved_dev), '+FLAGS', r'(\Deleted)')
        if self.moved_test:
            logger.info("Moving {} NON-PROD emails to TEST folder.".format(len(self.moved_test)))
            self.imp.copy(",".join(self.moved_test), 'INBOX/Test')
            self.imp.store(",".join(self.moved_test), '+FLAGS', r'(\Deleted)')
        if self.flags:
            logger.info("Flagging {} unprocessable emails.".format(len(self.flags)))
            self.imp.store(",".join(self.flags), '+FLAGS', r'(\Flagged)')
        if self.deletions:
            logger.info("Deleting {} processed emails.".format(len(self.deletions)))
            self.imp.store(",".join(self.deletions), '+FLAGS', r'(\Deleted)')
            self.logout(expunge=True)

        else:
            self.logout()
        self.flags, self.deletions, self.moved = [], [], []

    def move(self, msgid, env):
        if env.lower() == 'uat':
            self.moved_uat.append(str(msgid))
        if env.lower() == 'dev':
            self.moved_dev.append(str(msgid))
        if env.lower() == 'test':
            self.moved_test.append(str(msgid))

    def delete(self, msgid):
        self.deletions.append(str(msgid))

    def flag(self, msgid):
        self.flags.append(str(msgid))

    def __getattr__(self, name):
        def temp(*args, **kwargs):
            self.login()
            result = getattr(self.imp, name)(*args, **kwargs)
            self.logout()
            return result
        return temp



dimap = DeferredIMAP(settings.HARVEST_EMAIL_HOST, settings.HARVEST_EMAIL_USER, settings.HARVEST_EMAIL_PASSWORD, settings.HARVEST_EMAIL_FOLDER)


def retrieve_emails(search):
    textids = dimap.search(None, search)[1][0].split(' ')
    # If no emails just return
    if textids == ['']:
        return []
    typ, responses = dimap.fetch(",".join(textids[-BATCH_SIZE:]), '(BODY.PEEK[])')
    # If protcol error just return
    if typ != 'OK':
        return []
    messages = []
    for response in responses:
        if isinstance(response, tuple):
            msgid = int(response[0].split(' ')[0])
            msg = email.message_from_string(response[1])
            messages.append((msgid, msg))
    logger.info("Fetched {}/{} messages for {}.".format(len(messages), len(textids), search))
    return messages


def save_bushfire_emails(queueitem):
    msgid, msg = queueitem
    msg_meta = {}
    msg_subject = ''
    incident_num = ''
    fire_num = ''
    try:
        admin_user, exists = create_admin_user()
        msg_date = msg.get('Date')
        msg_from = msg.get('From')
        msg_to = msg.get('To')
        msg_subject = msg.get('Subject').replace('\r\n','')
        msg_text = lxml.html.document_fromstring(msg.get_payload(decode=True)).text_content()
        msg_meta = {
            'date': msg_date,
            'from': msg_from,
            'to': msg_to,
            'subject': msg_subject
        }
        try:
            incident_num = msg_text.split('Incident:')[1].split('\r')[0].strip()
            fire_num = msg_text.split('Fire Number:')[1].split('\r')[0].strip()
        except: pass
        if settings.HARVEST_EMAIL_FOLDER.lower() == 'inbox' and any(x in msg_subject for x in ['uat', 'UAT', 'dev', 'DEV', 'test', 'Test', 'TEST']):
            if any(x in msg_subject for x in ['uat', 'UAT']):
                dimap.move(msgid, 'uat')
            elif any(x in msg_subject for x in ['dev', 'DEV']):
                dimap.move(msgid, 'dev')
            elif any(x in msg_subject for x in ['test', 'Test', 'TEST']):
                dimap.move(msgid, 'test')

        elif ('Incident:' in msg_text and 'Fire Number:' in msg_text):
            logger.info('Updating DFES Incident Number - ' + incident_num + ' - ' + fire_num)
            bf = Bushfire.objects.get(fire_number=fire_num)
            bf.dfes_incident_no = incident_num
            bf.modifier = admin_user
            serialize_bushfire('Final', 'DFES Incident No. Update', bf) 
            bf.save()
            dimap.flag(msgid)
        else:
            raise Exception('Incident: and Fire Number: text missing from email')
    except Exception as e:
        logger.warning("Couldn't parse {}, error: {}".format(msg_meta, e))
        support_email(msg_subject, msg_meta, e)
        dimap.flag(msgid)
        return


def support_email(subject, msg_meta, e):
    if not settings.SUPPORT_EMAIL:
       return

    subject = 'DFES HARVEST ERROR: Incident No - Auto Update Failed - {}'.format(subject)
    body = 'Subject: {}<br><br>Could not parse {}<br><br>{}'.format(subject, msg_meta, e)

    message = EmailMessage(subject=subject, body=body, from_email=settings.FROM_EMAIL, to=settings.SUPPORT_EMAIL)
    message.content_subtype = 'html'
    message.send()


def cron(request=None):
    """
    Collect and save bushfire reporting system emails
    """
    start = timezone.now()
    map(save_bushfire_emails, retrieve_emails('(UNFLAGGED)'))
    dimap.flush()
    delta = timezone.now() - start
    html = "<html><body>Cron run at {} for {}.</body></html>".format(start, delta)
    if request:
        return HttpResponse(html)
    else:
        print(html)
