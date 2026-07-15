from datetime import datetime
from html import escape
import json

import streamlit as st
import streamlit.components.v1 as components

from acclimatization import WORKER_STATUS_LABELS, evaluate_acclimatization
from utils import get_risk_guidance, should_trigger_alert
from worker_store import (
    DB_PATH,
    get_latest_measurement,
    get_worker,
    initialize_database,
    list_latest_statuses,
    list_workers,
    save_measurement,
    upsert_worker,
)


SEX_LABELS = {
    "male": "남성",
    "female": "여성",
}
RISK_PRIORITY = {
    "위험": 4,
    "경고": 3,
    "주의": 2,
    "안전": 1,
}
LOCAL_WORKER_KEY = "wgbt-selected-worker-id"


def query_value(name):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def go_to(**params):
    st.query_params.clear()
    for key, value in params.items():
        if value is not None:
            st.query_params[key] = str(value)
    st.rerun()


def sex_label(sex):
    return SEX_LABELS.get(sex, sex)


def bool_label(value):
    return "예" if value else "아니오"


def format_time(value):
    if not value:
        return "아직 측정 없음"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def age_of_measurement(value):
    if not value:
        return None
    try:
        measured_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    now = datetime.now().astimezone()
    if measured_at.tzinfo is None:
        measured_at = measured_at.astimezone()
    return max(0, int((now - measured_at).total_seconds()))


def age_text(value):
    seconds = age_of_measurement(value)
    if seconds is None:
        return "갱신 전"
    if seconds < 60:
        return f"{seconds}초 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    return f"{hours}시간 전"


def is_stale(value, stale_seconds=300):
    seconds = age_of_measurement(value)
    return seconds is None or seconds > stale_seconds


def risk_tone(risk):
    return {
        "안전": "safe",
        "주의": "caution",
        "경고": "warning",
        "위험": "danger",
    }.get(risk, "empty")


def worker_label(worker):
    return f"{worker['worker_id']} · {worker['name']}"


def get_guidance(status):
    return get_risk_guidance(
        risk=status["risk"],
        margin=status["margin"],
        workload=status["workload"],
        acclimatized=status["acclimatized"],
        limit_type=status["limit_type"],
    )


def render_browser_worker_script(worker_id=None, clear=False, redirect=False):
    worker_json = json.dumps(worker_id, ensure_ascii=False)
    key_json = json.dumps(LOCAL_WORKER_KEY)
    components.html(
        f"""
        <script>
        (function() {{
            const key = {key_json};
            const workerId = {worker_json};
            try {{
                const storage = window.parent.localStorage;
                const params = new URLSearchParams(window.parent.location.search);
                if ({str(clear).lower()}) {{
                    storage.removeItem(key);
                    return;
                }}
                if (workerId) {{
                    storage.setItem(key, workerId);
                }}
                if ({str(redirect).lower()} && !params.get("worker_id") && !params.get("view")) {{
                    const saved = storage.getItem(key);
                    if (saved) {{
                        params.set("worker_id", saved);
                        window.parent.location.search = params.toString();
                    }}
                }}
            }} catch (_) {{}}
        }})();
        </script>
        """,
        height=0,
    )


