from concurrent.futures import ThreadPoolExecutor

import environ
import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import YearMonth
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load YearMonth data from Snowflake
    and update/create records in the local database using bulk operations.
    """

    help = "Load YearMonth data from Snowflake"

    def handle(self, *args, **kwargs):
        self.stdout.write("Initializing YearMonth data load...")

        # Load environment variables for Snowflake credentials
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

        # Set batch size for processing
        batch_size = 5000
        self.load_yearmonth_data(conn, batch_size)

        conn.close()
        self.stdout.write(self.style.SUCCESS("YearMonth data loaded successfully!"))

    def load_yearmonth_data(self, conn, batch_size):
        """
        Loads YearMonth data from Snowflake and performs bulk updates or inserts.

        Args:
            conn: Snowflake database connection.
            batch_size (int): Number of records to process per batch.
        """
        self.stdout.write("Fetching YearMonth data from Snowflake...")

        yearmonth_sql_query = """
            SELECT YEAR, MONTH, TIMEINDEX
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_YEARMONTH
        """

        schema = {
            "YEAR": pl.Int64,
            "MONTH": pl.Int64,
            "TIMEINDEX": pl.Int64,
        }

        yearmonth_df = execute_query(conn, yearmonth_sql_query, schema=schema)
        self.stdout.write(f"Fetched {len(yearmonth_df)} records from Snowflake.")

        # Map data to dictionary keyed by (year, month)
        incoming_data = {
            (row["YEAR"], row["MONTH"]): row["TIMEINDEX"]
            for row in yearmonth_df.iter_rows(named=True)
        }

        self.stdout.write(f"Processing {len(incoming_data)} incoming records...")

        # Load existing YearMonth entries
        existing_yearmonths = YearMonth.objects.values_list("year", "month", "id")
        existing_yearmonths_dict = {
            (year, month): ym_id for year, month, ym_id in existing_yearmonths
        }

        self.stdout.write(f"Found {len(existing_yearmonths_dict)} existing records.")

        yearmonths_to_update = []
        yearmonths_to_create = []

        for (year, month), time_index in incoming_data.items():
            if (year, month) in existing_yearmonths_dict:
                yearmonths_to_update.append(
                    YearMonth(
                        id=existing_yearmonths_dict[(year, month)],
                        year=year,
                        month=month,
                        time_index=time_index,
                        last_updated=timezone.now(),
                    ),
                )
            else:
                yearmonths_to_create.append(
                    YearMonth(
                        year=year,
                        month=month,
                        time_index=time_index,
                        last_updated=timezone.now(),
                    ),
                )

        def process_in_chunks(items, action, action_name):
            """
            Processes a list of model instances in chunks using ThreadPoolExecutor.

            Args:
                items (list): The list of model instances.
                action (callable): A function to apply on each chunk.
                action_name (str): Descriptive name for progress logging.
            """
            total_items = len(items)
            with ThreadPoolExecutor() as executor:
                for i in range(0, total_items, batch_size):
                    chunk = items[i : i + batch_size]
                    executor.submit(action, chunk)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"{action_name} {i + len(chunk)} of {total_items} records",
                        ),
                    )

        # Perform bulk update
        if yearmonths_to_update:
            process_in_chunks(
                yearmonths_to_update,
                lambda chunk: YearMonth.objects.bulk_update(
                    chunk,
                    ["time_index", "last_updated"],
                ),
                "Updated",
            )

        # Perform bulk create
        if yearmonths_to_create:
            process_in_chunks(
                yearmonths_to_create,
                lambda chunk: YearMonth.objects.bulk_create(
                    chunk,
                    batch_size=batch_size,
                ),
                "Created",
            )

        self.stdout.write(self.style.SUCCESS("YearMonth data successfully updated!"))
