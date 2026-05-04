from datetime import datetime
from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify
from django.utils.timezone import now


def format_pickup_time(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return ""

    try:
        pickup_time = datetime.fromisoformat(value)
    except ValueError:
        return value

    return pickup_time.strftime("%d %b %Y, %I:%M %p")


class DailyFoodRecord(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="daily_food_records",
    )
    entry_date = models.DateField(default=now)
    item_name = models.CharField(max_length=120)
    item_slug = models.SlugField(max_length=140, editable=False)
    prepared_quantity = models.PositiveIntegerField(default=0)
    sold_quantity = models.PositiveIntegerField(default=0)
    waste_quantity = models.PositiveIntegerField(default=0)
    is_day_closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "entry_date", "item_slug"],
                name="unique_food_record_per_day",
            )
        ]

    def save(self, *args, **kwargs):
        self.item_name = self.item_name.strip()
        self.item_slug = slugify(self.item_name)
        self.waste_quantity = max(self.prepared_quantity - self.sold_quantity, 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.item_name} - {self.entry_date}"


class PredictionSnapshot(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="prediction_snapshots",
    )
    entry_date = models.DateField(default=now)
    item_name = models.CharField(max_length=120)
    recommended_quantity = models.PositiveIntegerField(default=0)
    model_used = models.CharField(max_length=50, default="heuristic")
    trained_samples = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "entry_date", "item_name"],
                name="unique_prediction_per_day",
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.item_name} - {self.entry_date}"


class RestaurantProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="restaurant_profile",
    )
    location = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.user.username} - {self.location}"


class WeddingDonation(models.Model):
    organizer_name = models.CharField(max_length=120)
    contact_phone = models.CharField(max_length=20)
    venue_name = models.CharField(max_length=150)
    location = models.CharField(max_length=255)
    food_description = models.TextField()
    quantity = models.PositiveIntegerField(default=0)
    event_date = models.DateField(default=now)
    available_until = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_date", "-created_at"]

    def __str__(self):
        return f"{self.organizer_name} - {self.venue_name}"


class FoodRequest(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("scheduled", "Scheduled"),
        ("rejected", "Rejected"),
    )

    restaurant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_requests",
    )
    food_date = models.DateField(default=now)
    item_name = models.CharField(max_length=120, blank=True)
    requested_quantity = models.PositiveIntegerField(default=0)
    requester_name = models.CharField(max_length=100)
    requester_phone = models.CharField(max_length=15)
    preferred_pickup_time = models.CharField(max_length=40, blank=True)
    scheduled_pickup_time = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def preferred_pickup_time_display(self):
        return format_pickup_time(self.preferred_pickup_time)

    @property
    def scheduled_pickup_time_display(self):
        return format_pickup_time(self.scheduled_pickup_time)

    def __str__(self):
        item_label = self.item_name or "General request"
        return f"{self.requester_name} -> {self.restaurant.username} ({item_label})"


class Notification(models.Model):
    CATEGORY_CHOICES = (
        ("info", "Info"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("danger", "Danger"),
    )

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=140)
    message = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="info")
    is_read = models.BooleanField(default=False)
    related_request = models.ForeignKey(
        FoodRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"
