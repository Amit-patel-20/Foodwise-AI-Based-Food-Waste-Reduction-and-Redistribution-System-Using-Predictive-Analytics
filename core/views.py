from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.timezone import now
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from .ml import predict_next_quantity, train_item_model
from .models import (
    DailyFoodRecord,
    FoodRequest,
    PredictionSnapshot,
    RestaurantProfile,
    WeddingDonation,
)


def get_user_location(user):
    try:
        return user.restaurant_profile.location
    except RestaurantProfile.DoesNotExist:
        return "Location not added"


def normalize_item_name(item_name):
    return " ".join((item_name or "").strip().split())


def parse_positive_int(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return 0
    digits = "".join(char for char in value if char.isdigit())
    return int(digits or 0)


def normalize_pickup_time(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return ""

    try:
        datetime.fromisoformat(value)
    except ValueError:
        return ""

    return value


def extract_food_rows(post_data, quantity_key):
    item_names = post_data.getlist("item_name")
    quantities = post_data.getlist(quantity_key)
    rows = []

    for item_name, quantity in zip(item_names, quantities):
        cleaned_name = normalize_item_name(item_name)
        cleaned_quantity = parse_positive_int(quantity)

        if not cleaned_name:
            continue

        rows.append(
            {
                "item_name": cleaned_name,
                "quantity": cleaned_quantity,
            }
        )

    return rows


def get_today_records(user):
    today = now().date()
    return DailyFoodRecord.objects.filter(user=user, entry_date=today).order_by("item_name")


def build_available_item_rows(user, food_date=None):
    target_date = food_date or now().date()
    reserved_quantities = {
        normalize_item_name(row["item_name"]).lower(): row["total_requested"] or 0
        for row in FoodRequest.objects.filter(
            restaurant=user,
            food_date=target_date,
        )
        .exclude(status="rejected")
        .values("item_name")
        .annotate(total_requested=Sum("requested_quantity"))
        if row["item_name"]
    }

    available_items = []
    records = DailyFoodRecord.objects.filter(
        user=user,
        entry_date=target_date,
        is_day_closed=True,
        waste_quantity__gt=0,
    ).order_by("item_name")

    for record in records:
        item_key = normalize_item_name(record.item_name).lower()
        reserved_quantity = reserved_quantities.get(item_key, 0)
        available_quantity = max(record.waste_quantity - reserved_quantity, 0)
        if available_quantity <= 0:
            continue

        available_items.append(
            {
                "item_name": record.item_name,
                "available_quantity": available_quantity,
                "waste_quantity": record.waste_quantity,
            }
        )

    return available_items


def get_recent_closed_day_totals(user, limit=7):
    daily_totals = list(
        DailyFoodRecord.objects.filter(user=user, is_day_closed=True)
        .values("entry_date")
        .annotate(
            prepared_total=Sum("prepared_quantity"),
            sold_total=Sum("sold_quantity"),
            waste_total=Sum("waste_quantity"),
        )
        .order_by("-entry_date")[:limit]
    )
    daily_totals.reverse()
    
    return daily_totals


def build_prepared_sold_waste_trend_data(daily_totals):
    trend_rows = []

    for row in daily_totals:
        trend_rows.append(
            {
                "entry_date": row["entry_date"].strftime("%d %b"),
                "prepared_quantity": row["prepared_total"] or 0,
                "sold_quantity": row["sold_total"] or 0,
                "waste_quantity": row["waste_total"] or 0,
            }
        )
    
    return trend_rows


def build_daily_waste_trend_data(daily_totals):
    waste_rows = []

    for row in daily_totals:
        waste_rows.append(
            {
                "entry_date": row["entry_date"].strftime("%d %b"),
                "waste_quantity": row["waste_total"] or 0,
            }
        )

    return waste_rows


def build_donation_cards():
    today = now().date()
    donation_map = {}

    records = DailyFoodRecord.objects.filter(
        entry_date=today,
        is_day_closed=True,
        waste_quantity__gt=0,
    ).select_related("user")

    for record in records:
        username = record.user.username
        if username in donation_map:
            continue

        available_items = build_available_item_rows(record.user, today)
        if not available_items:
            continue

        donation_map[username] = {
            "restaurant": username,
            "location": get_user_location(record.user),
            "items": available_items,
            "total_quantity": sum(item["available_quantity"] for item in available_items),
        }

    return list(donation_map.values())


def build_prediction_rows(user):
    closed_records = list(
        DailyFoodRecord.objects.filter(user=user, is_day_closed=True, entry_date=now().date()).order_by(
            "item_name",
            "-entry_date",
            "-id",
        )
    )
    latest_records = []
    seen_items = set()

    for record in closed_records:
        if record.item_slug in seen_items:
            continue
        seen_items.add(record.item_slug)
        latest_records.append(record)

    prediction_rows = []
    tomorrow = now().date() + timedelta(days=1)

    for record in latest_records:
        result = predict_next_quantity(record)
        snapshot, _ = PredictionSnapshot.objects.update_or_create(
            user=user,
            entry_date=tomorrow,
            item_name=record.item_name,
            defaults={
                "recommended_quantity": result["recommended_quantity"],
                "model_used": result["model_used"],
                "trained_samples": result["trained_samples"],
            },
        )
        prediction_rows.append(snapshot)

    return prediction_rows


@never_cache
def home(request):
    wedding_donations = WeddingDonation.objects.filter(is_active=True).order_by("-event_date", "-created_at")
    return render(
        request,
        "index.html",
        {
            "donations": build_donation_cards(),
            "wedding_donations": wedding_donations,
        },
    )


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        location = request.POST.get("location", "").strip()
        if form.is_valid():
            user = form.save()
            RestaurantProfile.objects.create(
                user=user,
                location=location or "Location not added",
            )
            login(request, user)
            return redirect("restaurant_dashboard")
    else:
        form = UserCreationForm()

    return render(request, "register.html", {"form": form})


@never_cache
@login_required
def restaurant_dashboard(request):
    profile, _ = RestaurantProfile.objects.get_or_create(
        user=request.user,
        defaults={"location": "Location not added"},
    )
    today_records = list(get_today_records(request.user))
    planned_records = [record for record in today_records if record.prepared_quantity > 0]
    closed_records = [record for record in today_records if record.is_day_closed]
    recent_closed_day_totals = get_recent_closed_day_totals(request.user)
    prepared_sold_waste_trend_data = build_prepared_sold_waste_trend_data(recent_closed_day_totals)
    daily_waste_trend_data = build_daily_waste_trend_data(recent_closed_day_totals)
    requests = FoodRequest.objects.filter(restaurant=request.user).order_by("-created_at")
    latest_predictions = (
        PredictionSnapshot.objects.filter(user=request.user,).order_by("item_name", "-entry_date")
    )
    latest_prediction_map = {}
    for prediction in latest_predictions:
        latest_prediction_map.setdefault(prediction.item_name, prediction)

    return render(
        request,
        "restaurant_dashboard.html",
        {
            "planned_records": planned_records,
            "closed_records": closed_records,
            "prepared_sold_waste_trend_data": prepared_sold_waste_trend_data,
            "daily_waste_trend_data": daily_waste_trend_data,
            "requests": requests,
            "latest_predictions": latest_prediction_map.values(),
            "profile": profile,
        },
    )


@never_cache
@login_required
def add_food(request):
    today = now().date()
    existing_records = list(get_today_records(request.user))

    if request.method == "POST":
        rows = extract_food_rows(request.POST, "prepared_quantity")

        if not rows:
            messages.error(request, "Add at least one food item with a quantity.")
            return render(
                request,
                "add_Food.html",
                {"existing_records": existing_records},
            )

        if any(record.is_day_closed for record in existing_records):
            messages.error(request, "Today's day is already closed. Start again tomorrow.")
            return redirect("restaurant_dashboard")

        submitted_names = set()
        for row in rows:
            submitted_names.add(row["item_name"].lower())
            DailyFoodRecord.objects.update_or_create(
                user=request.user,
                entry_date=today,
                item_slug=slugify(row["item_name"]),
                defaults={
                    "item_name": row["item_name"],
                    "prepared_quantity": row["quantity"],
                    "sold_quantity": 0,
                    "waste_quantity": row["quantity"],
                    "is_day_closed": False,
                },
            )

        for record in existing_records:
            if record.item_name.lower() not in submitted_names:
                record.delete()

        messages.success(request, "Today's food preparation plan has been saved.")
        return redirect("restaurant_dashboard")

    return render(request, "add_Food.html", {"existing_records": existing_records})


@never_cache
@login_required
def close_day(request):
    today_records = list(get_today_records(request.user))

    if request.method == "POST":
        if not today_records:
            messages.error(request, "Add today's food plan before closing the day.")
            return redirect("add_food")

        rows = extract_food_rows(request.POST, "sold_quantity")
        sold_lookup = {row["item_name"].lower(): row["quantity"] for row in rows}

        updated_records = []
        for record in today_records:
            sold_quantity = min(sold_lookup.get(record.item_name.lower(), 0), record.prepared_quantity)
            record.sold_quantity = sold_quantity
            record.is_day_closed = True
            record.save()
            train_item_model(record.user, record.item_slug)
            updated_records.append(record)

        build_prediction_rows(request.user)
        messages.success(request, "Day closed successfully. Donation list and predictions are updated.")
        return redirect("restaurant_dashboard")

    return render(request, "close_day.html", {"today_records": today_records})


@never_cache
@login_required
def predict_page(request):
    prediction_rows = []

    if request.method == "POST":
        prediction_rows = build_prediction_rows(request.user)
        if not prediction_rows:
            messages.error(request, "Close at least one day of data to generate predictions.")

    return render(request, "predict.html", {"prediction_rows": prediction_rows})


def wedding_donation(request):
    if request.method == "POST":
        organizer_name = request.POST.get("organizer_name", "").strip()
        contact_phone = request.POST.get("contact_phone", "").strip()
        venue_name = request.POST.get("venue_name", "").strip()
        location = request.POST.get("location", "").strip()
        food_description = request.POST.get("food_description", "").strip()
        quantity = parse_positive_int(request.POST.get("quantity"))
        available_until = request.POST.get("available_until", "").strip()

        if not all([organizer_name, contact_phone, venue_name, location, food_description, quantity]):
            messages.error(request, "Please fill all required wedding donation details.")
            return render(request, "wedding_donation.html")

        WeddingDonation.objects.create(
            organizer_name=organizer_name,
            contact_phone=contact_phone,
            venue_name=venue_name,
            location=location,
            food_description=food_description,
            quantity=quantity,
            available_until=available_until,
            event_date=now().date(),
        )
        messages.success(request, "Wedding food donation posted successfully.")
        return redirect("home")

    return render(request, "wedding_donation.html")


@login_required
def update_location(request):
    if request.method == "POST":
        location = request.POST.get("location", "").strip()
        profile, _ = RestaurantProfile.objects.get_or_create(
            user=request.user,
            defaults={"location": "Location not added"},
        )
        profile.location = location or "Location not added"
        profile.save()
        messages.success(request, "Restaurant location updated successfully.")

    return redirect("restaurant_dashboard")


@never_cache
@csrf_protect
def request_food(request, restaurant_username):
    restaurant = get_object_or_404(User, username=restaurant_username)
    profile, _ = RestaurantProfile.objects.get_or_create(
        user=restaurant,
        defaults={"location": "Location not added"},
    )
    available_items = build_available_item_rows(restaurant)
    available_item_lookup = {
        normalize_item_name(item["item_name"]).lower(): item
        for item in available_items
    }

    if request.method == "POST":
        requester_name = request.POST.get("name", "").strip()
        requester_phone = request.POST.get("phone", "").strip()
        item_name = normalize_item_name(request.POST.get("item_name"))
        requested_quantity = parse_positive_int(request.POST.get("requested_quantity"))
        preferred_pickup_time = normalize_pickup_time(request.POST.get("preferred_pickup_time"))

        if not available_items:
            messages.error(request, "This restaurant has no requestable leftover items right now.")
            return render(
                request,
                "Request_Food.html",
                {
                    "restaurant": restaurant,
                    "profile": profile,
                    "available_items": available_items,
                },
            )

        if not all([requester_name, requester_phone, item_name, requested_quantity, preferred_pickup_time]):
            messages.error(request, "Please fill your details, choose an item, quantity, and pickup time.")
            return render(
                request,
                "Request_Food.html",
                {
                    "restaurant": restaurant,
                    "profile": profile,
                    "available_items": available_items,
                },
            )

        item_row = available_item_lookup.get(item_name.lower())
        if item_row is None:
            messages.error(request, "Please choose one of the currently available food items.")
            return render(
                request,
                "Request_Food.html",
                {
                    "restaurant": restaurant,
                    "profile": profile,
                    "available_items": available_items,
                },
            )

        if requested_quantity > item_row["available_quantity"]:
            messages.error(
                request,
                f"Only {item_row['available_quantity']} serving(s) of {item_row['item_name']} are available right now.",
            )
            return render(
                request,
                "Request_Food.html",
                {
                    "restaurant": restaurant,
                    "profile": profile,
                    "available_items": available_items,
                },
            )

        food_request = FoodRequest.objects.create(
            restaurant=restaurant,
            food_date=now().date(),
            item_name=item_row["item_name"],
            requested_quantity=requested_quantity,
            requester_name=requester_name,
            requester_phone=requester_phone,
            preferred_pickup_time=preferred_pickup_time,
            status="pending",
        )
        messages.success(request, "Your pickup request has been sent.")
        return redirect("request_status", req_id=food_request.id)

    return render(
        request,
        "Request_Food.html",
        {
            "restaurant": restaurant,
            "profile": profile,
            "available_items": available_items,
        },
    )


@never_cache
def request_status(request, req_id):
    food_request = get_object_or_404(FoodRequest, id=req_id)
    return render(request, "request_status.html", {"req": food_request})


@never_cache
@login_required
def accept_request(request, req_id):
    food_request = get_object_or_404(FoodRequest, id=req_id, restaurant=request.user)
    if food_request.status == "rejected":
        messages.error(request, "Rejected requests cannot be scheduled.")
        return redirect("restaurant_dashboard")

    if request.method == "POST":
        scheduled_pickup_time = normalize_pickup_time(request.POST.get("scheduled_pickup_time"))

        if not scheduled_pickup_time:
            messages.error(request, "Choose a valid pickup date and time.")
            return render(request, "schedule_request.html", {"req": food_request})

        food_request.scheduled_pickup_time = scheduled_pickup_time
        food_request.status = "scheduled"
        food_request.save()
        messages.success(request, "Pickup has been scheduled successfully.")
        return redirect("restaurant_dashboard")

    return render(request, "schedule_request.html", {"req": food_request})


@login_required
def reject_request(request, req_id):
    food_request = get_object_or_404(FoodRequest, id=req_id, restaurant=request.user)
    food_request.status = "rejected"
    food_request.scheduled_pickup_time = ""
    food_request.save()
    return redirect("restaurant_dashboard")


@login_required
def delete_request(request, req_id):
    food_request = get_object_or_404(FoodRequest, id=req_id, restaurant=request.user)
    food_request.delete()
    return redirect("restaurant_dashboard")


@login_required
def delete_all_requests(request):
    FoodRequest.objects.filter(restaurant=request.user).delete()
    messages.success(request, "All food requests deleted successfully.")
    return redirect("restaurant_dashboard")
