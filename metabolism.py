def estimate_vo2_by_hrr(age, sex, heart_rate, resting_hr=65, vo2max=None):
    """
    HRR(Heart Rate Reserve) 기반 VO2 추정.
    기존 heart_rate / HRmax 방식보다 안정시 심박수를 반영하므로 개인화 수준이 높음.
    """
    if age <= 0 or age > 120:
        raise ValueError("나이는 1~120 범위여야 합니다.")

    if heart_rate <= 0 or heart_rate > 220:
        raise ValueError("심박수는 1~220 범위여야 합니다.")

    if resting_hr <= 30 or resting_hr >= heart_rate:
        raise ValueError("안정시 심박수 값이 비정상적입니다.")

    sex = sex.lower()

    # Tanaka 계열 최대심박수 추정식
    hr_max = 208 - 0.7 * age

    if heart_rate > hr_max + 20:
        raise ValueError("심박수가 비정상적으로 높습니다.")

    hrr_ratio = (heart_rate - resting_hr) / (hr_max - resting_hr)
    hrr_ratio = max(0, min(hrr_ratio, 1))

    if vo2max is None:
        if sex == "male":
            vo2max = 42
        elif sex == "female":
            vo2max = 35
        else:
            raise ValueError("성별은 male 또는 female 이어야 합니다.")

    vo2_rest = 3.5
    vo2 = vo2_rest + hrr_ratio * (vo2max - vo2_rest)

    return vo2, hrr_ratio, hr_max


def calculate_calories_from_vo2(vo2, weight):
    """
    VO2 기반 kcal/min 계산.
    산소 1L 소비당 약 5 kcal로 환산.
    """
    if vo2 < 0:
        raise ValueError("VO2 값이 비정상적입니다.")

    if weight <= 0 or weight > 300:
        raise ValueError("체중은 1~300kg 범위여야 합니다.")

    oxygen_consumption_l_min = (vo2 * weight) / 1000
    return oxygen_consumption_l_min * 5


def calculate_energy_keytel(heart_rate, weight, age, sex):
    """
    Keytel et al. 계열 심박수 기반 에너지소비량 추정식.
    최종 위험도 계산에는 이 값을 우선 사용.
    """
    if heart_rate <= 0 or heart_rate > 220:
        raise ValueError("심박수는 1~220 범위여야 합니다.")

    if weight <= 0 or weight > 300:
        raise ValueError("체중은 1~300kg 범위여야 합니다.")

    if age <= 0 or age > 120:
        raise ValueError("나이는 1~120 범위여야 합니다.")

    sex = sex.lower()

    if sex == "male":
        ee_kj_min = (
            -55.0969
            + 0.6309 * heart_rate
            + 0.1988 * weight
            + 0.2017 * age
        )
    elif sex == "female":
        ee_kj_min = (
            -20.4022
            + 0.4472 * heart_rate
            - 0.1263 * weight
            + 0.074 * age
        )
    else:
        raise ValueError("성별은 male 또는 female 이어야 합니다.")

    ee_kcal_min = ee_kj_min / 4.184

    return max(0, ee_kcal_min)


def kcal_min_to_watts(kcal_min):
    """
    kcal/min을 대사율 W로 변환.
    1 kcal/min ≈ 69.78 W
    """
    if kcal_min < 0:
        raise ValueError("칼로리 값이 비정상적입니다.")

    return kcal_min * 69.78