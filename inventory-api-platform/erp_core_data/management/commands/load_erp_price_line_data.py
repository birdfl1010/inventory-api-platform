from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import PriceLine
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load ERP price line data from Snowflake
    into the local PriceLine model, handling both updates and inserts.
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

        # Batch size for bulk operations
        batch_size = 999

        # Load price line data
        self.load_price_line_data(conn, batch_size)

        self.stdout.write(self.style.SUCCESS("All data loaded successfully!"))

    def load_price_line_data(self, conn, batch_size):
        """
        Loads price line data from Snowflake and syncs it with the local database.

        Args:
            conn: Active Snowflake connection.
            batch_size (int): Number of records per batch for bulk_create.
        """
        self.stdout.write("Loading price line data...")

        # SQL query to retrieve price line data
        price_line_sql_query = (
            "SELECT * FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_PRICELINE"
        )
        price_line_df = execute_query(conn, price_line_sql_query)

        # Parse Snowflake results into a dict keyed by price line ID
        incoming_data = {
            row["PRICELINEID"]: {"price_line_name": row["DESCRIPTION"]}
            for row in price_line_df.iter_rows(named=True)
        }

        # Retrieve existing records for differential updates
        existing_price_lines = PriceLine.objects.filter(
            price_line__in=incoming_data.keys(),
        )
        existing_price_lines_dict = {pl.price_line: pl for pl in existing_price_lines}

        price_lines_to_update = []
        price_lines_to_create = []

        for price_line_id, data in incoming_data.items():
            if price_line_id in existing_price_lines_dict:
                # Update existing record
                price_line = existing_price_lines_dict[price_line_id]
                price_line.price_line_name = data["price_line_name"]
                price_line.last_updated = timezone.now()
                price_lines_to_update.append(price_line)
            else:
                # Prepare new record for creation
                price_lines_to_create.append(
                    PriceLine(
                        price_line=price_line_id,
                        price_line_name=data["price_line_name"],
                        last_updated=timezone.now(),
                    ),
                )

        # Apply updates and inserts
        if price_lines_to_update:
            PriceLine.objects.bulk_update(
                price_lines_to_update,
                ["price_line_name", "last_updated"],
            )

        if price_lines_to_create:
            PriceLine.objects.bulk_create(price_lines_to_create, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS("Price line data loaded successfully!"))
