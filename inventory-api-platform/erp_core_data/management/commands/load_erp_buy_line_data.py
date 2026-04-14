from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import BuyLine
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load ERP buy line data from Snowflake
    into the local BuyLine model with support for bulk updates and inserts.
    """

    help = "Load ERP Data to use as Core Data"

    def handle(self, *args, **kwargs):
        # Load environment variables
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

        # Execute data load
        self.load_buy_line_data(conn, batch_size)

        self.stdout.write(self.style.SUCCESS("All data loaded successfully!"))

    def load_buy_line_data(self, conn, batch_size):
        """
        Loads buy line data from Snowflake and synchronizes it with the local database.

        Args:
            conn: Active Snowflake connection.
            batch_size (int): Number of records to insert per batch during bulk_create.
        """
        self.stdout.write("Loading buy line data...")

        # SQL query to fetch buy line data
        buy_line_sql_query = "SELECT * FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_BUYLINE"
        buy_line_df = execute_query(conn, buy_line_sql_query)

        # Prepare incoming data as a dictionary
        incoming_data = {
            row["BUYLINEID"]: {"buy_line_name": row["DESCRIPTION"]}
            for row in buy_line_df.iter_rows(named=True)
        }

        # Retrieve existing records to determine updates
        existing_buy_lines = BuyLine.objects.filter(buy_line__in=incoming_data.keys())
        existing_buy_lines_dict = {bl.buy_line: bl for bl in existing_buy_lines}

        buy_lines_to_update = []
        buy_lines_to_create = []

        for buy_line_id, data in incoming_data.items():
            if buy_line_id in existing_buy_lines_dict:
                # Update existing record
                buy_line = existing_buy_lines_dict[buy_line_id]
                buy_line.buy_line_name = data["buy_line_name"]
                buy_line.last_updated = timezone.now()
                buy_lines_to_update.append(buy_line)
            else:
                # Create new record
                buy_lines_to_create.append(
                    BuyLine(
                        buy_line=buy_line_id,
                        buy_line_name=data["buy_line_name"],
                        last_updated=timezone.now(),
                    ),
                )

        # Apply updates and inserts in bulk
        if buy_lines_to_update:
            BuyLine.objects.bulk_update(
                buy_lines_to_update,
                ["buy_line_name", "last_updated"],
            )

        if buy_lines_to_create:
            BuyLine.objects.bulk_create(buy_lines_to_create, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS("Buy line data loaded successfully!"))
