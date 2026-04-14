from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


class Command(BaseCommand):
    """
    Management command to sequentially run all ERP data loading commands
    in the correct dependency order.
    """

    help = "Runs all ERP data loading commands in the correct order."

    def handle(self, *args, **options):
        # List of commands to execute in the correct order
        commands = [
            "load_branch_size_data",
            "load_erp_region_data",
            "load_erp_branch_data",
            "load_erp_buy_line_data",
            "load_erp_price_line_data",
            "load_erp_product_data",
            "load_erp_prodbranch_data",
            # below commands removed as data is unused
            # "load_erp_year_month_data", 
            # "load_erp_prodbranch_sales_history_data",
        ]

        for command in commands:
            self.stdout.write(f"Running command: {command}")
            try:
                # Execute each command
                call_command(command)
                self.stdout.write(self.style.SUCCESS(f"Successfully ran: {command}"))
            except CommandError as e:
                # Log the error and halt execution if any command fails
                self.stderr.write(self.style.ERROR(f"Failed to run {command}: {e}"))
                break
