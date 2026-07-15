# Render HTTPS 배포 가이드

이 프로젝트를 Wi-Fi IP와 무관한 고정 HTTPS 링크로 사용하려면 Render Web Service로
배포합니다. 배포 후 작업자와 관리자는 같은 공개 주소를 사용하며, Wi-Fi가 바뀌어도
인터넷만 연결되어 있으면 접속할 수 있습니다.

## 배포 후 사용할 링크

Render가 발급한 기본 주소가 예를 들어 다음과 같다면:

```text
https://wgbt-multi-worker-dashboard.onrender.com
```

작업자용 링크:

```text
https://wgbt-multi-worker-dashboard.onrender.com
```

관리자용 링크:

```text
https://wgbt-multi-worker-dashboard.onrender.com?view=manager
```

서비스 이름이 이미 사용 중이면 Render가 다른 주소를 배정할 수 있습니다. 그 경우
Render 대시보드의 서비스 URL을 기준으로 뒤에 `?view=manager`만 붙이면 됩니다.

## 준비

1. `wbgt - 2차 개선` 폴더를 GitHub 저장소로 올립니다.
2. Render 계정을 만들고 GitHub 계정을 연결합니다.
3. Render에서 `New` -> `Blueprint`를 선택합니다.
4. GitHub 저장소를 선택하면 `render.yaml` 설정을 읽어 자동 배포합니다.

## render.yaml 설정

현재 `render.yaml`은 2차 개선 앱을 실행하도록 맞춰져 있습니다.

```text
Build command: pip install -r requirements.txt
Start command: streamlit run main.py --server.address=0.0.0.0 --server.port=$PORT --server.headless=true
```

환경 변수:

```text
WGBT_DATA_DIR=/tmp/wgbt-data
WGBT_DB_PATH=/tmp/wgbt-data/workers.db
PYTHON_VERSION=3.12.13
```

## 저장 데이터 주의

Render 무료 Web Service의 파일시스템은 재시작/재배포 때 보존되지 않습니다.
Render 공식 문서도 기본 파일시스템은 ephemeral이며, 파일 변경은 재배포나 재시작
때 사라질 수 있다고 설명합니다.

캡스톤 발표용으로는 무료 배포도 충분합니다. 앱이 다시 켜지면 기본 작업자 5명이
자동 생성되고, 발표 중 입력한 측정값은 실행 중에는 유지됩니다.

측정값과 작업자 프로필을 장기 보존하려면 다음 중 하나가 필요합니다.

1. 유료 Render Web Service에 Persistent Disk를 연결하고 `WGBT_DB_PATH`를 디스크
   경로로 변경합니다. 예: `/var/data/workers.db`
2. SQLite 대신 Render Postgres, Supabase 같은 외부 DB를 사용합니다.

Render Persistent Disk는 유료 Web Service에 연결할 수 있고, 디스크 마운트 경로
아래의 파일만 재시작/재배포 후에도 보존됩니다.

## 배포 확인

배포가 끝난 뒤 다음 순서로 확인합니다.

1. 작업자 링크를 엽니다.
2. 작업자 선택 화면에서 `W001 김철수`를 선택합니다.
3. 심박수와 WBGT를 입력하고 저장합니다.
4. 관리자 링크를 엽니다.
5. 관리자 화면에 W001의 최신 위험도가 반영되는지 확인합니다.

## 커스텀 도메인

원하면 Render 서비스의 `Settings` -> `Custom Domains`에서 자체 도메인을 연결할
수 있습니다. 예를 들어 `https://heat.example.com`을 연결하면:

```text
작업자용: https://heat.example.com
관리자용: https://heat.example.com?view=manager
```
