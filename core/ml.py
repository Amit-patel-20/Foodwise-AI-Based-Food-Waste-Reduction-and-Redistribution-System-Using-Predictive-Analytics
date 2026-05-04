from pathlib import Path
import tempfile

from joblib import dump, load
from sklearn.ensemble import RandomForestRegressor

from .models import DailyFoodRecord
from django.conf import settings

MODEL_DIR = settings.MODEL_DIR

FEATURE_NAMES = [
    "day_of_week",
    "month",
    "prepared_quantity",
    "sold_quantity",
    "waste_quantity",
    "avg_prepared_last_3",
    "avg_sold_last_3",
    "avg_waste_last_3",
]


def _build_training_rows(records):
    training_rows = []

    for index in range(len(records) - 1):
        current_record = records[index]
        next_record = records[index + 1]
        history = records[max(0, index - 2) : index + 1]

        avg_prepared = round(
            sum(record.prepared_quantity for record in history) / len(history)
        )
        avg_sold = round(sum(record.sold_quantity for record in history) / len(history))
        avg_waste = round(sum(record.waste_quantity for record in history) / len(history))

        training_rows.append(
            {
                "features": [
                    current_record.entry_date.weekday(),
                    current_record.entry_date.month,
                    current_record.prepared_quantity,
                    current_record.sold_quantity,
                    current_record.waste_quantity,
                    avg_prepared,
                    avg_sold,
                    avg_waste,
                ],
                "target": next_record.prepared_quantity,
            }
        )

    return training_rows


def get_model_path(user_id, item_slug):
    return MODEL_DIR / f"user_{user_id}_{item_slug}.joblib"


def train_item_model(user, item_slug):
    records = list(
        DailyFoodRecord.objects.filter(
            user=user,
            item_slug=item_slug,
            is_day_closed=True,
        ).order_by("entry_date", "id")
    )
    rows = _build_training_rows(records)

    if len(rows) < 3:
        return {
            "model_path": None,
            "trained_samples": len(rows),
            "model_used": "heuristic",
        }

    X = [row["features"] for row in rows]
    y = [row["target"] for row in rows]

    model = RandomForestRegressor(n_estimators=150, random_state=42)
    model.fit(X, y)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = get_model_path(user.id, item_slug)
    dump({"model": model, "feature_names": FEATURE_NAMES}, model_path)

    return {
        "model_path": model_path,
        "trained_samples": len(rows),
        "model_used": "random_forest",
    }


def predict_next_quantity(record):
    history = list(
        DailyFoodRecord.objects.filter(
            user=record.user,
            item_slug=record.item_slug,
            is_day_closed=True,
            entry_date__lte=record.entry_date,
        )
        .order_by("-entry_date", "-id")[:3]
    )
    history = list(reversed(history))

    avg_prepared = round(
        sum(item.prepared_quantity for item in history) / len(history)
    )
    avg_sold = round(sum(item.sold_quantity for item in history) / len(history))
    avg_waste = round(sum(item.waste_quantity for item in history) / len(history))

    features = [
        record.entry_date.weekday(),
        record.entry_date.month,
        record.prepared_quantity,
        record.sold_quantity,
        record.waste_quantity,
        avg_prepared,
        avg_sold,
        avg_waste,
    ]

    metadata = train_item_model(record.user, record.item_slug)

    if metadata["model_path"]:
        bundle = load(metadata["model_path"])
        prediction = round(float(bundle["model"].predict([features])[0]))
    else:
        prediction = round(max(avg_sold, record.sold_quantity, record.prepared_quantity - record.waste_quantity))

    adjusted_prediction = max(1, prediction)

    if record.waste_quantity:
        adjusted_prediction = max(1, adjusted_prediction - round(record.waste_quantity * 0.3))

    return {
        "recommended_quantity": adjusted_prediction,
        "trained_samples": metadata["trained_samples"],
        "model_used": metadata["model_used"],
    }
