import os
import secrets

import environ
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

# Import your Branch model; adjust the path as needed.
from erp_core_data.models import Branch
from erp_core_data.utils.polars_snowflake_query_processor import (
    execute_query_in_batches,
)
from snowflake.connector import connect

# Import your UserBranchAccess model; adjust the path as needed.
from inventory_stock_management.users.models import UserBranchAccess


class Command(BaseCommand):
    help = "Load Users and UserBranch access data from Snowflake and write passwords to a file."

    def handle(self, *args, **kwargs):
        env = environ.Env()
        if env.bool("DJANGO_READ_DOT_ENV_FILE", default=False):
            env.read_env(settings.BASE_DIR / ".env")

        # Establish Snowflake connection using credentials from your environment.
        conn = connect(
            user=env("SNOWFLAKE_USER"),
            password=env("SNOWFLAKE_PASS"),
            account=env("SNOWFLAKE_ACC_ID"),
            role=env("SNOWFLAKE_ROLE"),
        )

        batch_size = 5000

        # Load user data and collect generated passwords.
        user_passwords = self.load_users(conn, batch_size)
        # Load the user-branch access records.
        self.load_userbranch_access(conn, batch_size)

        # Write the generated passwords to a file in BASE_DIR.
        file_path = os.path.join(settings.BASE_DIR, "_temp_test_user_passwords.txt")
        with open(file_path, "w") as f:
            for username, pwd in user_passwords.items():
                f.write(f"{username}: {pwd}\n")
        self.stdout.write(self.style.SUCCESS(f"Passwords written to {file_path}"))
        self.stdout.write(
            self.style.SUCCESS("User and UserBranch data loaded successfully!"),
        )

    def load_users(self, conn, batch_size):
        self.stdout.write("Loading user data...")

        # SQL query for User data
        user_sql_query = """
            SELECT DISTINCT
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_user' as USERID,
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_user' as First_Name,
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_user' as Last_name,
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_user@inventory.com' as Email,
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_password123!' as Password
            FROM SANDBOX.SUPPLYCHAIN.REGION_VIEW
            WHERE DIVISION IN ('Plumbing', 'HVAC')

            UNION ALL

            SELECT
                'branch_' || BranchID || '_user' as USERID,
                'branch_' || BranchID || '_user' as First_Name,
                'branch_' || BranchID || '_user' as Last_Name,
                'branch_' || BranchID || '_user@inventory.com' as Email,
                'branch_' || BranchID || '_password123!' as Password
            FROM SANDBOX.SUPPLYCHAIN.REGION_VIEW
            WHERE BranchID IN (
                '1008', '1009', '1012', '1020', '1023', '1030', '1043', '1049',
                '1057', '1086', '1111', '1153', '1310', '1401', '1504', '2002',
                '2010', '2018', '2024', '3007', '3018', '4001', '5003'
            );
        """

        User = get_user_model()
        # Dictionary to store the generated passwords (username => password)
        generated_passwords = {}

        # Process the query results in batches.
        for user_df in execute_query_in_batches(
            conn,
            user_sql_query,
            batch_size=batch_size,
        ):
            for row in user_df.iter_rows(named=True):
                username = row["USERID"]
                first_name = row["FIRST_NAME"]
                last_name = row["LAST_NAME"]
                email = row["EMAIL"]

                # Generate a random password for this user.
                new_password = secrets.token_urlsafe(12)
                generated_passwords[username] = new_password

                try:
                    # Update existing user.
                    user_obj = User.objects.get(username=username)
                    user_obj.first_name = first_name
                    user_obj.last_name = last_name
                    user_obj.email = email
                    user_obj.set_password(new_password)
                    user_obj.save()
                    self.stdout.write(f"Updated user {username}")
                except User.DoesNotExist:
                    # Create a new user.
                    user_obj = User.objects.create_user(
                        username=username,
                        email=email,
                        password=new_password,
                    )
                    user_obj.first_name = first_name
                    user_obj.last_name = last_name
                    user_obj.save()
                    self.stdout.write(f"Created user {username}")

        return generated_passwords

    def load_userbranch_access(self, conn, batch_size):
        self.stdout.write("Loading user branch access data...")

        # SQL query for UserBranch access data.
        userbranch_sql_query = """
            SELECT
                LOWER(REPLACE(REPLACE(RegionName, ' ', '_'), '/', '_')) || '_user' as USERID,
                BranchID as accessible_branches
            FROM SANDBOX.SUPPLYCHAIN.REGION_VIEW
            WHERE DIVISION IN ('Plumbing', 'HVAC')

            UNION ALL

            SELECT
                'branch_' || BranchID || '_user' as USERID,
                BranchID as accessible_branches
            FROM SANDBOX.SUPPLYCHAIN.REGION_VIEW
            WHERE BranchID IN (
                '1008', '1009', '1012', '1020', '1023', '1030', '1043', '1049',
                '1057', '1086', '1111', '1153', '1310', '1401', '1504', '2002',
                '2010', '2018', '2024', '3007', '3018', '4001', '5003'
            )
        """

        User = get_user_model()

        # Process each row from the query result.
        for ub_df in execute_query_in_batches(
            conn,
            userbranch_sql_query,
            batch_size=batch_size,
        ):
            for row in ub_df.iter_rows(named=True):
                username = row["USERID"]
                branch_id = row["ACCESSIBLE_BRANCHES"]

                try:
                    user_obj = User.objects.get(username=username)
                except User.DoesNotExist:
                    self.stdout.write(
                        f"User {username} does not exist; skipping branch access.",
                    )
                    continue

                try:
                    # Adjust the lookup below based on your Branch model's field names.
                    branch_obj = Branch.objects.get(branch=branch_id)
                except Branch.DoesNotExist:
                    self.stdout.write(
                        f"Branch {branch_id} does not exist; skipping for user {username}.",
                    )
                    continue

                # Create the UserBranchAccess record if it doesn't already exist.
                uba, created = UserBranchAccess.objects.get_or_create(
                    user=user_obj,
                    branch=branch_obj,
                )
                if created:
                    self.stdout.write(
                        f"Created branch access for user {username} to branch {branch_id}",
                    )
                else:
                    self.stdout.write(
                        f"Branch access already exists for user {username} to branch {branch_id}",
                    )
