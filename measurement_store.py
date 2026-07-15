import csv
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from acclimatization import (
    DEFAULT_ACCLIMATIZATION,
    validate_acclimatization_inputs,
)


BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv("WGBT_DATA_DIR", BASE_DIR / "data"))
SAMPLE_MEASUREMENT_PATH = DATA_DIR / "sample.csv"
CURRENT_MEASUREMENT_PATH = DATA_DIR / "current_measurement.json"
DEFAULT_PROFILE = {
    "age": 25,
    "weight": 70.0,
    "sex": "male",
}
FALLBACK_MEASUREMENT = {
    "heart_rate": 130,
    "wbgt": 31.2,
    **DEFAULT_PROFILE,
    **DEFAULT_ACCLIMATIZATION,
    "source": "fallback",
    "updated_at": None,
}


def validate_measurement(heart_rate, wbgt):
    try:
        normalized_heart_rate = int(heart_rate)
    except (TypeError, ValueError) as error:
        raise ValueError("심박수는 정수여야 합니다.") from error

    try:
        normalized_wbgt = float(wbgt)
    except (TypeError, ValueError) as error:
        raise ValueError("WBGT는 숫자여야 합니다.") from error

    if normalized_heart_rate <= 0 or normalized_heart_rate > 220:
        raise ValueError("심박수는 1~220 범위여야 합니다.")

    if normalized_wbgt < 0 or normalized_wbgt > 60:
        raise ValueError("WBGT는 0~60 범위여야 합니다.")

    return normalized_heart_rate, normalized_wbgt


def validate_profile(age, weight, sex):
    try:
        normalized_age = int(age)
    except (TypeError, ValueError) as error:
        raise ValueError("나이는 정수여야 합니다.") from error

    try:
        normalized_weight = float(weight)
    except (TypeError, ValueError) as error:
        raise ValueError("체중은 숫자여야 합니다.") from error

    normalized_sex = str(sex).lower()

    if normalized_age <= 0 or normalized_age > 120:
        raise ValueError("나이는 1~120 범위여야 합니다.")

    if normalized_weight <= 0 or normalized_weight > 300:
        raise ValueError("체중은 1~300kg 범위여야 합니다.")

    if normalized_sex not in ("male", "female"):
        raise ValueError("성별은 male 또는 female 이어야 합니다.")

    return normalized_age, normalized_weight, normalized_sex


def load_sample_measurement(sample_path=SAMPLE_MEASUREMENT_PATH):
    if not sample_path.exists():
        return FALLBACK_MEASUREMENT.copy()

    with sample_path.open(encoding="utf-8", newline="") as sample_file:
        rows = list(csv.DictReader(sample_file))

    if not rows:
        return FALLBACK_MEASUREMENT.copy()

    latest = rows[-1]
    try:
        heart_rate, wbgt = validate_measurement(latest["heart_rate"], latest["wbgt"])
        age, weight, sex = validate_profile(
            latest.get("age", DEFAULT_PROFILE["age"]),
            latest.get("weight", DEFAULT_PROFILE["weight"]),
            latest.get("sex", DEFAULT_PROFILE["sex"]),
        )
        worker_status, heat_exposure_days, absence_days, similar_heat_work = (
            validate_acclimatization_inputs(
                latest.get("worker_status", DEFAULT_ACCLIMATIZATION["worker_status"]),
                latest.get(
                    "heat_exposure_days",
                    DEFAULT_ACCLIMATIZATION["heat_exposure_days"],
                ),
                latest.get("absence_days", DEFAULT_ACCLIMATIZATION["absence_days"]),
                latest.get(
                    "similar_heat_work",
                    DEFAULT_ACCLIMATIZATION["similar_heat_work"],
                ),
            )
        )
    except (KeyError, ValueError):
        return FALLBACK_MEASUREMENT.copy()

    return {
        "heart_rate": heart_rate,
        "wbgt": wbgt,
        "age": age,
        "weight": weight,
        "sex": sex,
        "worker_status": worker_status,
        "heat_exposure_days": heat_exposure_days,
        "absence_days": absence_days,
        "similar_heat_work": similar_heat_work,
        "source": "sample",
        "updated_at": latest.get("time"),
    }


