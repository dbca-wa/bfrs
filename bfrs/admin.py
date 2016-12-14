from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin, GroupAdmin
from django.contrib import admin
from bfrs.forms import UserForm, GroupForm
#admin.site.register(Bushfire, BushfireAdmin)


class UserAdmin(AuthUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name',
                    'is_active')
    #readonly_fields=('username',)
    actions = None
    form = UserForm
    fieldsets = (
        (None, {'fields': ('username', 'email', ('first_name', 'last_name'),
                           'is_active', 'groups', 'user_permissions')}),
    )
    list_filter = ("is_active", "groups", "user_permissions")

    def has_delete_permission(self, request, obj=None):
        """ Removes the 'Delete' Button """
        return False

    def has_add_permission(self, request, obj=None):
        """ Removes the 'Add another' Button """
        return False


class GroupAdmin(GroupAdmin):
#    list_display = ('username', 'email', 'first_name', 'last_name',
#                    'is_active')
#    #readonly_fields=('username',)
#    actions = None
    form = GroupForm
#    fieldsets = (
#        (None, {'fields': ('username', 'email', ('first_name', 'last_name'),
#                           'is_active', 'groups', 'user_permissions')}),
#    )
#    list_filter = ("is_active", "groups", "user_permissions")
#
#    def has_delete_permission(self, request, obj=None):
#        """ Removes the 'Delete' Button """
#        return False
#
#    def has_add_permission(self, request, obj=None):
#        """ Removes the 'Add another' Button """
#        return False

#site.register(User, UserAdmin)
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
