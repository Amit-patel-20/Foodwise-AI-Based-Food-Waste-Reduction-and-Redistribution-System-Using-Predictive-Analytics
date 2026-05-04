from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from .models import DailyFoodRecord, FoodRequest, PredictionSnapshot, RestaurantProfile, WeddingDonation


class FoodWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="green_kitchen", password="testpass123")
        self.client.login(username="green_kitchen", password="testpass123")

    def test_provider_can_add_food_close_day_and_generate_predictions(self):
        RestaurantProfile.objects.create(user=self.user, location="Hazratganj, Lucknow")
        response = self.client.post(
            reverse("add_food"),
            {
                "item_name": ["Dal", "Rice"],
                "prepared_quantity": ["40", "25"],
            },
        )
        self.assertRedirects(response, reverse("restaurant_dashboard"))
        self.assertEqual(DailyFoodRecord.objects.count(), 2)

        response = self.client.post(
            reverse("close_day"),
            {
                "item_name": ["Dal", "Rice"],
                "sold_quantity": ["30", "20"],
            },
        )
        self.assertRedirects(response, reverse("restaurant_dashboard"))

        dal_record = DailyFoodRecord.objects.get(item_slug="dal")
        rice_record = DailyFoodRecord.objects.get(item_slug="rice")

        self.assertTrue(dal_record.is_day_closed)
        self.assertEqual(dal_record.waste_quantity, 10)
        self.assertEqual(rice_record.waste_quantity, 5)

        dashboard_response = self.client.get(reverse("restaurant_dashboard"))
        self.assertContains(dashboard_response, "Prepared vs Sold vs Waste Trend")
        self.assertContains(dashboard_response, "Daily Waste Trend")
        self.assertContains(dashboard_response, "prepared-sold-waste-trend-data")
        self.assertContains(dashboard_response, "daily-waste-trend-data")

        home_response = self.client.get(reverse("home"))
        self.assertContains(home_response, "green_kitchen")
        self.assertContains(home_response, "Dal")
        self.assertContains(home_response, "10")
        self.assertContains(home_response, "Hazratganj, Lucknow")
        self.assertContains(
            home_response,
            "https://www.google.com/maps/search/?api=1&query=Hazratganj%2C%20Lucknow",
            html=False,
        )

        prediction_response = self.client.post(reverse("predict_page"))
        self.assertEqual(prediction_response.status_code, 200)
        self.assertContains(prediction_response, "Dal")
        self.assertContains(prediction_response, "heuristic")
        self.assertEqual(PredictionSnapshot.objects.count(), 2)

    def test_home_page_handles_restaurant_without_profile(self):
        DailyFoodRecord.objects.create(
            user=self.user,
            item_name="Khichdi",
            prepared_quantity=25,
            sold_quantity=10,
            is_day_closed=True,
        )

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Location not added")

    def test_food_request_can_be_created_from_public_page(self):
        RestaurantProfile.objects.create(user=self.user, location="Aliganj, Lucknow")
        FoodRequest.objects.create(
            restaurant=self.user,
            food_date=now().date(),
            item_name="Rice",
            requested_quantity=5,
            requester_name="Seed NGO",
            requester_phone="9876543210",
            preferred_pickup_time="2026-04-22T19:30",
        )
        dashboard_response = self.client.get(reverse("restaurant_dashboard"))
        self.assertContains(dashboard_response, "Seed NGO")
        self.assertContains(dashboard_response, "Rice")
        self.assertContains(dashboard_response, "Aliganj, Lucknow")
        self.assertContains(
            dashboard_response,
            "https://www.google.com/maps/search/?api=1&query=Aliganj%2C%20Lucknow",
            html=False,
        )

    def test_public_user_can_request_specific_item_with_pickup_time(self):
        RestaurantProfile.objects.create(user=self.user, location="Aminabad, Lucknow")
        DailyFoodRecord.objects.create(
            user=self.user,
            item_name="Dal",
            prepared_quantity=25,
            sold_quantity=15,
            is_day_closed=True,
        )

        self.client.logout()
        response = self.client.post(
            reverse("request_food", args=[self.user.username]),
            {
                "name": "Hope Trust",
                "phone": "9998887776",
                "item_name": "Dal",
                "requested_quantity": "4",
                "preferred_pickup_time": "2026-04-22T19:30",
            },
        )

        request_record = FoodRequest.objects.get(requester_name="Hope Trust")
        self.assertRedirects(response, reverse("request_status", args=[request_record.id]))
        self.assertEqual(request_record.item_name, "Dal")
        self.assertEqual(request_record.requested_quantity, 4)
        self.assertEqual(request_record.preferred_pickup_time, "2026-04-22T19:30")

        home_response = self.client.get(reverse("home"))
        self.assertContains(home_response, "Available now: 6 servings")

        status_response = self.client.get(reverse("request_status", args=[request_record.id]))
        self.assertContains(status_response, "Dal")
        self.assertContains(status_response, "4 servings")
        self.assertContains(status_response, "22 Apr 2026, 07:30 PM")

    def test_restaurant_can_schedule_pickup_for_requested_item(self):
        request_record = FoodRequest.objects.create(
            restaurant=self.user,
            food_date=now().date(),
            item_name="Dal",
            requested_quantity=4,
            requester_name="Hope Trust",
            requester_phone="9998887776",
            preferred_pickup_time="2026-04-22T19:30",
        )

        response = self.client.post(
            reverse("accept_request", args=[request_record.id]),
            {"scheduled_pickup_time": "2026-04-22T20:15"},
        )

        self.assertRedirects(response, reverse("restaurant_dashboard"))
        request_record.refresh_from_db()
        self.assertEqual(request_record.status, "scheduled")
        self.assertEqual(request_record.scheduled_pickup_time, "2026-04-22T20:15")

        status_response = self.client.get(reverse("request_status", args=[request_record.id]))
        self.assertContains(status_response, "22 Apr 2026, 08:15 PM")
        self.assertContains(status_response, "scheduled")

    def test_register_creates_restaurant_location(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "city_dhaba",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "location": "Charbagh, Lucknow",
            },
        )

        self.assertRedirects(response, reverse("restaurant_dashboard"))
        self.assertTrue(
            RestaurantProfile.objects.filter(
                user__username="city_dhaba",
                location="Charbagh, Lucknow",
            ).exists()
        )

    def test_public_wedding_donation_can_be_posted_and_listed(self):
        response = self.client.post(
            reverse("wedding_donation"),
            {
                "organizer_name": "Anand Events",
                "contact_phone": "9999999999",
                "venue_name": "Royal Garden",
                "location": "Indira Nagar, Lucknow",
                "food_description": "Pulao, paneer, roti, sweets",
                "quantity": "120",
                "available_until": "Tonight 11:30 PM",
            },
        )

        self.assertRedirects(response, reverse("home"))
        self.assertTrue(
            WeddingDonation.objects.filter(
                venue_name="Royal Garden",
                location="Indira Nagar, Lucknow",
            ).exists()
        )

        home_response = self.client.get(reverse("home"))
        self.assertContains(home_response, "Wedding food donations")
        self.assertContains(home_response, "Royal Garden")
        self.assertContains(home_response, "Indira Nagar, Lucknow")
        self.assertContains(
            home_response,
            "https://www.google.com/maps/search/?api=1&query=Indira%20Nagar%2C%20Lucknow",
            html=False,
        )


class RandomForestTrainingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="hostel_mess", password="testpass123")

    def test_prediction_page_shows_random_forest_after_history_exists(self):
        start_date = now().date() - timedelta(days=3)

        for offset, prepared, sold in [
            (0, 100, 92),
            (1, 110, 100),
            (2, 105, 98),
            (3, 115, 107),
        ]:
            DailyFoodRecord.objects.create(
                user=self.user,
                entry_date=start_date + timedelta(days=offset),
                item_name="Chapati",
                prepared_quantity=prepared,
                sold_quantity=sold,
                is_day_closed=True,
            )

        self.client.login(username="hostel_mess", password="testpass123")
        response = self.client.post(reverse("predict_page"))

        self.assertContains(response, "Chapati")
        self.assertContains(response, "random_forest")
        self.assertTrue(
            PredictionSnapshot.objects.filter(
                user=self.user,
                item_name="Chapati",
                model_used="random_forest",
            ).exists()
        )


class SeedFoodHistoryCommandTests(TestCase):
    def test_command_duplicates_existing_closed_days(self):
        user = User.objects.create_user(username="dup_seed", password="testpass123")
        start_date = now().date() - timedelta(days=3)

        for offset, prepared, sold in [
            (0, 40, 32),
            (1, 48, 36),
        ]:
            DailyFoodRecord.objects.create(
                user=user,
                entry_date=start_date + timedelta(days=offset),
                item_name="Dal",
                prepared_quantity=prepared,
                sold_quantity=sold,
                is_day_closed=True,
            )
            DailyFoodRecord.objects.create(
                user=user,
                entry_date=start_date + timedelta(days=offset),
                item_name="Rice",
                prepared_quantity=prepared - 5,
                sold_quantity=sold - 4,
                is_day_closed=True,
            )

        output = StringIO()
        call_command(
            "seed_food_history",
            username=user.username,
            copies=2,
            seed=7,
            stdout=output,
        )

        records = DailyFoodRecord.objects.filter(user=user)
        self.assertEqual(records.count(), 12)
        self.assertIn("created 8 rows", output.getvalue())
        self.assertEqual(
            records.filter(is_day_closed=True).count(),
            12,
        )
        self.assertEqual(
            records.values_list("entry_date", flat=True).distinct().count(),
            6,
        )

    def test_command_uses_csv_samples_when_user_has_no_history(self):
        user = User.objects.create_user(username="csv_seed", password="testpass123")

        output = StringIO()
        call_command(
            "seed_food_history",
            username=user.username,
            copies=1,
            seed=11,
            stdout=output,
        )

        records = DailyFoodRecord.objects.filter(user=user, is_day_closed=True)
        self.assertTrue(records.exists())
        self.assertIn("bundled sample day(s)", output.getvalue())
        self.assertEqual(
            set(records.values_list("item_name", flat=True)),
            {"Dal", "Chawal", "Sabji"},
        )