def read_measurement(
    measurement_path=CURRENT_MEASUREMENT_PATH,
    sample_path=SAMPLE_MEASUREMENT_PATH,
):
    if not measurement_path.exists():
        return load_sample_measurement(sample_path)

    try:
        payload = json.loads(measurement_path.read_text(encoding="utf-8"))
        heart_rate, wbgt = validate_measurement(
            payload["heart_rate"],
            payload["wbgt"],
        )
        age, weight, sex = validate_profile(
            payload.get("age", DEFAULT_PROFILE["age"]),
            payload.get("weight", DEFAULT_PROFILE["weight"]),
            payload.get("sex", DEFAULT_PROFILE["sex"]),
        )
        worker_status, heat_exposure_days, absence_days, similar_heat_work = (
            validate_acclimatization_inputs(
                payload.get("worker_status", DEFAULT_ACCLIMATIZATION["worker_status"]),
                payload.get(
                    "heat_exposure_days",
                    DEFAULT_ACCLIMATIZATION["heat_exposure_days"],
                ),
                payload.get("absence_days", DEFAULT_ACCLIMATIZATION["absence_days"]),
                payload.get(
                    "similar_heat_work",
                    DEFAULT_ACCLIMATIZATION["similar_heat_work"],
                ),
            )
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return load_sample_measurement(sample_path)

    return {
        "heart_rate": heart_rate,
        "wbgt": wbgt,
        "age": age,
        "weight": weight,
        "sex": sex,
        "worker_status": worker_status,
        "heat_exposure_days": heat_exposure_days,
        "absence_days": absence_days,
        "similar_heat_work": similar_heat_work,
        "source": "computer",
        "updated_at": payload.get("updated_at"),
    }


def write_measurement(
    heart_rate,
    wbgt,
    age=DEFAULT_PROFILE["age"],
    weight=DEFAULT_PROFILE["weight"],
    sex=DEFAULT_PROFILE["sex"],
    worker_status=DEFAULT_ACCLIMATIZATION["worker_status"],
    heat_exposure_days=DEFAULT_ACCLIMATIZATION["heat_exposure_days"],
    absence_days=DEFAULT_ACCLIMATIZATION["absence_days"],
    similar_heat_work=DEFAULT_ACCLIMATIZATION["similar_heat_work"],
    measurement_path=CURRENT_MEASUREMENT_PATH,
    updated_at=None,
):
    normalized_heart_rate, normalized_wbgt = validate_measurement(heart_rate, wbgt)
    normalized_age, normalized_weight, normalized_sex = validate_profile(age, weight, sex)
    (
        normalized_worker_status,
        normalized_heat_exposure_days,
        normalized_absence_days,
        normalized_similar_heat_work,
    ) = validate_acclimatization_inputs(
        worker_status,
        heat_exposure_days,
        absence_days,
        similar_heat_work,
    )
    timestamp = updated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "heart_rate": normalized_heart_rate,
        "wbgt": normalized_wbgt,
        "age": normalized_age,
        "weight": normalized_weight,
        "sex": normalized_sex,
        "worker_status": normalized_worker_status,
        "heat_exposure_days": normalized_heat_exposure_days,
        "absence_days": normalized_absence_days,
        "similar_heat_work": normalized_similar_heat_work,
        "updated_at": timestamp,
    }

    measurement_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        delete=False,
        dir=measurement_path.parent,
        encoding="utf-8",
        newline="\n",
        suffix=".json",
    ) as temp_file:
        json.dump(payload, temp_file, ensure_ascii=False, indent=2)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)

    temp_path.replace(measurement_path)
    return payload
