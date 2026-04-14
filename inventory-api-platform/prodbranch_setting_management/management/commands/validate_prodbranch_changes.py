from django.core.management.base import BaseCommand
from prodbranch_setting_management.models import ProdBranchChange


class Command(BaseCommand):
    """
    Validates ProdBranchChange entries by comparing them to their corresponding
    ProdBranch values. Clears matching fields and deletes change records
    if no meaningful changes remain.
    """

    help = "Validates and prunes ProdBranchChange records against current ProdBranch data"

    def handle(self, *args, **kwargs):
        changes = ProdBranchChange.objects.select_related("prodbranch")
        total_checked = 0
        total_cleared = 0
        total_deleted = 0

        for change in changes:
            pb = change.prodbranch
            modified = False

            if change.stockflag_change is not None and change.stockflag_change == pb.stock_flag_binary:
                change.stockflag_change = None
                modified = True

            if change.manual_minimum_change is not None and change.manual_minimum_change == pb.manual_minimum:
                change.manual_minimum_change = None
                modified = True

            if change.manual_maximum_change is not None and change.manual_maximum_change == pb.manual_maximum:
                change.manual_maximum_change = None
                modified = True

            if (
                change.stockflag_change is None and
                change.manual_minimum_change is None and
                change.manual_maximum_change is None
            ):
                change.delete()
                total_deleted += 1
            elif modified:
                change.save()
                total_cleared += 1

            total_checked += 1

        self.stdout.write(self.style.SUCCESS(f"Validated {total_checked} change records"))
        self.stdout.write(self.style.SUCCESS(f"Cleared fields on {total_cleared} records"))
        self.stdout.write(self.style.SUCCESS(f"Deleted {total_deleted} empty records"))
