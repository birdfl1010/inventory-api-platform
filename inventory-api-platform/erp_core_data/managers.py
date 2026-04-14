from crum import get_current_user
from django.db import models

from inventory_stock_management.users.models import UserBranchAccess


def get_allowed_branches(user):
    """
    Retrieves a list of branch IDs the given user has access to.

    Args:
        user (User): The user for whom to fetch branch access.

    Returns:
        list: A list of branch identifiers the user can access.
    """
    return list(
        UserBranchAccess.objects.filter(user=user).values_list("branch", flat=True),
    )


class BranchFilterQuerySet(models.QuerySet):
    """
    Custom QuerySet that filters results based on the current user's branch access.
    """

    def for_user(self, branch_lookup):
        """
        Filters the QuerySet to include only objects associated with
        branches the current user can access.

        Args:
            branch_lookup (str): The field name used to filter
            branches (e.g., 'branch' or 'branch__branch').

        Returns:
            QuerySet: A filtered QuerySet restricted to the user's allowed branches.
        """
        user = get_current_user()
        if user and not user.is_superuser:
            allowed_branches = get_allowed_branches(user)
            filter_kwargs = {f"{branch_lookup}__in": allowed_branches}
            return self.filter(**filter_kwargs)
        return self


class BranchAccessManager(models.Manager.from_queryset(BranchFilterQuerySet)):
    """
    Custom model manager that restricts queryset access to branches
    the current user is authorized to access, unless they are a superuser.
    """

    def __init__(self, branch_lookup="branch", *args, **kwargs):
        """
        Initializes the manager with a customizable lookup
        path for branch filtering.

        Args:
            branch_lookup (str): Dot-path string used to
            reference the branch field in models.
        """
        self.branch_lookup = branch_lookup
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        """
        Overrides the default queryset to apply branch-level filtering.

        Returns:
            QuerySet: A queryset filtered by branch access for the current user.
        """
        qs = super().get_queryset()
        return qs.for_user(self.branch_lookup).distinct()

    def __get__(self, instance, owner):
        """
        Ensures the branch lookup field is retained when
        accessed as a class property.

        Args:
            instance: The model instance (if accessed from instance).
            owner: The model class.

        Returns:
            BranchAccessManager: The bound manager instance.
        """
        manager = super().__get__(instance, owner)
        manager.branch_lookup = self.branch_lookup
        return manager
