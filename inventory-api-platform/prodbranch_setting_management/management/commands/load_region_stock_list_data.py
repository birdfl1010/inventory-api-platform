from django.core.management.base import BaseCommand
from django.utils import timezone
from erp_core_data.models import Product
from erp_core_data.models import Region
from erp_core_data.utils.polars_snowflake_query_processor import execute_query
from prodbranch_setting_management.models import RegionProductStockingList
from snowflake.connector import connect


class Command(BaseCommand):
    """
    Management command to load Region Product Stocking List data from Snowflake
    and synchronize with the RegionProductStockingList model.
    """

    help = "Load Region Stock List Data from Snowflake"

    def handle(self, *args, **kwargs):
        # Set up Snowflake connection.
        import environ
        from django.conf import settings

        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        conn = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
            disable_ocsp_checks=True,
        )

        batch_size = 999
        self.load_region_stock_list_data(conn, batch_size)

        self.stdout.write(
            self.style.SUCCESS("Region Stock List data loaded successfully!"),
        )

    def load_region_stock_list_data(self, conn, batch_size):
        """
        Fetches Region-Product relationships from Snowflake and ensures they
        are reflected in the RegionProductStockingList table.

        Args:
            conn: Active Snowflake connection.
            batch_size (int): Number of records to insert per batch.
        """
        self.stdout.write("Loading region stock list data...")

        query = """
            SELECT DISTINCT
                r.RegionID,
                INITCAP(r.RegionName) as RegionName,
                rsl.productid
            FROM SANDBOX.SUPPLYCHAIN.REGION_STOCK_LISTS rsl
            LEFT OUTER JOIN SANDBOX.SUPPLYCHAIN.REGION_VIEW r
                ON INITCAP(rsl.RegionName) = r.RegionName
        """
        region_stock_list_df = execute_query(conn, query)

        incoming_rows = []
        region_ids = set()
        product_ids = set()

        # Collect all incoming region-product references
        for row in region_stock_list_df.iter_rows(named=True):
            region_id = row["REGIONID"]
            product_id = row["PRODUCTID"]
            incoming_rows.append({"region_id": region_id, "product_id": product_id})
            region_ids.add(region_id)
            product_ids.add(product_id)

        # Pre-fetch Regions and Products for lookup
        regions_lookup = {r.id: r for r in Region.objects.filter(id__in=region_ids)}
        products_lookup = {
            p.product: p for p in Product.objects.filter(product__in=product_ids)
        }

        # Build incoming key mappings
        incoming_dict = {}
        for row in incoming_rows:
            region = regions_lookup.get(row["region_id"])
            product = products_lookup.get(int(row["product_id"]))
            if region and product:
                incoming_dict[(region.pk, product.pk)] = {
                    "region": region,
                    "product": product,
                }
            else:
                if not region:
                    self.stdout.write(
                        self.style.WARNING(f"Region not found: {row['region_id']}"),
                    )
                if not product:
                    self.stdout.write(
                        self.style.WARNING(f"Product not found: {row['product_id']}"),
                    )

        # Query for existing RSL records matching these combinations
        existing_rsl_qs = RegionProductStockingList.objects.filter(
            region__id__in=region_ids,
            product__in=product_ids,
        )
        existing_rsl_dict = {
            (rsl.region.pk, rsl.product.pk): rsl for rsl in existing_rsl_qs
        }

        regions_to_update = []
        regions_to_create = []
        now = timezone.now()

        # Determine which records to update or create
        for key, data in incoming_dict.items():
            if key in existing_rsl_dict:
                rsl_instance = existing_rsl_dict[key]
                rsl_instance.last_updated = now
                regions_to_update.append(rsl_instance)
            else:
                new_rsl = RegionProductStockingList(
                    region=data["region"],
                    product=data["product"],
                    initial_stock_quantity=None,
                    last_updated=now,
                )
                regions_to_create.append(new_rsl)

        # Apply bulk updates and creates
        if regions_to_update:
            RegionProductStockingList.objects.bulk_update(
                regions_to_update,
                ["last_updated"],
            )

        if regions_to_create:
            RegionProductStockingList.objects.bulk_create(
                regions_to_create,
                batch_size=batch_size,
            )

        self.stdout.write(
            self.style.SUCCESS("Region stock list data loaded successfully!"),
        )
