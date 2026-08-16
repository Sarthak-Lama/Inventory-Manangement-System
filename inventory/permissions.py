from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsStaffOrReadOnly(BasePermission):
    """
    Any authenticated user can read (GET/HEAD/OPTIONS).
    Only staff/admin users can create, update, or delete.

    Use this on viewsets for data that every logged-in user needs to see
    (stock levels, suppliers, categories, orders) but that only trusted
    staff should be able to change. Assumes IsAuthenticated has already
    been satisfied — combine as permission_classes = [IsAuthenticated, IsStaffOrReadOnly].
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsOwnerOrStaff(BasePermission):
    """
    Object-level permission: staff can act on anything; a regular user can
    only act on objects they created (expects an object attribute named
    `created_by`).
    """

    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_staff:
            return True
        owner = getattr(obj, 'created_by', None)
        return owner is not None and owner == request.user