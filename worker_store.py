import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from acclimatization import (
    DEFAULT_ACCLIMATIZATION,
    evaluate_acclimatization,
    validate_acclimatization_inputs,
)
from measurement_store import DEFAULT_PROFILE, validate_measurement, validate_profile
from metabolism import (
    calculate_calories_from_vo2,
    calculate_energy_keytel,
    estimate_vo2_by_hrr,
)
from wbgt_risk import calculate_heat_risk


BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv("WGBT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.getenv("WGBT_DB_PATH", DATA_DIR / "workers.db"))

DEFAULT_RESTING_HR = 65
DEFAULT_CLOTHING_ADJUSTMENT = 0.0

DEFAULT_WORKERS = [
    {
        "worker_id": "W001",
        "name": "김철수",
        "age": 25,
        "weight": 70.0,
        "sex": "male",
        **DEFAULT_ACCLIMATIZATION,
    },
    {
        "worker_id": "W002",
        "name": "홍길동",
        "age": 30,
        "weight": 75.0,
        "sex": "male",
        **DEFAULT_ACCLIMATIZATION,
    },
    {
        "worker_id": "W003",
        "name": "이영희",
        "age": 28,
        "weight": 58.0,
        "sex": "female",
        **DEFAULT_ACCLIMATIZATION,
    },
    {
        "worker_id": "W004",
        "name": "박민수",
        "age": 42,
        "weight": 82.0,
        "sex": "male",
        "worker_status": "returning",
        "heat_exposure_days": 3,
        "absence_days": 8,
        "similar_heat_work": True,
    },
    {
        "worker_id": "W005",
        "name": "최지훈",
        "age": 35,
        "weight": 68.0,
        "sex": "male",
        "worker_status": "new",
        "heat_exposure_days": 2,
        "absence_days": 0,
        "similar_heat_work": False,
    },
]


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect(db_path=DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def normalize_worker_id(worker_id):
    normalized = str(worker_id).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{2,20}", normalized):
        raise ValueError("작업자 식별번호는 영문, 숫자, _, - 조합 2~20자여야 합니다.")
    return normalized


def normalize_worker_name(name):
    normalized = str(name).strip()
    if not normalized:
        raise ValueError("작업자 이름을 입력해야 합니다.")
    if len(normalized) > 40:
        raise ValueError("작업자 이름은 40자 이하여야 합니다.")
    return normalized


def normalize_active(active):
    return 1 if bool(active) else 0


def _create_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workers (
            worker_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            weight REAL NOT NULL,
            sex TEXT NOT NULL,
            worker_status TEXT NOT NULL,
            heat_exposure_days INTEGER NOT NULL,
            absence_days INTEGER NOT NULL,
            similar_heat_work INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            heart_rate INTEGER NOT NULL,
            wbgt REAL NOT NULL,
            vo2 REAL NOT NULL,
            hrr_ratio REAL NOT NULL,
            hr_max REAL NOT NULL,
            kcal_from_vo2 REAL NOT NULL,
            kcal_min REAL NOT NULL,
            metabolic_watts REAL NOT NULL,
            workload TEXT NOT NULL,
            risk TEXT NOT NULL,
            limit_type TEXT NOT NULL,
            limit_wbgt REAL NOT NULL,
            adjusted_wbgt REAL NOT NULL,
            margin REAL NOT NULL,
            acclimatized INTEGER NOT NULL,
            acclimatization_label TEXT NOT NULL,
            measured_at TEXT NOT NULL,
            FOREIGN KEY(worker_id) REFERENCES workers(worker_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_measurements_worker_time
        ON measurements(worker_id, measured_at DESC, id DESC)
        """
    )


def initialize_database(db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = now_iso()
    with closing(connect(db_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_tables(connection)
        for worker in DEFAULT_WORKERS:
            normalized = normalize_worker_payload(worker)
            connection.execute(
                """
                INSERT OR IGNORE INTO workers (
                    worker_id, name, age, weight, sex, worker_status,
                    heat_exposure_days, absence_days, similar_heat_work,
                    active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    normalized["worker_id"],
                    normalized["name"],
                    normalized["age"],
                    normalized["weight"],
                    normalized["sex"],
                    normalized["worker_status"],
                    normalized["heat_exposure_days"],
                    normalized["absence_days"],
                    1 if normalized["similar_heat_work"] else 0,
                    timestamp,
                    timestamp,
                ),
            )
        connection.commit()
    return db_path


def normalize_worker_payload(payload):
    worker_id = normalize_worker_id(payload["worker_id"])
    name = normalize_worker_name(payload["name"])
    age, weight, sex = validate_profile(
        payload.get("age", DEFAULT_PROFILE["age"]),
        payload.get("weight", DEFAULT_PROFILE["weight"]),
        payload.get("sex", DEFAULT_PROFILE["sex"]),
    )
    (
        worker_status,
        heat_exposure_days,
        absence_days,
        similar_heat_work,
    ) = validate_acclimatization_inputs(
        payload.get("worker_status", DEFAULT_ACCLIMATIZATION["worker_status"]),
        payload.get("heat_exposure_days", DEFAULT_ACCLIMATIZATION["heat_exposure_days"]),
        payload.get("absence_days", DEFAULT_ACCLIMATIZATION["absence_days"]),
        payload.get("similar_heat_work", DEFAULT_ACCLIMATIZATION["similar_heat_work"]),
    )
    return {
        "worker_id": worker_id,
        "name": name,
        "age": age,
        "weight": weight,
        "sex": sex,
        "worker_status": worker_status,
        "heat_exposure_days": heat_exposure_days,
        "absence_days": absence_days,
        "similar_heat_work": similar_heat_work,
        "active": normalize_active(payload.get("active", True)),
    }


def worker_from_row(row):
    if row is None:
        return None
    return {
        "worker_id": row["worker_id"],
        "name": row["name"],
        "age": row["age"],
        "weight": row["weight"],
        "sex": row["sex"],
        "worker_status": row["worker_status"],
        "heat_exposure_days": row["heat_exposure_days"],
        "absence_days": row["absence_days"],
        "similar_heat_work": bool(row["similar_heat_work"]),
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def measurement_from_row(row):
    if row is None:
        return None
    return {
        "measurement_id": row["id"],
        "heart_rate": row["heart_rate"],
        "wbgt": row["wbgt"],
        "vo2": row["vo2"],
        "hrr_ratio": row["hrr_ratio"],
        "hr_max": row["hr_max"],
        "kcal_from_vo2": row["kcal_from_vo2"],
        "kcal_min": row["kcal_min"],
        "metabolic_watts": row["metabolic_watts"],
        "workload": row["workload"],
        "risk": row["risk"],
        "limit_type": row["limit_type"],
        "limit_wbgt": row["limit_wbgt"],
        "adjusted_wbgt": row["adjusted_wbgt"],
        "margin": row["margin"],
        "acclimatized": bool(row["acclimatized"]),
        "acclimatization_label": row["acclimatization_label"],
        "measured_at": row["measured_at"],
    }


def list_workers(include_inactive=False, db_path=DB_PATH):
    initialize_database(db_path)
    sql = "SELECT * FROM workers"
    params = []
    if not include_inactive:
        sql += " WHERE active = ?"
        params.append(1)
    sql += " ORDER BY worker_id"
    rows = execute_fetchall(db_path, sql, params)
    return [worker_from_row(row) for row in rows]


def execute_fetchall(db_path, sql, params=()):
    with closing(connect(db_path)) as connection:
        return connection.execute(sql, params).fetchall()


def execute_fetchone(db_path, sql, params=()):
    with closing(connect(db_path)) as connection:
        return connection.execute(sql, params).fetchone()


def execute_write(db_path, sql, params=()):
    with closing(connect(db_path)) as connection:
        connection.execute(sql, params)
        connection.commit()


def execute_write_many(db_path, statements):
    with closing(connect(db_path)) as connection:
        for sql, params in statements:
            connection.execute(sql, params)
        connection.commit()
    return db_path


def get_worker(worker_id, db_path=DB_PATH):
    initialize_database(db_path)
    normalized_id = normalize_worker_id(worker_id)
    row = execute_fetchone(
        db_path,
        "SELECT * FROM workers WHERE worker_id = ?",
        (normalized_id,),
    )
    return worker_from_row(row)


def upsert_worker(
    worker_id,
    name,
    age,
    weight,
    sex,
    worker_status=DEFAULT_ACCLIMATIZATION["worker_status"],
    heat_exposure_days=DEFAULT_ACCLIMATIZATION["heat_exposure_days"],
    absence_days=DEFAULT_ACCLIMATIZATION["absence_days"],
    similar_heat_work=DEFAULT_ACCLIMATIZATION["similar_heat_work"],
    active=True,
    db_path=DB_PATH,
):
    initialize_database(db_path)
    payload = normalize_worker_payload(
        {
            "worker_id": worker_id,
            "name": name,
            "age": age,
            "weight": weight,
            "sex": sex,
            "worker_status": worker_status,
            "heat_exposure_days": heat_exposure_days,
            "absence_days": absence_days,
            "similar_heat_work": similar_heat_work,
            "active": active,
        }
    )
    timestamp = now_iso()
    with closing(connect(db_path)) as connection:
        existing = connection.execute(
            "SELECT created_at FROM workers WHERE worker_id = ?",
            (payload["worker_id"],),
        ).fetchone()
        created_at = existing["created_at"] if existing else timestamp
        connection.execute(
            """
            INSERT OR REPLACE INTO workers (
                worker_id, name, age, weight, sex, worker_status,
                heat_exposure_days, absence_days, similar_heat_work,
                active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["worker_id"],
                payload["name"],
                payload["age"],
                payload["weight"],
                payload["sex"],
                payload["worker_status"],
                payload["heat_exposure_days"],
                payload["absence_days"],
                1 if payload["similar_heat_work"] else 0,
                payload["active"],
                created_at,
                timestamp,
            ),
        )
        connection.commit()
    return get_worker(payload["worker_id"], db_path=db_path)


def calculate_worker_snapshot(worker, heart_rate, wbgt):
    heart_rate, wbgt = validate_measurement(heart_rate, wbgt)
    acclimatization = evaluate_acclimatization(
        worker_status=worker["worker_status"],
        heat_exposure_days=worker["heat_exposure_days"],
        absence_days=worker["absence_days"],
        similar_heat_work=worker["similar_heat_work"],
    )
    vo2, hrr_ratio, hr_max = estimate_vo2_by_hrr(
        age=worker["age"],
        sex=worker["sex"],
        heart_rate=heart_rate,
        resting_hr=DEFAULT_RESTING_HR,
    )
    kcal_from_vo2 = calculate_calories_from_vo2(vo2, worker["weight"])
    kcal_min = calculate_energy_keytel(
        heart_rate=heart_rate,
        weight=worker["weight"],
        age=worker["age"],
        sex=worker["sex"],
    )
    risk_result = calculate_heat_risk(
        wbgt=wbgt,
        kcal_min=kcal_min,
        acclimatized=acclimatization["acclimatized"],
        clothing_adjustment=DEFAULT_CLOTHING_ADJUSTMENT,
    )
    return {
        "heart_rate": heart_rate,
        "wbgt": wbgt,
        "vo2": vo2,
        "hrr_ratio": hrr_ratio,
        "hr_max": hr_max,
        "kcal_from_vo2": kcal_from_vo2,
        "kcal_min": kcal_min,
        "metabolic_watts": risk_result["metabolic_watts"],
        "workload": risk_result["workload"],
        "risk": risk_result["risk"],
        "limit_type": risk_result["limit_type"],
        "limit_wbgt": risk_result["limit_wbgt"],
        "adjusted_wbgt": risk_result["adjusted_wbgt"],
        "margin": risk_result["margin"],
        "acclimatized": acclimatization["acclimatized"],
        "acclimatization_label": acclimatization["status_label"],
    }


def save_measurement(worker_id, heart_rate, wbgt, measured_at=None, db_path=DB_PATH):
    initialize_database(db_path)
    worker = get_worker(worker_id, db_path=db_path)
    if worker is None or not worker["active"]:
        raise ValueError("활성 작업자를 찾을 수 없습니다.")
    snapshot = calculate_worker_snapshot(worker, heart_rate, wbgt)
    timestamp = measured_at or now_iso()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO measurements (
                worker_id, heart_rate, wbgt, vo2, hrr_ratio, hr_max,
                kcal_from_vo2, kcal_min, metabolic_watts, workload, risk,
                limit_type, limit_wbgt, adjusted_wbgt, margin, acclimatized,
                acclimatization_label, measured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                worker["worker_id"],
                snapshot["heart_rate"],
                snapshot["wbgt"],
                snapshot["vo2"],
                snapshot["hrr_ratio"],
                snapshot["hr_max"],
                snapshot["kcal_from_vo2"],
                snapshot["kcal_min"],
                snapshot["metabolic_watts"],
                snapshot["workload"],
                snapshot["risk"],
                snapshot["limit_type"],
                snapshot["limit_wbgt"],
                snapshot["adjusted_wbgt"],
                snapshot["margin"],
                1 if snapshot["acclimatized"] else 0,
                snapshot["acclimatization_label"],
                timestamp,
            ),
        )
        connection.commit()
    return get_latest_measurement(worker["worker_id"], db_path=db_path)


def get_latest_measurement(worker_id, db_path=DB_PATH):
    worker = get_worker(worker_id, db_path=db_path)
    if worker is None:
        return None
    row = execute_fetchone(
        db_path,
        """
        SELECT *
        FROM measurements
        WHERE worker_id = ?
        ORDER BY measured_at DESC, id DESC
        LIMIT 1
        """,
        (worker["worker_id"],),
    )
    measurement = measurement_from_row(row)
    if measurement is None:
        return {
            **worker,
            "has_measurement": False,
        }
    return {
        **worker,
        **measurement,
        "has_measurement": True,
    }


def list_latest_statuses(db_path=DB_PATH):
    workers = list_workers(include_inactive=False, db_path=db_path)
    return [
        get_latest_measurement(worker["worker_id"], db_path=db_path)
        for worker in workers
    ]
