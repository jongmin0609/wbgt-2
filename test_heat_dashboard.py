import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from acclimatization import evaluate_acclimatization
from measurement_store import (
    read_measurement,
    validate_measurement,
    validate_profile,
    write_measurement,
)
from metabolism import (
    calculate_calories_from_vo2,
    calculate_energy_keytel,
    estimate_vo2_by_hrr,
)
from utils import RISK_GUIDANCE, get_risk_guidance, should_trigger_alert
from wbgt_risk import calculate_heat_risk
from worker_store import (
    get_latest_measurement,
    get_worker,
    initialize_database,
    list_latest_statuses,
    list_workers,
    save_measurement,
    upsert_worker,
)


class MetabolismTests(unittest.TestCase):
    def test_example_profile_produces_expected_vo2_and_calories(self):
        vo2, hrr_ratio, hr_max = estimate_vo2_by_hrr(
            age=25,
            sex="male",
            heart_rate=130,
        )

        self.assertAlmostEqual(vo2, 23.44, places=2)
        self.assertAlmostEqual(hrr_ratio, 0.52, places=2)
        self.assertAlmostEqual(hr_max, 190.5)
        self.assertAlmostEqual(calculate_calories_from_vo2(vo2, weight=70), 8.20, places=2)
        self.assertAlmostEqual(
            calculate_energy_keytel(
                heart_rate=130,
                weight=70,
                age=25,
                sex="male",
            ),
            10.97,
            places=2,
        )

    def test_profile_and_heart_rate_validation(self):
        with self.assertRaisesRegex(ValueError, "나이는"):
            estimate_vo2_by_hrr(age=0, sex="male", heart_rate=130)

        with self.assertRaisesRegex(ValueError, "심박수는"):
            estimate_vo2_by_hrr(age=25, sex="male", heart_rate=0)

        with self.assertRaisesRegex(ValueError, "비정상적으로"):
            estimate_vo2_by_hrr(age=25, sex="male", heart_rate=216)

        with self.assertRaisesRegex(ValueError, "성별은"):
            estimate_vo2_by_hrr(age=25, sex="unknown", heart_rate=130)

    def test_weight_validation(self):
        with self.assertRaisesRegex(ValueError, "체중은"):
            calculate_calories_from_vo2(vo2=30, weight=0)


class HeatRiskTests(unittest.TestCase):
    def test_example_measurement_is_high_workload_and_dangerous(self):
        result = calculate_heat_risk(wbgt=31.2, kcal_min=10.97)

        self.assertEqual(result["workload"], "매우 고강도")
        self.assertEqual(result["limit_type"], "REL")
        self.assertEqual(result["risk"], "위험")
        self.assertLess(result["margin"], -4.0)

    def test_unacclimatized_workers_use_more_restrictive_ral(self):
        rel_result = calculate_heat_risk(wbgt=26, kcal_min=5, acclimatized=True)
        ral_result = calculate_heat_risk(wbgt=26, kcal_min=5, acclimatized=False)

        self.assertEqual(rel_result["limit_type"], "REL")
        self.assertEqual(ral_result["limit_type"], "RAL")
        self.assertLess(ral_result["limit_wbgt"], rel_result["limit_wbgt"])
        self.assertLessEqual(ral_result["margin"], rel_result["margin"])

    def test_risk_thresholds_cover_dashboard_labels(self):
        self.assertEqual(calculate_heat_risk(wbgt=29.5, kcal_min=2)["risk"], "안전")
        self.assertEqual(calculate_heat_risk(wbgt=30.5, kcal_min=2)["risk"], "주의")
        self.assertEqual(calculate_heat_risk(wbgt=33.0, kcal_min=2)["risk"], "경고")
        self.assertEqual(calculate_heat_risk(wbgt=35.0, kcal_min=2)["risk"], "위험")
        self.assertEqual(calculate_heat_risk(wbgt=37.0, kcal_min=2)["risk"], "위험")

    def test_workload_thresholds_are_reported_from_metabolic_watts(self):
        self.assertEqual(calculate_heat_risk(wbgt=28, kcal_min=2)["workload"], "저강도")
        self.assertEqual(calculate_heat_risk(wbgt=28, kcal_min=3.5)["workload"], "중강도")
        self.assertEqual(calculate_heat_risk(wbgt=28, kcal_min=5)["workload"], "고강도")
        self.assertEqual(calculate_heat_risk(wbgt=28, kcal_min=6)["workload"], "매우 고강도")

    def test_heat_risk_rejects_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "WBGT"):
            calculate_heat_risk(wbgt=61, kcal_min=2)

        with self.assertRaisesRegex(ValueError, "칼로리"):
            calculate_heat_risk(wbgt=30, kcal_min=-1)


