import csv
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q
from prodbranch_setting_management.models import ProdBranchChange

class Command(BaseCommand):
    help = "Export ProdBranchChange data into three different CSV files."

    def handle(self, *args, **options):
        # ---------------------------------------------------------------------
        # 1) Define the columns (22 columns total).
        # ---------------------------------------------------------------------
        columns = [
            "Eclipse Product ID",
            "Branch",
            "Min",
            "Max",
            "Min/Max Expiration",
            "Buy Pkg",
            "Buy Package Divisibility Flag (Y, N, Blank) = (1, 0, Blank)",
            "Branch Stock Flag        (Y, N, Auto) = (1, 0, -)",
            "Service Stock",
            "Lead Time Override",
            "LTO Expiration Date",
            "EOQ $",
            "EOQ %",
            "Saftey Factor",
            "Trend %",
            "Rank 1",
            "Rank 2",
            "Serial #?",
            "Requesting Team (Merch, Supply Chain, RVP, Branch)",
            "Requester (First & Last Name)",
            "Reason (VAP Rollout, Data Corrections, Stock Range Adjustments, etc..)",
            "Comment (Optional Context)",
        ]

        # ---------------------------------------------------------------------
        # 2) Prepare output file paths
        # ---------------------------------------------------------------------
        stock_flags_path = "/app/output/prod_branch_stock_flags.csv"
        min_path         = "/app/output/prod_branch_minimums.csv"
        max_path         = "/app/output/prod_branch_maximums.csv"

        # ---------------------------------------------------------------------
        # 3) Querysets for each file
        #    Note: We only export rows if the relevant field is not None.
        # ---------------------------------------------------------------------
        filtered_prodbranches = ProdBranchChange.objects.filter(last_updated__gt=date(2025, 4, 10))

        stockflag_qs = filtered_prodbranches.filter(stockflag_change__isnull=False)
        minimum_qs   = filtered_prodbranches.filter(manual_minimum_change__isnull=False)
        maximum_qs   = filtered_prodbranches.filter(manual_maximum_change__isnull=False)

        # ---------------------------------------------------------------------
        # 4) Helper function to build a row of 22 columns, filling the columns
        #    that apply for each file and leaving the rest blank.
        # ---------------------------------------------------------------------
        def build_base_row(obj):
            """
            Returns a list of 22 items in the correct column order, mostly blanks,
            but with Product ID, Branch, and Reason filled in. This is a template
            we can customize for each file type.
            """
            base_row = [""] * len(columns)

            # Fill in the basics for every file
            # Column indices based on 'columns' list above:
            #  0: Eclipse Product ID
            #  1: Branch
            # 20: Reason
            base_row[0] = getattr(obj.prodbranch.product, "product", "")  # Eclipse Product ID
            base_row[1] = getattr(obj.prodbranch.branch, "branch", "")    # Branch
            base_row[20] = "SMS Portal Upload"                            # Reason

            return base_row

        # ---------------------------------------------------------------------
        # 5) Generate "prod_branch_stock_flags.csv"
        #    For each record in stockflag_qs, fill the Branch Stock Flag column
        #    (index 7). Per instructions:
        #       - If True -> "-"
        #       - If False -> "0"
        # ---------------------------------------------------------------------
        with open(stock_flags_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(columns)  # Header

            for obj in stockflag_qs:
                row = build_base_row(obj)

                # Fill the Branch Stock Flag column (index 7)
                if obj.stockflag_change is True:
                    row[7] = "-"
                elif obj.stockflag_change is False:
                    row[7] = "0"
                else:
                    row[7] = ""  # If it's neither True nor False

                writer.writerow(row)

        # ---------------------------------------------------------------------
        # 6) Generate "prod_branch_minimums.csv"
        #    For each record in minimum_qs, fill the Min column (index 2).
        #    If the value is zero, leave the field blank.
        # ---------------------------------------------------------------------
        with open(min_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(columns)  # Header

            for obj in minimum_qs:
                row = build_base_row(obj)

                # Fill the Min column (index 2), blank if zero
                min_val = obj.manual_minimum_change
                if min_val == 0:
                    row[2] = ""
                else:
                    row[2] = str(min_val)

                writer.writerow(row)

        # ---------------------------------------------------------------------
        # 7) Generate "prod_branch_maximums.csv"
        #    For each record in maximum_qs, fill the Max column (index 3).
        #    If the value is zero, leave the field blank.
        # ---------------------------------------------------------------------
        with open(max_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(columns)  # Header

            for obj in maximum_qs:
                row = build_base_row(obj)

                # Fill the Max column (index 3), blank if zero
                max_val = obj.manual_maximum_change
                if max_val == 0:
                    row[3] = ""
                else:
                    row[3] = str(max_val)

                writer.writerow(row)

        # ---------------------------------------------------------------------
        # 8) Let the user know we are done
        # ---------------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS(
            "Successfully exported to:\n"
            f"  {stock_flags_path}\n"
            f"  {min_path}\n"
            f"  {max_path}"
        ))
