from .permissions import (
    can_create_inventory_unit,
    can_manage_inventory,
    has_inventory_access,
    inventory_role,
)


def inventory_nav(request):
    if not request.user.is_authenticated:
        return {
            'show_inventory_nav': False,
            'inventory_can_manage': False,
            'inventory_can_add_unit': False,
            'inventory_role': '',
        }
    return {
        'show_inventory_nav': has_inventory_access(request.user),
        'inventory_can_manage': can_manage_inventory(request.user),
        'inventory_can_add_unit': can_create_inventory_unit(request.user),
        'inventory_role': inventory_role(request.user) or 'employee',
    }