class GuidanceTests(unittest.TestCase):
    def test_every_risk_label_has_rest_action_water_control_and_tone(self):
        for risk in ("안전", "주의", "경고", "위험"):
            with self.subTest(risk=risk):
                guidance = get_risk_guidance(risk)

                expected = RISK_GUIDANCE[risk].copy()
                expected["context_notes"] = []
                self.assertEqual(guidance, expected)
                self.assertTrue(guidance["rest_time"])
                self.assertTrue(guidance["action_text"])
                self.assertTrue(guidance["action_items"])
                self.assertTrue(guidance["water_text"])
                self.assertTrue(guidance["control_text"])
                self.assertTrue(guidance["tone"])

    def test_guidance_keeps_context_notes_separate_from_response_items(self):
        guidance = get_risk_guidance(
            risk="경고",
            margin=-1.5,
            workload="고강도",
            acclimatized=False,
            limit_type="RAL",
        )

        self.assertIn("기준 WBGT를 1.5℃ 초과", guidance["context_notes"])
        self.assertIn(
            "고강도 작업이므로 작업 속도 저감, 인원 교대, 기계화 보조를 우선 검토",
            guidance["context_notes"],
        )
        self.assertIn("비순화 작업자이므로 더 긴 휴식과 단계적 노출 적용", guidance["context_notes"])
        self.assertIn("적용 기준: NIOSH RAL", guidance["context_notes"])
        self.assertNotIn("NIOSH RAL", " ".join(guidance["action_items"]))

    def test_unknown_risk_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "알 수 없는"):
            get_risk_guidance("미정")

    def test_manager_alert_starts_at_danger_level(self):
        self.assertFalse(should_trigger_alert("안전"))
        self.assertFalse(should_trigger_alert("주의"))
        self.assertTrue(should_trigger_alert("경고"))
        self.assertTrue(should_trigger_alert("위험"))


class AcclimatizationTests(unittest.TestCase):
    def test_existing_worker_with_recent_similar_heat_work_is_acclimatized(self):
        result = evaluate_acclimatization(
            worker_status="existing",
            heat_exposure_days=7,
            absence_days=0,
            similar_heat_work=True,
        )

        self.assertTrue(result["acclimatized"])
        self.assertEqual(result["limit_type"], "REL")
        self.assertEqual(result["status_label"], "순화 작업자")

    def test_new_or_returning_worker_is_unacclimatized_until_enough_exposure(self):
        new_worker = evaluate_acclimatization(
            worker_status="new",
            heat_exposure_days=3,
            absence_days=0,
            similar_heat_work=True,
        )
        returning_worker = evaluate_acclimatization(
            worker_status="returning",
            heat_exposure_days=3,
            absence_days=8,
            similar_heat_work=True,
        )

        self.assertFalse(new_worker["acclimatized"])
        self.assertFalse(returning_worker["acclimatized"])
        self.assertEqual(new_worker["limit_type"], "RAL")
        self.assertEqual(returning_worker["limit_type"], "RAL")

    def test_non_similar_recent_work_does_not_count_as_acclimatized(self):
        result = evaluate_acclimatization(
            worker_status="existing",
            heat_exposure_days=10,
            absence_days=0,
            similar_heat_work=False,
        )

        self.assertFalse(result["acclimatized"])
        self.assertEqual(result["limit_type"], "RAL")

    def test_acclimatization_validation_rejects_bad_ranges(self):
        with self.assertRaisesRegex(ValueError, "작업자 상태"):
            evaluate_acclimatization("unknown", 7, 0, True)

        with self.assertRaisesRegex(ValueError, "0~14일"):
            evaluate_acclimatization("existing", 15, 0, True)

        with self.assertRaisesRegex(ValueError, "0~365일"):
            evaluate_acclimatization("existing", 7, -1, True)


