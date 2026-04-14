from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from erp_core_data.models import Region
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load ERP region data from Snowflake and sync it
    with the Region model using bulk update and insert operations.
    """

    help = "Load ERP Data to use as Core Data"

    def handle(self, *args, **kwargs):
        # Load environment variables for Snowflake credentials
        import environ
        from django.conf import settings

        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        # Establish Snowflake connection
        conn = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
            disable_ocsp_checks=True,
        )

        # Set batch size for database operations
        batch_size = 999

        # Load and process region data
        self.load_region_data(conn, batch_size)

        self.stdout.write(self.style.SUCCESS("All data loaded successfully!"))

    def load_region_data(self, conn, batch_size):
        """
        Loads region data from Snowflake and performs bulk updates and inserts.

        Args:
            conn: Snowflake database connection.
            batch_size (int): Number of records to insert per batch.
        """
        self.stdout.write("Loading region data...")

        region_sql_query = """
            SELECT DISTINCT REGIONID, REGIONNAME
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_REGION_VIEW
        """
        region_df = execute_query(conn, region_sql_query)

        # Transform fetched data into a dictionary keyed by REGIONID
        incoming_data = {
            row["REGIONID"]: row for row in region_df.iter_rows(named=True)
        }

        # Fetch existing Region records to compare and update
        existing_regions = Region.objects.filter(id__in=incoming_data.keys())
        existing_regions_dict = {region.id: region for region in existing_regions}

        regions_to_update = []
        regions_to_create = []

        for region_id, row in incoming_data.items():
            region_name = row["REGIONNAME"]
            if region_id in existing_regions_dict:
                # Update fields for existing records
                region = existing_regions_dict[region_id]
                region.name = region_name
                region.slug = slugify(region_name)
                region.last_updated = timezone.now()
                regions_to_update.append(region)
            else:
                # Prepare new records for creation
                regions_to_create.append(
                    Region(
                        id=region_id,
                        name=region_name,
                        slug=slugify(region_name),
                        last_updated=timezone.now(),
                    ),
                )

        # Bulk update and create
        if regions_to_update:
            Region.objects.bulk_update(
                regions_to_update,
                ["name", "slug", "last_updated"],
            )

        if regions_to_create:
            Region.objects.bulk_create(regions_to_create, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS("Region data loaded successfully!"))
