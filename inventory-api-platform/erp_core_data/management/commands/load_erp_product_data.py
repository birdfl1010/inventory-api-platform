import environ
import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from erp_core_data.models import BuyLine, PriceLine
from erp_core_data.utils.polars_snowflake_query_processor import execute_query_in_batches
from snowflake.connector import connect


def execute_batch_fixed(cur, sql, args_list, page_size=100):
    """
    Executes batched raw SQL statements for efficiency.
    """
    parts = []
    for args in args_list:
        qry = cur.mogrify(sql, args)
        if isinstance(qry, str):
            qry = qry.encode("utf8")
        parts.append(qry)
        if len(parts) >= page_size:
            cur.execute(b";".join(parts))
            parts = []
    if parts:
        cur.execute(b";".join(parts))


class Command(BaseCommand):
    """
    Efficiently load ERP Product data from Snowflake using raw SQL UPSERTs.
    """

    help = "Load ERP Product data using raw SQL UPSERT for performance"

    def handle(self, *args, **kwargs):
        # Load environment variables
        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        # Connect to Snowflake
        conn_sf = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
            disable_ocsp_checks=True,
        )

        # Load product data
        batch_size = 10000
        self.load_product_data(conn_sf, batch_size)
        self.stdout.write(self.style.SUCCESS("All Product data loaded successfully!"))

    def load_product_data(self, conn_sf, batch_size):
        """
        Queries Snowflake for product data and upserts it into the local DB.
        """
        self.stdout.write("Loading Product data...")

        query_sf = """
            SELECT
                PRODUCTID,
                PRODDESC,
                CATALOGNUMBER,
                VAP_FLAG,
                BUYLINEID,
                PRICELINEID,
                KEYWORDS,
                IMAGE_URL
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_PRODUCT
        """

        schema = {
            "PRODUCTID": pl.Int64,
            "PRODDESC": pl.Utf8,
            "CATALOGNUMBER": pl.Utf8,
            "VAP_FLAG": pl.Boolean,
            "BUYLINEID": pl.Utf8,
            "PRICELINEID": pl.Utf8,
            "KEYWORDS": pl.Utf8,
            "IMAGE_URL": pl.Utf8,
        }

        buy_lines = {bl.pk: bl.pk for bl in BuyLine.objects.all()}
        price_lines = {pl.pk: pl.pk for pl in PriceLine.objects.all()}
        total_processed = 0

        for df in execute_query_in_batches(conn_sf, query_sf, schema, batch_size=batch_size):
            current_time = timezone.now()
            rows = []

            for row in df.iter_rows(named=True):
                buy_line_id = buy_lines.get(row["BUYLINEID"])
                price_line_id = price_lines.get(row["PRICELINEID"])

                rows.append((
                    row["PRODUCTID"],
                    row["PRODDESC"],
                    row["CATALOGNUMBER"],
                    row["VAP_FLAG"],
                    buy_line_id,
                    price_line_id,
                    row["KEYWORDS"],
                    row["IMAGE_URL"],
                    current_time,
                ))

            if not rows:
                continue

            upsert_query = """
            INSERT INTO erp_core_data_product (
                product, product_desc, vendor_model, vap_flag,
                buy_line_id, price_line_id, search_key_words,
                image_url, last_updated
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (product) DO UPDATE SET
                product_desc = EXCLUDED.product_desc,
                vendor_model = EXCLUDED.vendor_model,
                vap_flag = EXCLUDED.vap_flag,
                buy_line_id = EXCLUDED.buy_line_id,
                price_line_id = EXCLUDED.price_line_id,
                search_key_words = EXCLUDED.search_key_words,
                image_url = EXCLUDED.image_url,
                last_updated = EXCLUDED.last_updated
            """

            with connection.cursor() as cursor:
                connection.connection.encoding = "UTF8"
                execute_batch_fixed(cursor, upsert_query, rows, page_size=1000)

            total_processed += len(rows)
            self.stdout.write(self.style.SUCCESS(f"Processed {total_processed} product records..."))

        self.stdout.write(self.style.SUCCESS("Product data load complete!"))