class MeasurementStoreTests(unittest.TestCase):
    def test_written_pc_measurement_is_shared_from_json(self):
        with TemporaryDirectory() as temp_dir:
            measurement_path = Path(temp_dir) / "current_measurement.json"
            missing_sample_path = Path(temp_dir) / "missing.csv"

            write_measurement(
                heart_rate=144,
                wbgt=32.4,
                age=38,
                weight=82.5,
                sex="female",
                worker_status="returning",
                heat_exposure_days=3,
                absence_days=9,
                similar_heat_work=True,
                measurement_path=measurement_path,
                updated_at="2026-05-23T11:20:30+09:00",
            )
            measurement = read_measurement(measurement_path, missing_sample_path)

        self.assertEqual(measurement["heart_rate"], 144)
        self.assertEqual(measurement["wbgt"], 32.4)
        self.assertEqual(measurement["age"], 38)
        self.assertEqual(measurement["weight"], 82.5)
        self.assertEqual(measurement["sex"], "female")
        self.assertEqual(measurement["worker_status"], "returning")
        self.assertEqual(measurement["heat_exposure_days"], 3)
        self.assertEqual(measurement["absence_days"], 9)
        self.assertTrue(measurement["similar_heat_work"])
        self.assertEqual(measurement["source"], "computer")
        self.assertEqual(measurement["updated_at"], "2026-05-23T11:20:30+09:00")

    def test_sample_measurement_is_used_before_pc_input_exists(self):
        with TemporaryDirectory() as temp_dir:
            sample_path = Path(temp_dir) / "sample.csv"
            sample_path.write_text(
                "time,heart_rate,wbgt\n10:01,121,30.4\n10:02,133,31.8\n",
                encoding="utf-8",
            )
            measurement = read_measurement(
                Path(temp_dir) / "current_measurement.json",
                sample_path,
            )

        self.assertEqual(measurement["heart_rate"], 133)
        self.assertEqual(measurement["wbgt"], 31.8)
        self.assertEqual(measurement["age"], 25)
        self.assertEqual(measurement["weight"], 70.0)
        self.assertEqual(measurement["sex"], "male")
        self.assertEqual(measurement["worker_status"], "existing")
        self.assertEqual(measurement["heat_exposure_days"], 7)
        self.assertEqual(measurement["absence_days"], 0)
        self.assertTrue(measurement["similar_heat_work"])
        self.assertEqual(measurement["source"], "sample")
        self.assertEqual(measurement["updated_at"], "10:02")

    def test_external_measurement_validation_rejects_bad_ranges(self):
        with self.assertRaisesRegex(ValueError, "심박수"):
            validate_measurement(0, 31.2)

        with self.assertRaisesRegex(ValueError, "WBGT"):
            validate_measurement(130, 61)

        with self.assertRaisesRegex(ValueError, "나이"):
            validate_profile(0, 70, "male")

        with self.assertRaisesRegex(ValueError, "체중"):
            validate_profile(25, 0, "male")

        with self.assertRaisesRegex(ValueError, "성별"):
            validate_profile(25, 70, "unknown")

    def test_changed_profile_changes_heat_risk_calculation_inputs(self):
        male_kcal = calculate_energy_keytel(
            heart_rate=130,
            weight=70,
            age=25,
            sex="male",
        )
        female_kcal = calculate_energy_keytel(
            heart_rate=130,
            weight=40,
            age=25,
            sex="female",
        )

        self.assertGreater(male_kcal, female_kcal)
        self.assertEqual(
            calculate_heat_risk(wbgt=28, kcal_min=male_kcal)["risk"],
            "위험",
        )
        self.assertEqual(
            calculate_heat_risk(wbgt=28, kcal_min=female_kcal)["risk"],
            "위험",
        )


class WorkerStoreTests(unittest.TestCase):
    def test_default_workers_are_seeded(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workers.db"
            initialize_database(db_path)
            workers = list_workers(db_path=db_path)

        self.assertEqual(len(workers), 5)
        self.assertEqual(workers[0]["worker_id"], "W001")
        self.assertEqual(workers[0]["name"], "김철수")
        self.assertTrue(workers[0]["active"])

    def test_worker_measurement_is_calculated_and_listed(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workers.db"
            initialize_database(db_path)
            saved = save_measurement(
                "W001",
                heart_rate=130,
                wbgt=31.2,
                measured_at="2026-07-15T09:00:00+09:00",
                db_path=db_path,
            )
            latest = get_latest_measurement("W001", db_path=db_path)
            statuses = list_latest_statuses(db_path=db_path)

        self.assertTrue(saved["has_measurement"])
        self.assertEqual(saved["name"], "김철수")
        self.assertEqual(saved["risk"], latest["risk"])
        self.assertEqual(saved["workload"], "매우 고강도")
        self.assertGreater(saved["metabolic_watts"], 400)
        self.assertEqual(len(statuses), 5)
        self.assertTrue(statuses[0]["has_measurement"])

    def test_profile_update_changes_central_worker_profile(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "workers.db"
            initialize_database(db_path)
            upsert_worker(
                "W001",
                name="김철수",
                age=40,
                weight=80,
                sex="female",
                worker_status="new",
                heat_exposure_days=2,
                absence_days=0,
                similar_heat_work=True,
                db_path=db_path,
            )
            worker = get_worker("W001", db_path=db_path)
            saved = save_measurement("W001", 130, 30.0, db_path=db_path)

        self.assertEqual(worker["age"], 40)
        self.assertEqual(worker["weight"], 80.0)
        self.assertEqual(worker["sex"], "female")
        self.assertFalse(saved["acclimatized"])
        self.assertEqual(saved["limit_type"], "RAL")


if __name__ == "__main__":
    unittest.main()
