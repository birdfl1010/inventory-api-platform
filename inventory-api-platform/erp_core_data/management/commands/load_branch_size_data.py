import polars as pl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from erp_core_data.models import BranchSize


class Command(BaseCommand):
    """
    Management command to load ERP core data, currently focused on BranchSize.
    """

    help = "Load ERP Data to use as Core Data"

    def handle(self, *args, **kwargs):
        # Batch size for loading
        batch_size = 999

        # Load data for each model
        self.load_branch_size_data(batch_size)

        self.stdout.write(self.style.SUCCESS("All data loaded successfully!"))

    def load_branch_size_data(self, batch_size):
        """
        Load static branch size data into the BranchSize model.
        Existing records are updated; new records are inserted.

        Args:
            batch_size (int): Number of records per batch for bulk_create.
        """
        self.stdout.write("Loading branch size data...")

        # Static branch size definitions
        branch_sizes = {
            "pk": [1, 2, 3],
            "size_description": ["Small", "Medium", "Large"],
        }
        branch_size_df = pl.from_dict(branch_sizes)

        new_objs = []
        with transaction.atomic():
            for row in branch_size_df.iter_rows(named=True):
                # Update if exists; otherwise create a new one
                obj, created = BranchSize.objects.update_or_create(
                    pk=row["pk"],
                    defaults={
                        "size_description": row["size_description"],
                        "last_updated": timezone.now(),
                    },
                )
                # Track newly created objects for potential bulk operations
                if created:
                    obj.last_updated = timezone.now()
                    new_objs.append(obj)

        # Optionally bulk create new objects if needed
        if new_objs:
            BranchSize.objects.bulk_create(new_objs, batch_size=batch_size)
