from __future__ import (division, print_function, unicode_literals,
                        absolute_import)

import logging
import magic  # File MIME-type identification
import reversion
import threading

from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.contrib.auth import get_user_model
from django.contrib.gis.db import models
from django.core.urlresolvers import reverse
from django.utils import timezone
from django.utils.encoding import python_2_unicode_compatible

logger = logging.getLogger("log." + __name__)
INITIAL_COMMENT = 'Initial version.'


@python_2_unicode_compatible
class Audit(models.Model):

    class Meta:
        abstract = True

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_created', editable=False)
    modifier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_modified', editable=False)
    created = models.DateTimeField(default=timezone.now, editable=False)
    modified = models.DateTimeField(auto_now=True, editable=False)

    def __init__(self, *args, **kwargs):
        super(Audit, self).__init__(*args, **kwargs)
        self._changed_data = None
        self._initial = {}
        if self.pk:
            for field in self._meta.fields:
                self._initial[field.attname] = getattr(self, field.attname)

    def has_changed(self):
        """
        Returns true if the current data differs from initial.
        """
        return bool(self.changed_data)

    def get_changed_data(self):
        if self._changed_data is None:
            self._changed_data = []
            for field, value in self._initial.items():
                if field in ["modified", "modifier_id"]:
                    continue
                if getattr(self, field) != value:
                    self._changed_data.append(field)
        return self._changed_data
    changed_data = property(get_changed_data)

    def save(self, *args, **kwargs):

        '''
        This falls back on using an admin user if a thread request object wasn't found
        '''
        #import ipdb; ipdb.set_trace()
        User = get_user_model()
        _locals = threading.local()

        if ((not hasattr(_locals, "request") or _locals.request.user.is_anonymous())):
            if hasattr(_locals, "user"):
                user = _locals.user
            else:
                try:
                    user = User.objects.get(pk=_locals.request.user.pk)
                except Exception:
                    user = User.objects.get(username__icontains='admin')
                _locals.user = user
        else:
            try:
                user = User.objects.get(pk=_locals.request.user.pk)
            except Exception:
                user = User.objects.get(id=1)

        # If saving a new model, set the creator.
        if not self.pk:
            try:
                self.creator
            except ObjectDoesNotExist:
                self.creator = user

            try:
                self.modifier
            except ObjectDoesNotExist:
                self.modifier = user

            created = True
        else:
            created = False
            self.modifier = user

        super(Audit, self).save(*args, **kwargs)

        if created:
            with reversion.create_revision():
                reversion.set_comment('Initial version.')
        else:
            if self.has_changed():
                comment = 'Changed ' + ', '.join(self.changed_data) + '.'
                with reversion.create_revision():
                    reversion.set_comment(comment)
            else:
                with reversion.create_revision():
                    reversion.set_comment('Nothing changed.')

    def __str__(self):
        return str(self.pk)

#    def get_absolute_url(self):
#        opts = self._meta.app_label, self._meta.module_name
#        return reverse("admin:%s_%s_change" % opts, args=(self.pk, ))
#        return reverse("bushfire:index")

    def clean_fields(self, exclude=None):
        """
        Override clean_fields to do what model validation should have done
        in the first place -- call clean_FIELD during model validation.
        """
        errors = {}

        for f in self._meta.fields:
            if f.name in exclude:
                continue
            if hasattr(self, "clean_%s" % f.attname):
                try:
                    getattr(self, "clean_%s" % f.attname)()
                except ValidationError as e:
                    # TODO: Django 1.6 introduces new features to
                    # ValidationError class, update it to use e.error_list
                    errors[f.name] = e.messages

        try:
            super(Audit, self).clean_fields(exclude)
        except ValidationError as e:
            errors = e.update_error_dict(errors)

        if errors:
            raise ValidationError(errors)


