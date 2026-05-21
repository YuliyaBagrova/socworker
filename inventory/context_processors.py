from .permissions import (
    can_create_inventory_unit,
    can_manage_inventory,
    has_inventory_access,
    inventory_role,
    is_inventory_manager_interface_user,
)


def inventory_nav(request):
    inv_mgr_ui = (
        request.user.is_authenticated
        and is_inventory_manager_interface_user(request.user)
    )
    # Блокировка остальных пунктов шапки — только для «Управляющий инвентарём», не на всех страницах inventory
    locked_top_nav = inv_mgr_ui

    if not request.user.is_authenticated:
        return {
            'show_inventory_nav': False,
            'inventory_can_manage': False,
            'inventory_can_add_unit': False,
            'inventory_role': '',
            'sw_inventory_top_nav_locked': locked_top_nav,
            'sw_inventory_manager_interface': False,
        }
    return {
        'show_inventory_nav': has_inventory_access(request.user),
        'inventory_can_manage': can_manage_inventory(request.user),
        'inventory_can_add_unit': can_create_inventory_unit(request.user),
        'inventory_role': inventory_role(request.user) or '',
        'sw_inventory_top_nav_locked': locked_top_nav,
        'sw_inventory_manager_interface': inv_mgr_ui,
    }
