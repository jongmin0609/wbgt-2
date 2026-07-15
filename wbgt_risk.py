import math

from metabolism import kcal_min_to_watts


def classify_workload_by_watts(metabolic_watts):
    """
    대사율 W 기준 작업강도 분류.
    기존 kcal/min 직접 분류보다 온열환경 기준과 연결하기 쉬움.
    """
    if metabolic_watts < 0:
        raise ValueError("대사율 값이 비정상적입니다.")

    if metabolic_watts < 200:
        return "저강도"
    elif metabolic_watts < 300:
        return "중강도"
    elif metabolic_watts < 415:
        return "고강도"
    else:
        return "매우 고강도"


def calculate_niosh_limit(metabolic_watts, acclimatized=True):
    """
    NIOSH RAL/REL 계열 WBGT 한계값 계산.
    acclimatized=True  → 순화 작업자 기준 REL
    acclimatized=False → 비순화 작업자 기준 RAL
    """
    if metabolic_watts <= 0:
        raise ValueError("대사율은 0보다 커야 합니다.")

    if acclimatized:
        return 56.7 - 11.5 * math.log10(metabolic_watts)
    else:
        return 59.9 - 14.1 * math.log10(metabolic_watts)


def niosh_limit_type(acclimatized):
    return "REL" if acclimatized else "RAL"


def classify_heat_risk_by_niosh(
    wbgt,
    metabolic_watts,
    acclimatized=True,
    clothing_adjustment=0.0,
):
    """
    실제 WBGT와 대사율 기반 WBGT 한계값의 차이를 이용해 위험도 분류.
    """
    if wbgt < 0 or wbgt > 60:
        raise ValueError("WBGT는 0~60℃ 범위여야 합니다.")

    if metabolic_watts <= 0:
        raise ValueError("대사율은 0보다 커야 합니다.")

    adjusted_wbgt = wbgt + clothing_adjustment
    limit_wbgt = calculate_niosh_limit(metabolic_watts, acclimatized)

    margin = limit_wbgt - adjusted_wbgt

    if margin >= 2.0:
        risk = "안전"
    elif margin >= 0:
        risk = "주의"
    elif margin >= -2.0:
        risk = "경고"
    else:
        risk = "위험"

    return {
        "risk": risk,
        "adjusted_wbgt": adjusted_wbgt,
        "limit_wbgt": limit_wbgt,
        "margin": margin,
    }


def calculate_heat_risk(
    wbgt,
    kcal_min,
    acclimatized=True,
    clothing_adjustment=0.0,
):
    """
    main.py에서 호출할 최종 통합 함수.

    입력:
    - WBGT
    - kcal/min

    내부 처리:
    - kcal/min → W 변환
    - W 기준 작업강도 분류
    - NIOSH 기준 WBGT 한계값 계산
    - 위험도 단계 산출
    """
    if kcal_min < 0:
        raise ValueError("칼로리 값이 비정상적입니다.")

    metabolic_watts = kcal_min_to_watts(kcal_min)
    workload = classify_workload_by_watts(metabolic_watts)

    risk_result = classify_heat_risk_by_niosh(
        wbgt=wbgt,
        metabolic_watts=metabolic_watts,
        acclimatized=acclimatized,
        clothing_adjustment=clothing_adjustment,
    )

    return {
        "risk": risk_result["risk"],
        "workload": workload,
        "metabolic_watts": metabolic_watts,
        "limit_type": niosh_limit_type(acclimatized),
        "adjusted_wbgt": risk_result["adjusted_wbgt"],
        "limit_wbgt": risk_result["limit_wbgt"],
        "margin": risk_result["margin"],
    }
