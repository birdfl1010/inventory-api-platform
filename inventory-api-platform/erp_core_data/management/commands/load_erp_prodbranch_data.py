# ruff: noqa: E501
import environ
import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from erp_core_data.models import Branch
from erp_core_data.models import Product
from erp_core_data.utils.polars_snowflake_query_processor import (
    execute_query_in_batches,
)
from snowflake.connector import connect


def execute_batch_fixed(cur, sql, args_list, page_size=100):
    """
    Helper function to mimic psycopg2.extras.execute_batch while ensuring
    all query parts are byte-encoded for execution.

    Args:
        cur: Database cursor.
        sql (str): SQL insert or upsert query.
        args_list (list): List of tuples representing row data.
        page_size (int): Number of rows per batch.
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
    Management command to load ERP ProdBranch data from Snowflake and
    perform raw SQL UPSERTs for efficient bulk updates and inserts.
    """

    help = "Load ERP Data for ProdBranch using raw SQL upsert for bulk update/insert"

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

        # Load ProdBranch data
        batch_size = 15000
        self.load_prodbranch_data(conn_sf, batch_size)
        self.stdout.write(
            self.style.SUCCESS("All ProdBranch data loaded successfully!"),
        )

    def load_prodbranch_data(self, conn_sf, batch_size):
        """
        Queries Snowflake for ProdBranch data, transforms it,
        and upserts it into the local database.

        Args:
            conn_sf: Snowflake connection.
            batch_size (int): Number of records to process per batch.
        """
        self.stdout.write("Loading ProdBranch data...")

        query_sf = """
            SELECT
                BRANCHID,
                PRODUCTID,
                STOCKFLAG1,
                LAST_STOCK_FLAG_CHANGE_DATE,
                RANK1,
                PURCHASINGBRANCH,
                AVERAGECOST,
                MONTHLYDEMAND,
                SALESSHIPBRANCHQTY30,
                SALESSHIPBRANCHQTY90,
                ORDERPOINT,
                LINEPOINT,
                MANUALMINIMUM,
                LAST_MANUAL_MINIMUM_CHANGE_DATE,
                MANUALMAXIMUM,
                LAST_MANUAL_MAXIMUM_CHANGE_DATE,
                BUYPACK,
                BUYPACKDIVISIBILITYFLAG
            FROM SANDBOX.DIGITALSOLUTIONS.SMS_PORTAL_PRODBRANCH
        """

        # Expected schema of the query results
        schema = {
            "BRANCHID": pl.Utf8,
            "PRODUCTID": pl.Int64,
            "STOCKFLAG1": pl.Boolean,
            "LAST_STOCK_FLAG_CHANGE_DATE": pl.Date,
            "RANK1": pl.Utf8,
            "PURCHASINGBRANCH": pl.Utf8,
            "AVERAGECOST": pl.Float64,
            "MONTHLYDEMAND": pl.Float64,
            "SALESSHIPBRANCHQTY30": pl.Int64,
            "SALESSHIPBRANCHQTY90": pl.Int64,
            "ORDERPOINT": pl.Int64,
            "LINEPOINT": pl.Int64,
            "MANUALMINIMUM": pl.Int64,
            "LAST_MANUAL_MINIMUM_CHANGE_DATE": pl.Date,
            "MANUALMAXIMUM": pl.Int64,
            "LAST_MANUAL_MAXIMUM_CHANGE_DATE": pl.Date,
            "BUYPACK": pl.Int64,
            "BUYPACKDIVISIBILITYFLAG": pl.Boolean
        }

        # Preload reference data for lookup
        branches = {b.branch: b for b in Branch.objects.all()}
        products = {p.product: p for p in Product.objects.all()}

        total_processed = 0

        for sf_df in execute_query_in_batches(
            conn_sf,
            query_sf,
            schema,
            batch_size=batch_size,
        ):
            # Compute calculated_manual_cost
            transformed_df = sf_df.with_columns(
                pl.max_horizontal(
                    [
                        pl.col("MANUALMINIMUM").fill_null(0) - pl.col("ORDERPOINT"),
                        pl.lit(0),
                    ],
                ).alias("diff"),
            ).with_columns(
                (pl.col("diff") * pl.col("AVERAGECOST")).alias(
                    "calculated_manual_cost",
                ),
            )

            # Filter out rows where required foreign keys are missing
            valid_df = transformed_df.filter(
                pl.col("BRANCHID").is_in(list(branches.keys()))
                & pl.col("PRODUCTID").is_in(list(products.keys())),
            )

            records = valid_df.to_dicts()
            current_time = timezone.now()

            values = []
            for rec in records:
                branch_inst = branches.get(rec["BRANCHID"])
                product_inst = products.get(rec["PRODUCTID"])
                if not branch_inst or not product_inst:
                    continue

                purchasing_branch_inst = branches.get(rec["PURCHASINGBRANCH"])
                purchasing_branch_id = (
                    purchasing_branch_inst.pk if purchasing_branch_inst else None
                )

                values.append(
                    (
                        branch_inst.pk,
                        product_inst.pk,
                        rec["STOCKFLAG1"],
                        rec["LAST_STOCK_FLAG_CHANGE_DATE"],
                        rec["RANK1"],
                        purchasing_branch_id,
                        rec["AVERAGECOST"],
                        rec["MONTHLYDEMAND"],
                        rec["SALESSHIPBRANCHQTY30"],
                        rec["SALESSHIPBRANCHQTY90"],
                        rec["ORDERPOINT"],
                        rec["LINEPOINT"],
                        rec["MANUALMINIMUM"],
                        rec["LAST_MANUAL_MINIMUM_CHANGE_DATE"],
                        rec["MANUALMAXIMUM"],
                        rec["LAST_MANUAL_MAXIMUM_CHANGE_DATE"],
                        rec["calculated_manual_cost"],
                        rec["BUYPACK"],
                        rec["BUYPACKDIVISIBILITYFLAG"],
                        current_time,
                    ),
                )

            if not values:
                continue

            # SQL upsert (PostgreSQL ON CONFLICT clause)
            upsert_query = """
            INSERT INTO erp_core_data_prodbranch (
                branch_id, product_id, stock_flag_binary,
                last_stock_flag_change_date, rank,
                purchasing_branch_id, average_cost, monthly_demand,
                sales_qty_30, sales_qty_90, order_point, line_point,
                manual_minimum, last_manual_minimum_change_date,
                manual_maximum, last_manual_maximum_change_date,
                calculated_manual_cost, buy_pack_qty, buy_pack_divisibility_flag,
                last_updated
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (branch_id, product_id)
            DO UPDATE SET
                stock_flag_binary = EXCLUDED.stock_flag_binary,
                last_stock_flag_change_date = EXCLUDED.last_stock_flag_change_date,
                rank = EXCLUDED.rank,
                purchasing_branch_id = EXCLUDED.purchasing_branch_id,
                average_cost = EXCLUDED.average_cost,
                monthly_demand = EXCLUDED.monthly_demand,
                sales_qty_30 = EXCLUDED.sales_qty_30,
                sales_qty_90 = EXCLUDED.sales_qty_90,
                order_point = EXCLUDED.order_point,
                line_point = EXCLUDED.line_point,
                manual_minimum = EXCLUDED.manual_minimum,
                last_manual_minimum_change_date = EXCLUDED.last_manual_minimum_change_date,
                manual_maximum = EXCLUDED.manual_maximum,
                last_manual_maximum_change_date = EXCLUDED.last_manual_maximum_change_date,
                calculated_manual_cost = EXCLUDED.calculated_manual_cost,
                buy_pack_qty =  EXCLUDED.buy_pack_qty,
                buy_pack_divisibility_flag =  EXCLUDED.buy_pack_divisibility_flag,
                last_updated = EXCLUDED.last_updated
            """

            # Execute the upsert in batches using raw SQL
            with connection.cursor() as cursor:
                real_conn = cursor.connection
                real_conn.encoding = "UTF8"
                execute_batch_fixed(cursor, upsert_query, values, page_size=1000)

            total_processed += len(values)
            self.stdout.write(
                self.style.SUCCESS(f"Processed {total_processed} records so far..."),
            )

        self.stdout.write(self.style.SUCCESS("ProdBranch data load complete!"))
