import csv
from datetime import date
from io import StringIO

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from prodbranch_setting_management.models import ProdBranchChange


class Command(BaseCommand):
    help = "Export ProdBranchChange data as CSVs to public S3 bucket."

    def handle(self, *args, **options):
        # 1. S3 basics
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        s3 = boto3.client("s3")

        base_path = "exports/prodbranch_changes"
        public_url_base = f"https://{bucket_name}.s3.amazonaws.com/{base_path}"

        # add buy_packs filename
        filenames = {
            "stock_flags": f"{base_path}/prod_branch_stock_flags.csv",
            "minimums": f"{base_path}/prod_branch_minimums.csv",
            "maximums": f"{base_path}/prod_branch_maximums.csv",
            "buy_packs": f"{base_path}/prod_branch_buy_packs.csv",
        }

        # 2. Column structure
        columns = [
            "Eclipse Product ID", "Branch", "Min", "Max", "Min/Max Expiration",
            "Buy Pkg", "Buy Package Divisibility Flag (Y, N, Blank) = (1, 0, Blank)",
            "Branch Stock Flag        (Y, N, Auto) = (1, 0, -)", "Service Stock",
            "Lead Time Override", "LTO Expiration Date", "EOQ $", "EOQ %",
            "Saftey Factor", "Trend %", "Rank 1", "Rank 2", "Serial #?",
            "Requesting Team (Merch, Supply Chain, RVP, Branch)",
            "Requester (First & Last Name)", "Reason (VAP Rollout, Data Corrections, Stock Range Adjustments, etc..)",
            "Comment (Optional Context)",
        ]

        # 3. Query relevant change records
        recent = ProdBranchChange.objects.filter(last_updated__gt=date(2025, 4, 10))
        stockflag_qs = recent.filter(stockflag_change__isnull=False)
        minimum_qs = recent.filter(manual_minimum_change__isnull=False)
        maximum_qs = recent.filter(manual_maximum_change__isnull=False)

        # use Q() to OR the two conditions properly
        buy_pack_qs = recent.filter(
            Q(buy_pack_change__isnull=False)
            | Q(buy_pack_divisibility_change__isnull=False)
        )

        # 4. Row template
        def build_base_row(obj):
            row = [""] * len(columns)
            row[0] = getattr(obj.prodbranch.product, "product", "")
            row[1] = getattr(obj.prodbranch.branch, "branch", "")
            row[20] = "SMS Portal Upload"
            return row

        # 5. In-memory CSV -> S3 upload
        def upload_csv_to_s3(filename, queryset, row_mutator):
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(columns)

            for obj in queryset:
                row = build_base_row(obj)
                row_mutator(row, obj)
                writer.writerow(row)

            buffer.seek(0)
            s3.put_object(
                Bucket=bucket_name,
                Key=filename,
                Body=buffer.getvalue(),
                ContentType="text/csv",
                # ACL="public-read",
            )
            buffer.close()
            return f"{public_url_base}/{filename.split('/')[-1]}"

        # 6. Process and upload each file
        urls = {}

        urls["stock_flags"] = upload_csv_to_s3(
            filenames["stock_flags"],
            stockflag_qs,
            lambda row, obj: row.__setitem__(7, "-" if obj.stockflag_change else "0"),
        )

        urls["minimums"] = upload_csv_to_s3(
            filenames["minimums"],
            minimum_qs,
            lambda row, obj: row.__setitem__(2, "" if obj.manual_minimum_change == 0 else str(obj.manual_minimum_change)),
        )

        urls["maximums"] = upload_csv_to_s3(
            filenames["maximums"],
            maximum_qs,
            lambda row, obj: row.__setitem__(3, "" if obj.manual_maximum_change == 0 else str(obj.manual_maximum_change)),
        )

        # single mutator that handles both buy_pack_change and buy_pack_divisibility_change
        def mutate_buy_pack(row, obj):
            # Buy Pkg
            row[5] = "" if obj.buy_pack_change in (None, 0) else str(obj.buy_pack_change)
            # Divisibility Flag: Blank if None, "Y" if truthy, "N" otherwise
            flag = obj.buy_pack_divisibility_change
            if flag is None:
                row[6] = ""
            else:
                row[6] = "Y" if flag else "N"

        urls["buy_packs"] = upload_csv_to_s3(
            filenames["buy_packs"],
            buy_pack_qs,
            mutate_buy_pack,
        )

        # 7. Display results
        self.stdout.write(self.style.SUCCESS("CSV files uploaded to S3:"))
        for name, url in urls.items():
            self.stdout.write(f" - {name}: {url}")
