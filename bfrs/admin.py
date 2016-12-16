from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin, GroupAdmin
from django.contrib import admin
from bfrs.forms import UserForm, GroupForm


class UserAdmin(AuthUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name',
                    'is_active')
    #readonly_fields=('username',)
    actions = None
    form = UserForm
    fieldsets = (
        (None, {'fields': ('username', 'email', ('first_name', 'last_name'),
                           'is_active', 'groups')}),
#                           'is_active', 'groups', 'user_permissions')}),
    )
    list_filter = ("is_active", "groups")

    def has_delete_permission(self, request, obj=None):
        """ Removes the 'Delete' Button """
        return False

    def has_add_permission(self, request, obj=None):
        """ Removes the 'Add another' Button """
        return False


class GroupAdmin(GroupAdmin):
    form = GroupForm


admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
