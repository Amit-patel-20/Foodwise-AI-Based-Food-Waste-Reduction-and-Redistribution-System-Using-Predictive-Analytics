import csv
import random
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from django.utils.timezone import now

from core.models import DailyFoodRecord

CSV_ITEM_COLUMNS = (
    ("Dal", "dal_added", "dal_sold"),
    ("Chawal", "chawal_added", "chawal_sold"),
    ("Sabji", "sabji_added", "sabji_sold"),
)
SAMPLE_DATA_PATH = Path(__file__).resolve().parents[3] / "ml_data.csv"


def vary_quantity(base_value, rng, *, minimum=0):
    spread = max(1, round(base_value * 0.12))
    return max(minimum, base_value + rng.randint(-spread, spread))


def build_template_days_from_records(records):
    records_by_day = defaultdict(list)

    for record in records:
        records_by_day[record.entry_date].append(
            {
                "item_name": record.item_name,
                "item_slug": record.item_slug,
                "prepared_quantity": record.prepared_quantity,
                "sold_quantity": record.sold_quantity,
            }
        )

    return [records_by_day[entry_date] for entry_date in sorted(records_by_day)]


def load_template_days_from_csv(csv_path):
    if not csv_path.exists():
        raise CommandError(f"Sample data file not found: {csv_path}")

    template_days = []
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            day_items = []
            for item_name, prepared_key, sold_key in CSV_ITEM_COLUMNS:
                prepared_quantity = max(1, int(row[prepared_key]))
                sold_quantity = min(prepared_quantity, int(row[sold_key]))
                day_items.append(
                    {
                        "item_name": item_name,
                        "item_slug": slugify(item_name),
                        "prepared_quantity": prepared_quantity,
                        "sold_quantity": sold_quantity,
                    }
                )
            template_days.append(day_items)

    if not template_days:
        raise CommandError(f"No sample rows found in {csv_path}")

    return template_days


def seed_history_for_user(user, template_days, anchor_date, copies, rng):
    total_days = len(template_days) * copies
    current_date = anchor_date - timedelta(days=total_days)
    created_count = 0
    updated_count = 0

    for _ in range(copies):
        for template_day in template_days:
            for template in template_day:
                prepared_quantity = vary_quantity(
                    template["prepared_quantity"],
                    rng,
                    minimum=1,
                )
                sold_quantity = min(
                    prepared_quantity,
                    vary_quantity(template["sold_quantity"], rng, minimum=0),
                )
                _, created = DailyFoodRecord.objects.update_or_create(
                    user=user,
                    entry_date=current_date,
                    item_slug=template["item_slug"],
                    defaults={
                        "item_name": template["item_name"],
                        "prepared_quantity": prepared_quantity,
                        "sold_quantity": sold_quantity,
                        "is_day_closed": True,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            current_date += timedelta(days=1)

    return created_count, updated_count


class Command(BaseCommand):
    help = (
        "Seed duplicate-like DailyFoodRecord history with small random variations "
        "to help test the random forest training flow."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            action="append",
            dest="usernames",
            help="Target one or more usernames. Defaults to all users.",
        )
        parser.add_argument(
            "--copies",
            type=int,
            default=3,
            help="How many duplicate-like history cycles to add. Default: 3.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed so test data stays reproducible. Default: 42.",
        )

    def handle(self, *args, **options):
        copies = options["copies"]
        if copies < 1:
            raise CommandError("--copies must be at least 1")

        usernames = options["usernames"] or list(
            User.objects.order_by("username").values_list("username", flat=True)
        )
        if isinstance(usernames, str):
            usernames = [usernames]
        if not usernames:
            raise CommandError("No users found. Create a user first, then run this command.")

        users = list(User.objects.filter(username__in=usernames).order_by("username"))
        found_usernames = {user.username for user in users}
        missing_usernames = sorted(set(usernames) - found_usernames)
        if missing_usernames:
            raise CommandError(
                "Unknown username(s): " + ", ".join(missing_usernames)
            )

        rng = random.Random(options["seed"])

        for user in users:
            source_records = list(
                DailyFoodRecord.objects.filter(user=user, is_day_closed=True).order_by(
                    "entry_date",
                    "item_name",
                    "id",
                )
            )

            if source_records:
                template_days = build_template_days_from_records(source_records)
                anchor_date = source_records[0].entry_date
                source_label = f"{len(template_days)} existing closed day(s)"
            else:
                template_days = load_template_days_from_csv(SAMPLE_DATA_PATH)
                anchor_date = now().date()
                source_label = f"{len(template_days)} bundled sample day(s)"

            created_count, updated_count = seed_history_for_user(
                user=user,
                template_days=template_days,
                anchor_date=anchor_date,
                copies=copies,
                rng=rng,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"{user.username}: created {created_count} rows, "
                    f"updated {updated_count} rows using {source_label}."
                )
            )
