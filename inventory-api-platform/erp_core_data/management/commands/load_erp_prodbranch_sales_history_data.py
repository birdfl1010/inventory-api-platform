from concurrent.futures import ThreadPoolExecutor

import environ
import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import Branch
from erp_core_data.models import Product
from erp_core_data.models import Sales
from erp_core_data.models import YearMonth
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load sales data from Snowflake and synchronize it with
    the local database using bulk update and create operations.
    """

    help = "Load Sales data from Snowflake"

    def handle(self, *args, **kwargs):
        self.stdout.write("Initializing Sales data load...")

        # Load environment variables for Snowflake credentials
        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        # Connect to Snowflake
        conn = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
            disable_ocsp_checks=True,
        )

        # Set batch size for bulk operations
        batch_size = 5000
        self.load_sales_data(conn, batch_size)

        conn.close()
        self.stdout.write(self.style.SUCCESS("Sales data loaded successfully!"))

    def load_sales_data(self, conn, batch_size):
        """
        Queries Snowflake for sales data and applies bulk
        updates/inserts to the database.

        Args:
            conn: Active Snowflake connection.
            batch_size (int): Number of records to process per batch.
        """
        self.stdout.write("Fetching Sales data from Snowflake...")

        sales_sql_query = """
            SELECT BranchID, ProductID, Year, Month, branch_sales_qty
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_PRODBRANCH_SALES
        """

        schema = {
            "BranchID": pl.Utf8,
            "ProductID": pl.Int64,
            "Year": pl.Int64,
            "Month": pl.Int64,
            "branch_sales_qty": pl.Int64,
        }

        sales_df = execute_query(conn, sales_sql_query, schema=schema)
        self.stdout.write(f"Fetched {len(sales_df)} records from Snowflake.")

        # Map raw rows to a dictionary keyed by (BranchID, ProductID, Year, Month)
        incoming_data = {
            (row["BranchID"], row["ProductID"], row["Year"], row["Month"]): row[
                "branch_sales_qty"
            ]
            for row in sales_df.iter_rows(named=True)
        }

        self.stdout.write(f"Processing {len(incoming_data)} incoming records...")

        # Retrieve existing Sales records for identification of updates
        existing_sales = Sales.objects.values_list(
            "branch__branch",
            "product__product",
            "year_month__year",
            "year_month__month",
            "id",
        )
        existing_sales_dict = {
            (branch, product, year, month): sale_id
            for branch, product, year, month, sale_id in existing_sales
        }

        self.stdout.write(f"Found {len(existing_sales_dict)} existing records.")

        # Preload related models for efficient lookups
        branch_instances = {b.branch: b for b in Branch.objects.all()}
        product_instances = {p.product: p for p in Product.objects.all()}
        yearmonth_instances = {
            (ym.year, ym.month): ym for ym in YearMonth.objects.all()
        }

        sales_to_update = []
        sales_to_create = []

        for (branch_id, product_id, year, month), quantity in incoming_data.items():
            branch_instance = branch_instances.get(branch_id)
            product_instance = product_instances.get(product_id)
            yearmonth_instance = yearmonth_instances.get((year, month))

            if not branch_instance or not product_instance or not yearmonth_instance:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping missing branch {branch_id}, "
                        f"product {product_id}, or year/month {year}-{month}",
                    ),
                )
                continue

            if (branch_id, product_id, year, month) in existing_sales_dict:
                sales_to_update.append(
                    Sales(
                        id=existing_sales_dict[(branch_id, product_id, year, month)],
                        branch=branch_instance,
                        product=product_instance,
                        year_month=yearmonth_instance,
                        quantity=quantity,
                        last_updated=timezone.now(),
                    ),
                )
            else:
                sales_to_create.append(
                    Sales(
                        branch=branch_instance,
                        product=product_instance,
                        year_month=yearmonth_instance,
                        quantity=quantity,
                        last_updated=timezone.now(),
                    ),
                )

        def process_in_chunks(items, action, action_name):
            """
            Helper function to process items in parallel chunks.

            Args:
                items (list): List of model instances.
                action (callable): Function to execute on each chunk.
                action_name (str): Descriptive name for logging progress.
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

        # Apply bulk updates
        if sales_to_update:
            process_in_chunks(
                sales_to_update,
                lambda chunk: Sales.objects.bulk_update(
                    chunk,
                    ["quantity", "last_updated"],
                ),
                "Updated",
            )

        # Apply bulk inserts
        if sales_to_create:
            process_in_chunks(
                sales_to_create,
                lambda chunk: Sales.objects.bulk_create(chunk, batch_size=batch_size),
                "Created",
            )

        self.stdout.write(self.style.SUCCESS("Sales data successfully updated!"))
