import argparse

from acclimatization import WORKER_STATUS_LABELS, evaluate_acclimatization
from measurement_store import CURRENT_MEASUREMENT_PATH, read_measurement, write_measurement


def prompt_value(label):
    return input(f"{label}: ").strip()


def parse_args():
    parser = argparse.ArgumentParser(
        description="PC에서 온열 위험도 대시보드 측정값을 갱신합니다.",
    )
    parser.add_argument("--heart-rate", help="현재 심박수(bpm)")
    parser.add_argument("--wbgt", help="온열지수(WBGT)")
    parser.add_argument("--age", help="나이")
    parser.add_argument("--weight", help="체중(kg)")
    parser.add_argument("--sex", choices=("male", "female"), help="성별")
    parser.add_argument(
        "--worker-status",
        choices=tuple(WORKER_STATUS_LABELS),
        help="작업자 상태(existing, new, returning)",
    )
    parser.add_argument("--heat-exposure-days", help="최근 14일 유사 더위 작업일수")
    parser.add_argument("--absence-days", help="연속 부재일수")
    parser.add_argument(
        "--similar-heat-work",
        choices=("true", "false"),
        help="최근 작업 강도가 오늘 작업과 유사한지 여부",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    current = read_measurement()
    heart_rate = args.heart_rate or prompt_value("현재 심박수(bpm)")
    wbgt = args.wbgt or prompt_value("온열지수(WBGT)")
    age = args.age or current["age"]
    weight = args.weight or current["weight"]
    sex = args.sex or current["sex"]
    worker_status = args.worker_status or current["worker_status"]
    heat_exposure_days = args.heat_exposure_days or current["heat_exposure_days"]
    absence_days = args.absence_days or current["absence_days"]
    similar_heat_work = (
        current["similar_heat_work"]
        if args.similar_heat_work is None
        else args.similar_heat_work == "true"
    )

    try:
        payload = write_measurement(
            heart_rate,
            wbgt,
            age=age,
            weight=weight,
            sex=sex,
            worker_status=worker_status,
            heat_exposure_days=heat_exposure_days,
            absence_days=absence_days,
            similar_heat_work=similar_heat_work,
        )
        acclimatization = evaluate_acclimatization(
            worker_status=payload["worker_status"],
            heat_exposure_days=payload["heat_exposure_days"],
            absence_days=payload["absence_days"],
            similar_heat_work=payload["similar_heat_work"],
        )
    except ValueError as error:
        raise SystemExit(f"입력 오류: {error}") from error

    print("측정값을 저장했습니다.")
    print(f"심박수: {payload['heart_rate']} bpm")
    print(f"온열지수(WBGT): {payload['wbgt']:.1f}")
    print(f"프로필: {payload['age']}세 / {payload['weight']:g}kg / {payload['sex']}")
    print(
        f"순화 판정: {acclimatization['status_label']} "
        f"({acclimatization['limit_type']})"
    )
    print(f"저장 위치: {CURRENT_MEASUREMENT_PATH}")


if __name__ == "__main__":
    main()
