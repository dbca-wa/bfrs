from bfrs.utils import can_maintain_data, is_external_user, is_dbca_user

def user_permissions(request):
    if request.user.is_authenticated:
        return {
            'can_maintain_data': can_maintain_data(request.user),
            'is_external_user': is_external_user(request.user),
            'is_dbca_user': is_dbca_user(request.user),
        }
    return {}