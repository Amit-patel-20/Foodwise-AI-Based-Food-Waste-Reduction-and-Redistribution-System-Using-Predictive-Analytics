from django.contrib import admin
from .models import (
    DailyFoodRecord,
    FoodRequest,
    PredictionSnapshot,
    RestaurantProfile,
    WeddingDonation,
)


@admin.register(DailyFoodRecord)
class DailyFoodRecordAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "entry_date",
        "item_name",
        "prepared_quantity",
        "sold_quantity",
        "waste_quantity",
        "is_day_closed",
    )
    list_filter = ("is_day_closed", "entry_date")
    search_fields = ("user__username", "item_name")


@admin.register(PredictionSnapshot)
class PredictionSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "entry_date",
        "item_name",
        "recommended_quantity",
        "model_used",
        "trained_samples",
    )
    list_filter = ("model_used", "entry_date")
    search_fields = ("user__username", "item_name")


@admin.register(FoodRequest)
class FoodRequestAdmin(admin.ModelAdmin):
    list_display = (
        "restaurant",
        "food_date",
        "item_name",
        "requested_quantity",
        "requester_name",
        "requester_phone",
        "status",
        "scheduled_pickup_time_display",
        "created_at",
    )
    list_filter = ("status", "food_date")
    search_fields = ("restaurant__username", "requester_name", "requester_phone", "item_name")


@admin.register(RestaurantProfile)
class RestaurantProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "location")
    search_fields = ("user__username", "location")


@admin.register(WeddingDonation)
class WeddingDonationAdmin(admin.ModelAdmin):
    list_display = (
        "organizer_name",
        "venue_name",
        "location",
        "quantity",
        "event_date",
        "is_active",
    )
    list_filter = ("is_active", "event_date")
    search_fields = ("organizer_name", "venue_name", "location")
