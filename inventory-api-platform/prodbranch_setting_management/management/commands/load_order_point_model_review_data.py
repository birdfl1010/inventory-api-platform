import environ
from django.conf import settings
from django.core.management.base import BaseCommand
from erp_core_data.models import ProdBranch
from erp_core_data.utils.polars_snowflake_query_processor import (
    execute_query_in_batches,
)
from prodbranch_setting_management.models import OrderPointModelReview
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load Order Point Model Review data from Snowflake and
    update or create corresponding records in the local database.
    """

    help = "Load Order Point Model Review data from Snowflake."

    def handle(self, *args, **kwargs):
        # Load environment variables
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
        self.load_order_point_model_review(conn, batch_size)

        self.stdout.write(
            self.style.SUCCESS("Order Point Model Review data loaded successfully!"),
        )

    def load_order_point_model_review(self, conn, batch_size):
        """
        Loads order point model review data from Snowflake and updates or creates
        corresponding `OrderPointModelReview` entries in the local database.

        Args:
            conn: Snowflake connection.
            batch_size (int): Number of records to process per batch.
        """
        self.stdout.write("Loading Order Point Model Review data...")

        sql_query = """
            SELECT
                *
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_ORDER_POINT_MODEL
        """

        total_processed = 0

        for df in execute_query_in_batches(conn, sql_query, batch_size=batch_size):
            batch_count = 0

            for row in df.iter_rows(named=True):
                branch_id = row["BRANCHID"]
                product_id = row["PRODUCTID"]
                new_opm_flag = row["NEW_ORDER_POINT_MODEL_FLAG"]
                new_order_point = row["NEW_ORDERPOINT"]
                suggest_removal_flag = row["SUGGEST_MANUAL_SETTING_REMOVAL_FLAG"]
                removal_reason = row["MINIMUM_REMOVAL_REASON"]

                # Try to find the associated ProdBranch
                try:
                    prodbranch = ProdBranch.objects.get(
                        branch=branch_id,
                        product=product_id,
                    )
                except ProdBranch.DoesNotExist:
                    # Skip if matching ProdBranch does not exist
                    continue

                # Create or update the OrderPointModelReview record
                OrderPointModelReview.objects.update_or_create(
                    prodbranch=prodbranch,
                    defaults={
                        "new_order_point_model_flag": new_opm_flag,
                        "new_order_point": new_order_point,
                        "suggested_manual_setting_removal_flag": suggest_removal_flag,
                        "suggested_manual_setting_removal_reason": removal_reason,
                    },
                )

                batch_count += 1

            total_processed += batch_count
            self.stdout.write(
                self.style.SUCCESS(f"Processed {total_processed} records so far"),
            )