def render_device_alert_controls(status, guidance):
    payload = {
        "workerId": status["worker_id"],
        "workerName": status["name"],
        "risk": status["risk"],
        "managerAlert": should_trigger_alert(status["risk"]),
        "heartRate": status["heart_rate"],
        "wbgt": status["wbgt"],
        "updatedAt": status["measured_at"],
        "key": (
            f"{status['worker_id']}-{status['measured_at']}-"
            f"{status['risk']}-{status['heart_rate']}-{status['wbgt']}"
        ),
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    components.html(
        f"""
        <div id="alert-root"></div>
        <script>
        const payload = {payload_json};
        const root = document.getElementById("alert-root");
        const enabledKey = "wgbt-device-alert-enabled";
        const lastAlertKey = "wgbt-last-alert-key-" + payload.workerId;

        function readStorage(key) {{
            try {{ return window.parent.localStorage.getItem(key); }}
            catch (_) {{ return null; }}
        }}

        function writeStorage(key, value) {{
            try {{ window.parent.localStorage.setItem(key, value); }}
            catch (_) {{}}
        }}

        function notificationsSupported() {{
            return "Notification" in window && window.isSecureContext;
        }}

        function vibrate(pattern) {{
            if ("vibrate" in navigator) {{
                try {{ navigator.vibrate(pattern); }} catch (_) {{}}
            }}
        }}

        function playAlertSound() {{
            try {{
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (!AudioContext) return;
                const context = new AudioContext();
                const gain = context.createGain();
                gain.gain.setValueAtTime(0.0001, context.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.22, context.currentTime + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.95);
                gain.connect(context.destination);
                [0, 0.28, 0.56].forEach((offset) => {{
                    const oscillator = context.createOscillator();
                    oscillator.type = "sine";
                    oscillator.frequency.setValueAtTime(880, context.currentTime + offset);
                    oscillator.connect(gain);
                    oscillator.start(context.currentTime + offset);
                    oscillator.stop(context.currentTime + offset + 0.18);
                }});
            }} catch (_) {{}}
        }}

        function sendBrowserNotification() {{
            if (!notificationsSupported() || Notification.permission !== "granted") return;
            try {{
                new Notification("온열 위험도 알람", {{
                    body: `${{payload.workerName}} · ${{payload.risk}} 단계입니다. 심박수 ${{payload.heartRate}} bpm, WBGT ${{Number(payload.wbgt).toFixed(1)}}`,
                    tag: "wgbt-risk-alert-" + payload.workerId,
                    renotify: true,
                }});
            }} catch (_) {{}}
        }}

        async function enableAlerts() {{
            writeStorage(enabledKey, "true");
            if (notificationsSupported() && Notification.permission === "default") {{
                try {{ await Notification.requestPermission(); }} catch (_) {{}}
            }}
            vibrate([80]);
            playAlertSound();
            render();
            maybeTriggerAlert(true);
        }}

        function maybeTriggerAlert(force=false) {{
            const enabled = readStorage(enabledKey) === "true";
            if (!payload.managerAlert || !enabled) return;
            const previousKey = readStorage(lastAlertKey);
            if (!force && previousKey === payload.key) return;
            writeStorage(lastAlertKey, payload.key);
            vibrate([450, 160, 450, 160, 450]);
            playAlertSound();
            sendBrowserNotification();
        }}

        function statusText() {{
            const enabled = readStorage(enabledKey) === "true";
            if (!enabled) return "알림을 받으려면 이 기기에서 한 번 활성화하세요.";
            if (!notificationsSupported()) return "소리와 진동 알림 활성화됨 · OS 푸시는 HTTPS에서만 가능";
            if (Notification.permission === "granted") return "브라우저 알림, 소리, 진동 활성화됨";
            if (Notification.permission === "denied") return "브라우저 알림 차단됨 · 소리와 진동만 시도";
            return "소리와 진동 활성화됨 · 브라우저 알림 권한 대기";
        }}

        function render() {{
            const enabled = readStorage(enabledKey) === "true";
            const riskMessage = payload.managerAlert
                ? `${{payload.workerName}} 작업자 ${{payload.risk}} 단계 감지됨`
                : "경고 이상 단계에서만 알림을 울립니다.";
            root.innerHTML = `
                <style>
                    body {{ margin: 0; font-family: sans-serif; }}
                    .device-alert {{
                        background: ${{payload.managerAlert ? "#fff1f0" : "#ffffff"}};
                        border: 1px solid ${{payload.managerAlert ? "#b42318" : "#d7dee7"}};
                        border-radius: 8px;
                        box-sizing: border-box;
                        color: #101828;
                        padding: 12px 14px;
                    }}
                    .device-alert p {{
                        color: #526070;
                        font-size: 13px;
                        margin: 0 0 8px;
                    }}
                    .device-alert strong {{
                        color: ${{payload.managerAlert ? "#7a271a" : "#101828"}};
                        display: block;
                        font-size: 15px;
                        line-height: 1.4;
                        margin-bottom: 10px;
                    }}
                    .device-alert button {{
                        background: #101828;
                        border: 0;
                        border-radius: 6px;
                        color: white;
                        cursor: pointer;
                        font-size: 14px;
                        font-weight: 700;
                        min-height: 40px;
                        padding: 0 14px;
                        width: 100%;
                    }}
                    .device-alert button.enabled {{
                        background: #137a45;
                    }}
                </style>
                <section class="device-alert" aria-live="polite">
                    <p>작업자 기기 알림</p>
                    <strong>${{riskMessage}} · ${{statusText()}}</strong>
                    <button id="enable-alerts" class="${{enabled ? "enabled" : ""}}">
                        ${{enabled ? "알림 활성화됨" : "알림 활성화"}}
                    </button>
                </section>
            `;
            document.getElementById("enable-alerts").addEventListener("click", enableAlerts);
        }}

        render();
        maybeTriggerAlert(false);
        </script>
        """,
        height=132,
    )


def render_css():
    st.markdown(
        """
        <style>
            :root {
                --ink: #101828;
                --muted: #526070;
                --line: #d7dee7;
                --surface: #ffffff;
                --canvas: #f4f7f9;
                --safe: #137a45;
                --caution: #b7791f;
                --warning: #b45309;
                --danger: #b42318;
                --accent: #0f766e;
            }
            .stApp {
                background: var(--canvas);
                color: var(--ink);
            }
            [data-testid="stHeader"] {
                background: transparent;
            }
            .block-container {
                max-width: 1180px;
                padding-top: 1.4rem;
                padding-bottom: 2rem;
            }
            h1, h2, h3, p {
                letter-spacing: 0;
            }
            .topbar {
                border-bottom: 1px solid var(--line);
                margin-bottom: 1rem;
                padding-bottom: 0.9rem;
            }
            .topbar p {
                color: var(--muted);
                font-size: 0.95rem;
                margin: 0 0 0.25rem;
            }
            .topbar h1 {
                color: var(--ink);
                font-size: clamp(1.7rem, 4vw, 2.5rem);
                line-height: 1.15;
                margin: 0;
            }
            .topbar span {
                color: var(--muted);
                display: block;
                line-height: 1.55;
                margin-top: 0.55rem;
            }
            .summary-grid {
                display: grid;
                gap: 0.75rem;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                margin: 1rem 0;
            }
            .summary-card,
            .worker-card,
            .detail-card,
            .risk-panel,
            .status-band {
                background: var(--surface);
                border: 1px solid var(--line);
                border-radius: 8px;
                box-sizing: border-box;
            }
            .summary-card {
                min-height: 86px;
                padding: 0.85rem;
            }
            .summary-card p,
            .detail-card p {
                color: var(--muted);
                font-size: 0.86rem;
                margin: 0 0 0.35rem;
            }
            .summary-card strong {
                color: var(--ink);
                display: block;
                font-size: 1.55rem;
                line-height: 1.1;
            }
            .status-band {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 0.6rem;
                justify-content: space-between;
                margin-bottom: 1rem;
                padding: 0.8rem 0.95rem;
            }
            .status-band strong {
                color: var(--ink);
            }
            .status-band span {
                color: var(--muted);
                font-size: 0.92rem;
            }
            .worker-grid {
                display: grid;
                gap: 0.75rem;
                grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
                margin: 1rem 0;
            }
            .worker-card {
                border-left: 5px solid #98a2b3;
                min-height: 210px;
                padding: 0.95rem;
            }
            .worker-card.safe { border-left-color: var(--safe); }
            .worker-card.caution { border-left-color: var(--caution); }
            .worker-card.warning { border-left-color: var(--warning); }
            .worker-card.danger { border-left-color: var(--danger); }
            .worker-card.empty { border-left-color: #667085; }
            .worker-card header {
                align-items: flex-start;
                display: flex;
                gap: 0.75rem;
                justify-content: space-between;
            }
            .worker-card h3 {
                color: var(--ink);
                font-size: 1.05rem;
                line-height: 1.25;
                margin: 0;
            }
            .worker-card p {
                color: var(--muted);
                font-size: 0.88rem;
                line-height: 1.45;
                margin: 0.35rem 0 0;
            }
            .risk-pill {
                border-radius: 999px;
                color: white;
                font-size: 0.8rem;
                font-weight: 800;
                padding: 0.25rem 0.55rem;
                white-space: nowrap;
            }
            .risk-pill.safe { background: var(--safe); }
            .risk-pill.caution { background: var(--caution); }
            .risk-pill.warning { background: var(--warning); }
            .risk-pill.danger { background: var(--danger); }
            .risk-pill.empty { background: #667085; }
            .worker-metrics {
                display: grid;
                gap: 0.5rem;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                margin-top: 0.85rem;
            }
            .worker-metrics div {
                border-top: 1px solid var(--line);
                padding-top: 0.55rem;
            }
            .worker-metrics span {
                color: var(--muted);
                display: block;
                font-size: 0.76rem;
            }
            .worker-metrics strong {
                color: var(--ink);
                display: block;
                font-size: 0.95rem;
                margin-top: 0.12rem;
            }
            .risk-panel {
                border-left: 6px solid var(--safe);
                margin: 1rem 0;
                padding: 1rem;
            }
            .risk-panel.safe { border-left-color: var(--safe); }
            .risk-panel.caution { border-left-color: var(--caution); }
            .risk-panel.warning { border-left-color: var(--warning); }
            .risk-panel.danger { border-left-color: var(--danger); }
            .risk-panel p {
                color: var(--muted);
                margin: 0 0 0.25rem;
            }
            .risk-panel h2 {
                color: var(--ink);
                font-size: 2rem;
                line-height: 1.1;
                margin: 0 0 0.6rem;
            }
            .risk-panel strong {
                display: block;
                line-height: 1.5;
            }
            .detail-grid {
                display: grid;
                gap: 0.75rem;
                grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                margin: 1rem 0;
            }
            .detail-card {
                min-height: 88px;
                padding: 0.85rem;
            }
            .detail-card strong {
                color: var(--ink);
                display: block;
                font-size: 1rem;
                line-height: 1.35;
            }
            .notice {
                color: var(--muted);
                font-size: 0.9rem;
                line-height: 1.55;
                margin-top: 1rem;
            }
            div[data-testid="stForm"] {
                background: var(--surface);
                border: 1px solid var(--line);
                border-radius: 8px;
                padding: 1rem;
            }
            div[data-testid="stFormSubmitButton"] button {
                min-height: 2.7rem;
                width: 100%;
            }
            @media (max-width: 780px) {
                .summary-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
                .block-container {
                    padding-left: 1rem;
                    padding-right: 1rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(kicker, title, subtitle):
    st.markdown(
        f"""
        <header class="topbar">
            <p>{escape(kicker)}</p>
            <h1>{escape(title)}</h1>
            <span>{escape(subtitle)}</span>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_entry_page():
    if query_value("reset_worker") == "1":
        render_browser_worker_script(clear=True)
        st.info("이 기기에 저장된 작업자 선택을 초기화했습니다. 다시 작업자를 선택하세요.")
    else:
        render_browser_worker_script(redirect=True)

    workers = list_workers()
    render_header(
        "작업자 선택",
        "온열 위험도 중앙 입력",
        "작업자는 처음 한 번 이름을 선택하면 이 브라우저가 기본 작업자를 기억합니다.",
    )

    with st.form("worker-start-form"):
        selected_id = st.selectbox(
            "작업자",
            options=[worker["worker_id"] for worker in workers],
            format_func=lambda worker_id: worker_label(
                next(worker for worker in workers if worker["worker_id"] == worker_id)
            ),
        )
        submitted = st.form_submit_button("이 작업자로 시작", type="primary")

    if submitted:
        go_to(worker_id=selected_id)

    if st.button("관리자 전체 현황 열기"):
        go_to(view="manager")

    st.markdown(
        f"""
        <p class="notice">
            관리자 화면 주소: <strong>?view=manager</strong><br>
            작업자 화면은 선택한 브라우저의 저장공간에 식별번호를 보관하므로,
            같은 휴대폰/같은 브라우저로 다시 접속하면 기본 작업자로 자동 이동합니다.
            현재 DB 파일: {escape(str(DB_PATH))}
        </p>
        """,
        unsafe_allow_html=True,
    )


def render_measurement_form(worker, latest):
    default_heart_rate = latest["heart_rate"] if latest and latest.get("has_measurement") else 130
    default_wbgt = latest["wbgt"] if latest and latest.get("has_measurement") else 31.0

    with st.form(f"measurement-form-{worker['worker_id']}"):
        st.subheader("측정값 입력")
        columns = st.columns(2)
        with columns[0]:
            heart_rate = st.number_input(
                "현재 심박수",
                min_value=66,
                max_value=220,
                value=int(default_heart_rate),
                step=1,
                help="단위: bpm. HRR 계산을 위해 기본 안정시 심박수 65 bpm보다 큰 값부터 입력합니다.",
            )
        with columns[1]:
            wbgt = st.number_input(
                "온열지수 (WBGT)",
                min_value=0.0,
                max_value=60.0,
                value=float(default_wbgt),
                step=0.1,
                format="%.1f",
            )
        submitted = st.form_submit_button("중앙서버로 전송", type="primary")

    if submitted:
        try:
            saved = save_measurement(worker["worker_id"], heart_rate, wbgt)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(
                f"{saved['name']} 작업자 측정값 저장 완료: "
                f"{saved['heart_rate']} bpm / WBGT {saved['wbgt']:.1f} / {saved['risk']}"
            )
            st.rerun()


@st.experimental_fragment(run_every=2)
def render_worker_live_dashboard(worker_id):
    status = get_latest_measurement(worker_id)
    if status is None:
        st.error("작업자 정보를 찾을 수 없습니다.")
        return

    if not status.get("has_measurement"):
        st.markdown(
            f"""
            <section class="status-band">
                <strong>{escape(worker_label(status))}</strong>
                <span>아직 전송된 측정값이 없습니다.</span>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return

    guidance = get_guidance(status)
    render_device_alert_controls(status, guidance)

    st.markdown(
        f"""
        <section class="status-band">
            <strong>{escape(worker_label(status))}</strong>
            <span>최근 갱신 {escape(age_text(status["measured_at"]))} · {escape(format_time(status["measured_at"]))}</span>
        </section>
        <section class="risk-panel {escape(risk_tone(status["risk"]))}">
            <p>현재 위험도 단계</p>
            <h2>{escape(status["risk"])}</h2>
            <strong>{escape(guidance["action_text"])}</strong>
        </section>
        <section class="detail-grid">
            <article class="detail-card">
                <p>심박수</p>
                <strong>{status["heart_rate"]} bpm</strong>
            </article>
            <article class="detail-card">
                <p>WBGT</p>
                <strong>{status["wbgt"]:.1f} ℃</strong>
            </article>
            <article class="detail-card">
                <p>작업강도</p>
                <strong>{escape(status["workload"])}</strong>
            </article>
            <article class="detail-card">
                <p>권장 휴식</p>
                <strong>{escape(guidance["rest_time"])}</strong>
            </article>
            <article class="detail-card">
                <p>VO2 추정값</p>
                <strong>{status["vo2"]:.2f} ml/kg/min</strong>
            </article>
            <article class="detail-card">
                <p>Keytel 칼로리</p>
                <strong>{status["kcal_min"]:.2f} kcal/min</strong>
            </article>
            <article class="detail-card">
                <p>대사율</p>
                <strong>{status["metabolic_watts"]:.0f} W</strong>
            </article>
            <article class="detail-card">
                <p>기준 여유</p>
                <strong>{status["margin"]:.1f} ℃</strong>
            </article>
            <article class="detail-card">
                <p>순화 판정</p>
                <strong>{escape(status["acclimatization_label"])} / {escape(status["limit_type"])}</strong>
            </article>
            <article class="detail-card">
                <p>수분 섭취</p>
                <strong>{escape(guidance["water_text"])}</strong>
            </article>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if guidance["context_notes"]:
        st.info(" · ".join(guidance["context_notes"]))


def render_worker_page(worker_id):
    worker = get_worker(worker_id)
    if worker is None or not worker["active"]:
        render_header(
            "작업자 화면",
            "작업자를 찾을 수 없습니다",
            "관리자 화면에서 작업자 식별번호가 등록되어 있는지 확인하세요.",
        )
        if st.button("작업자 선택으로 돌아가기"):
            go_to(reset_worker=1)
        return

    render_browser_worker_script(worker["worker_id"])
    render_header(
        "작업자 개인 대시보드",
        worker_label(worker),
        "이 브라우저는 현재 작업자를 기본값으로 기억합니다. 심박수와 WBGT만 입력하면 중앙서버가 위험도를 계산합니다.",
    )

    columns = st.columns([1, 1, 1])
    with columns[0]:
        if st.button("관리자 화면"):
            go_to(view="manager")
    with columns[1]:
        if st.button("다른 작업자 선택"):
            go_to(reset_worker=1)
    with columns[2]:
        st.caption(
            f"고정 프로필: {worker['age']}세 / {worker['weight']:g}kg / {sex_label(worker['sex'])}"
        )

    latest = get_latest_measurement(worker["worker_id"])
    render_measurement_form(worker, latest)
    render_worker_live_dashboard(worker["worker_id"])


def render_summary_cards(statuses):
    measured = [status for status in statuses if status.get("has_measurement")]
    alerts = [
        status
        for status in measured
        if status["risk"] in ("경고", "위험")
    ]
    stale = [
        status
        for status in statuses
        if (not status.get("has_measurement")) or is_stale(status.get("measured_at"))
    ]
    highest = "미측정"
    if measured:
        highest = max(measured, key=lambda row: RISK_PRIORITY.get(row["risk"], 0))["risk"]
    st.markdown(
        f"""
        <section class="summary-grid">
            <article class="summary-card">
                <p>활성 작업자</p>
                <strong>{len(statuses)}</strong>
            </article>
            <article class="summary-card">
                <p>경고 이상</p>
                <strong>{len(alerts)}</strong>
            </article>
            <article class="summary-card">
                <p>갱신 지연/미측정</p>
                <strong>{len(stale)}</strong>
            </article>
            <article class="summary-card">
                <p>최고 위험도</p>
                <strong>{escape(highest)}</strong>
            </article>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_worker_cards(statuses):
    sorted_statuses = sorted(
        statuses,
        key=lambda row: (
            RISK_PRIORITY.get(row.get("risk"), 0) if row.get("has_measurement") else -1,
            row.get("measured_at") or "",
        ),
        reverse=True,
    )
    cards = []
    for status in sorted_statuses:
        has_measurement = status.get("has_measurement")
        risk = status["risk"] if has_measurement else "미측정"
        tone = risk_tone(status["risk"]) if has_measurement else "empty"
        updated = age_text(status.get("measured_at"))
        stale_badge = " · 갱신 지연" if is_stale(status.get("measured_at")) else ""
        metrics = {
            "심박수": f"{status['heart_rate']} bpm" if has_measurement else "-",
            "WBGT": f"{status['wbgt']:.1f} ℃" if has_measurement else "-",
            "작업강도": status["workload"] if has_measurement else "-",
            "대사율": f"{status['metabolic_watts']:.0f} W" if has_measurement else "-",
        }
        metric_markup = "".join(
            f"<div><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
            for label, value in metrics.items()
        )
        cards.append(
            f"""
            <article class="worker-card {escape(tone)}">
                <header>
                    <div>
                        <h3>{escape(worker_label(status))}</h3>
                        <p>{status['age']}세 / {status['weight']:g}kg / {escape(sex_label(status['sex']))}</p>
                    </div>
                    <span class="risk-pill {escape(tone)}">{escape(risk)}</span>
                </header>
                <p>최근 갱신: {escape(updated)}{escape(stale_badge)}</p>
                <div class="worker-metrics">{metric_markup}</div>
            </article>
            """
        )
    st.markdown(
        f"<section class=\"worker-grid\">{''.join(cards)}</section>",
        unsafe_allow_html=True,
    )


def render_status_table(statuses):
    rows = []
    for status in statuses:
        rows.append(
            {
                "식별번호": status["worker_id"],
                "이름": status["name"],
                "위험도": status["risk"] if status.get("has_measurement") else "미측정",
                "심박수": status["heart_rate"] if status.get("has_measurement") else None,
                "WBGT": round(status["wbgt"], 1) if status.get("has_measurement") else None,
                "작업강도": status["workload"] if status.get("has_measurement") else None,
                "대사율(W)": round(status["metabolic_watts"]) if status.get("has_measurement") else None,
                "기준여유(℃)": round(status["margin"], 1) if status.get("has_measurement") else None,
                "순화": status["acclimatization_label"] if status.get("has_measurement") else None,
                "최근 갱신": format_time(status.get("measured_at")),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


@st.experimental_fragment(run_every=2)
def render_manager_live_dashboard():
    statuses = list_latest_statuses()
    render_summary_cards(statuses)
    render_worker_cards(statuses)
    render_status_table(statuses)


def render_worker_profile_admin():
    workers = list_workers(include_inactive=True)
    worker_options = [worker["worker_id"] for worker in workers]

    with st.expander("작업자 프로필 관리", expanded=False):
        tab_update, tab_create = st.tabs(["기존 작업자 수정", "새 작업자 추가"])

        with tab_update:
            selected_id = st.selectbox(
                "수정할 작업자",
                options=worker_options,
                format_func=lambda worker_id: worker_label(
                    next(worker for worker in workers if worker["worker_id"] == worker_id)
                ),
            )
            selected = next(worker for worker in workers if worker["worker_id"] == selected_id)
            with st.form("update-worker-form"):
                name = st.text_input("이름", value=selected["name"])
                columns = st.columns(3)
                with columns[0]:
                    age = st.number_input("나이", min_value=1, max_value=120, value=selected["age"])
                with columns[1]:
                    weight = st.number_input(
                        "체중(kg)",
                        min_value=1.0,
                        max_value=300.0,
                        value=float(selected["weight"]),
                        step=0.5,
                    )
                with columns[2]:
                    sex = st.selectbox(
                        "성별",
                        options=list(SEX_LABELS),
                        index=list(SEX_LABELS).index(selected["sex"]),
                        format_func=SEX_LABELS.get,
                    )
                acclimatization_columns = st.columns(2)
                with acclimatization_columns[0]:
                    worker_status = st.selectbox(
                        "작업자 상태",
                        options=list(WORKER_STATUS_LABELS),
                        index=list(WORKER_STATUS_LABELS).index(selected["worker_status"]),
                        format_func=WORKER_STATUS_LABELS.get,
                    )
                    heat_exposure_days = st.number_input(
                        "최근 14일 유사 더위 작업일수",
                        min_value=0,
                        max_value=14,
                        value=selected["heat_exposure_days"],
                    )
                with acclimatization_columns[1]:
                    absence_days = st.number_input(
                        "연속 부재일수",
                        min_value=0,
                        max_value=365,
                        value=selected["absence_days"],
                    )
                    similar_heat_work = st.checkbox(
                        "최근 작업 강도가 오늘 작업과 유사함",
                        value=selected["similar_heat_work"],
                    )
                    active = st.checkbox("활성 작업자", value=selected["active"])
                preview = evaluate_acclimatization(
                    worker_status,
                    heat_exposure_days,
                    absence_days,
                    similar_heat_work,
                )
                st.info(f"순화 판정: {preview['status_label']} ({preview['limit_type']})")
                submitted = st.form_submit_button("프로필 저장", type="primary")
            if submitted:
                try:
                    upsert_worker(
                        selected_id,
                        name,
                        age,
                        weight,
                        sex,
                        worker_status,
                        heat_exposure_days,
                        absence_days,
                        similar_heat_work,
                        active,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success(f"{selected_id} 프로필을 저장했습니다.")
                    st.rerun()

        with tab_create:
            with st.form("create-worker-form"):
                next_number = len(workers) + 1
                worker_id = st.text_input("식별번호", value=f"W{next_number:03d}")
                name = st.text_input("이름", value="신규작업자")
                columns = st.columns(3)
                with columns[0]:
                    age = st.number_input("나이", min_value=1, max_value=120, value=25, key="new-age")
                with columns[1]:
                    weight = st.number_input(
                        "체중(kg)",
                        min_value=1.0,
                        max_value=300.0,
                        value=70.0,
                        step=0.5,
                        key="new-weight",
                    )
                with columns[2]:
                    sex = st.selectbox(
                        "성별",
                        options=list(SEX_LABELS),
                        format_func=SEX_LABELS.get,
                        key="new-sex",
                    )
                submitted = st.form_submit_button("작업자 추가", type="primary")
            if submitted:
                try:
                    upsert_worker(worker_id, name, age, weight, sex)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success(f"{worker_id.upper()} 작업자를 추가했습니다.")
                    st.rerun()


def render_manager_page():
    render_header(
        "관리자 대시보드",
        "작업자별 온열 위험도 현황",
        "중앙서버가 작업자별 심박수와 WBGT를 받아 위험도, 작업강도, 휴식 권고를 계산합니다.",
    )

    columns = st.columns([1, 1, 4])
    with columns[0]:
        if st.button("작업자 선택"):
            go_to(reset_worker=1)
    with columns[1]:
        st.caption(f"DB: {DB_PATH.name}")

    render_worker_profile_admin()
    render_manager_live_dashboard()


def main():
    initialize_database()
    st.set_page_config(
        page_title="다중 작업자 온열 위험도",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    render_css()

    view = query_value("view")
    worker_id = query_value("worker_id")

    if view == "manager":
        render_manager_page()
    elif worker_id:
        render_worker_page(worker_id)
    else:
        render_entry_page()


if __name__ == "__main__":
    main()
