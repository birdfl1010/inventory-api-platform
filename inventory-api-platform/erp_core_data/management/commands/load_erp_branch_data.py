from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import Branch
from erp_core_data.models import BranchSize
from erp_core_data.models import Region
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load ERP branch data from Snowflake into the local database.
    Performs bulk updates and inserts for improved efficiency.
    """

    help = "Load ERP Data to use as Core Data"

    def handle(self, *args, **kwargs):
        # Import environment handling for secure credential management
        import environ
        from django.conf import settings

        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        # Establish connection to Snowflake
        conn = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
            disable_ocsp_checks=True,
        )

        # Batch size for bulk create
        batch_size = 999

        # Load branch data
        self.load_branch_data(conn, batch_size)

        self.stdout.write(self.style.SUCCESS("All data loaded successfully!"))

    def load_branch_data(self, conn, batch_size):
        """
        Loads branch data from Snowflake,
        updating existing records and inserting new ones.

        Args:
            conn: Snowflake database connection.
            batch_size (int): Batch size for bulk_create.
        """
        self.stdout.write("Loading branch data...")

        # Query to retrieve branch records from Snowflake
        branch_sql_query = "SELECT * FROM SANDBOX.DIGITALSOLUTIONS.SMS_REGION_VIEW"
        branch_df = execute_query(conn, branch_sql_query)

        # Default size assignment
        small_branch = BranchSize.objects.get(id=1)

        # Lookup Region instances by ID to associate with branches
        region_lookup = {region.id: region for region in Region.objects.all()}

        # Transform Snowflake result into a dictionary of data keyed by branch ID
        incoming_data = {
            row["BRANCHID"]: {
                "branch_name": row["BRANCHNAME"],
                "division": row["DIVISION"],
                "region": region_lookup.get(row["REGIONID"]),
                "longitude": row["LONGITUDE"],
                "latitude": row["LATITUDE"],
                "branch_size": small_branch,
            }
            for row in branch_df.iter_rows(named=True)
        }

        # Fetch existing branches to determine which to update
        existing_branches = Branch.objects.filter(branch__in=incoming_data.keys())
        existing_branches_dict = {branch.branch: branch for branch in existing_branches}

        branches_to_update = []
        branches_to_create = []

        for branch_id, data in incoming_data.items():
            if branch_id in existing_branches_dict:
                # Update fields of existing branches
                branch = existing_branches_dict[branch_id]
                branch.branch_name = data["branch_name"]
                branch.division = data["division"]
                branch.region = data["region"]
                branch.longitude = data["longitude"]
                branch.latitude = data["latitude"]
                branch.branch_size = data["branch_size"]
                branch.last_updated = timezone.now()
                branches_to_update.append(branch)
            else:
                # Prepare new branches for insertion
                branches_to_create.append(
                    Branch(
                        branch=branch_id,
                        branch_name=data["branch_name"],
                        division=data["division"],
                        region=data["region"],
                        longitude=data["longitude"],
                        latitude=data["latitude"],
                        branch_size=data["branch_size"],
                        last_updated=timezone.now(),
                    ),
                )

        # Bulk update existing branches
        if branches_to_update:
            Branch.objects.bulk_update(
                branches_to_update,
                [
                    "branch_name",
                    "division",
                    "region",
                    "longitude",
                    "latitude",
                    "branch_size",
                    "last_updated",
                ],
            )

        # Bulk create new branches
        if branches_to_create:
            Branch.objects.bulk_create(branches_to_create, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS("Branch data loaded successfully!"))
