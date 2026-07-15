WORKER_STATUS_LABELS = {
    "existing": "기존 작업자",
    "new": "신규 작업자",
    "returning": "복귀 작업자",
}

DEFAULT_ACCLIMATIZATION = {
    "worker_status": "existing",
    "heat_exposure_days": 7,
    "absence_days": 0,
    "similar_heat_work": True,
}


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "y", "on"):
            return True
        if lowered in ("0", "false", "no", "n", "off"):
            return False
    return bool(value)


def validate_acclimatization_inputs(
    worker_status,
    heat_exposure_days,
    absence_days,
    similar_heat_work,
):
    normalized_status = str(worker_status).lower()
    if normalized_status not in WORKER_STATUS_LABELS:
        raise ValueError("작업자 상태는 existing, new, returning 중 하나여야 합니다.")

    try:
        normalized_heat_days = int(heat_exposure_days)
    except (TypeError, ValueError) as error:
        raise ValueError("최근 더운 환경 작업일수는 정수여야 합니다.") from error

    try:
        normalized_absence_days = int(absence_days)
    except (TypeError, ValueError) as error:
        raise ValueError("연속 부재일수는 정수여야 합니다.") from error

    if normalized_heat_days < 0 or normalized_heat_days > 14:
        raise ValueError("최근 더운 환경 작업일수는 0~14일 범위여야 합니다.")

    if normalized_absence_days < 0 or normalized_absence_days > 365:
        raise ValueError("연속 부재일수는 0~365일 범위여야 합니다.")

    return (
        normalized_status,
        normalized_heat_days,
        normalized_absence_days,
        normalize_bool(similar_heat_work),
    )


def evaluate_acclimatization(
    worker_status,
    heat_exposure_days,
    absence_days,
    similar_heat_work,
):
    (
        worker_status,
        heat_exposure_days,
        absence_days,
        similar_heat_work,
    ) = validate_acclimatization_inputs(
        worker_status,
        heat_exposure_days,
        absence_days,
        similar_heat_work,
    )

    reasons = []
    if heat_exposure_days < 7:
        reasons.append("유사한 더위 작업 노출이 7일 미만입니다.")
    if absence_days >= 7:
        reasons.append("더운 작업에서 1주 이상 떨어져 순화가 일부 손실됐을 수 있습니다.")
    if worker_status == "new":
        reasons.append("신규 작업자는 첫 1~2주 동안 점진적인 열 노출이 필요합니다.")
    elif worker_status == "returning":
        reasons.append("복귀 작업자는 최소 1주 동안 추가 보호가 필요합니다.")
    if not similar_heat_work:
        reasons.append("최근 작업 강도가 오늘 작업과 달라 순화 근거가 약합니다.")

    acclimatized = (
        heat_exposure_days >= 7
        and absence_days < 7
        and similar_heat_work
    )

    limit_type = "REL" if acclimatized else "RAL"
    status_label = "순화 작업자" if acclimatized else "비순화 작업자"
    if acclimatized:
        summary = "최근 7일 이상 유사한 더위 작업을 했고, 1주 이상 부재 기록이 없습니다."
        recommendation = "순화 작업자 기준 REL을 적용합니다."
        recommended_exposure_percent = 100
    else:
        summary = " ".join(reasons)
        recommendation = "비순화 작업자 기준 RAL을 적용하고, 노출 시간을 단계적으로 늘리세요."
        recommended_exposure_percent = min(100, max(20, (heat_exposure_days + 1) * 20))

    return {
        "acclimatized": acclimatized,
        "limit_type": limit_type,
        "status_label": status_label,
        "worker_status_label": WORKER_STATUS_LABELS[worker_status],
        "heat_exposure_days": heat_exposure_days,
        "absence_days": absence_days,
        "similar_heat_work": similar_heat_work,
        "summary": summary,
        "recommendation": recommendation,
        "recommended_exposure_percent": recommended_exposure_percent,
    }
