import uuid

from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.timezone import now

from .models import ChangeLog
from .models import ProdBranchChange


@receiver(pre_save, sender=ProdBranchChange)
def log_changes(sender, instance, **kwargs):
    """
    Signal handler to log field changes made in a ProdBranchChange instance
    by comparing new values with either the existing ProdBranch state or
    a previous ProdBranchChange record (if updating).

    This logs into the ChangeLog model using a shared change_session_id for grouping.
    """
    try:
        # Access the related ProdBranch record
        prodbranch = instance.prodbranch
        # Retrieve the previous ProdBranchChange record if it exists
        old_instance = ProdBranchChange.objects.get(pk=instance.pk)
    except ProdBranchChange.DoesNotExist:
        old_instance = None

    # Optional metadata for user auditing
    user = getattr(instance, "_changed_by", None)
    change_session_id = getattr(instance, "_change_session_id", uuid.uuid4())

    # Define which fields to track and their corresponding change fields
    fields_to_track = [
        ("manual_minimum", "manual_minimum_change"),
        ("manual_maximum", "manual_maximum_change"),
        ("cost_estimation", "cost_estimation_change"),
    ]

    changes = []

    for prod_field, change_field in fields_to_track:
        # Determine the previous value
        old_value = (
            getattr(prodbranch, prod_field, None)
            if old_instance is None
            else getattr(old_instance, change_field, None)
        )
        new_value = getattr(instance, change_field, None)

        # Normalize None to zero for comparison
        old_value = old_value if old_value is not None else 0
        new_value = new_value if new_value is not None else 0

        # Log the change if the values differ
        if old_value != new_value:
            changes.append(
                ChangeLog(
                    prod_branch=prodbranch,
                    change_session_id=change_session_id,
                    field_name=change_field,
                    previous_value=old_value,
                    new_value=new_value,
                    changed_by=user,
                    timestamp=now(),
                ),
            )

    # Bulk insert the collected change records
    if changes:
        ChangeLog.objects.bulk_create(changes)
