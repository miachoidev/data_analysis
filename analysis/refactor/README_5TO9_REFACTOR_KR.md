# 5~9 분석 리팩토링 가이드

요청하신 대로 5~9 분석을 항목별 코드로 분리했습니다.
또한 요청 반영으로 **주피터 노트북 기반 시각화 워크북**도 추가했습니다.

## 파일 구성

- `common.py`  
  공통 함수(컬럼 매핑, 로드, 표 출력, 안전 나눗셈, 사용자집계)

- `a01_signup_alignment.py`  
  1) AI가입일 = 전자금융가입일 분석 + 이벤트별 신규+AI 동시가입 검증

- `a02_transfer_prepost.py`  
  2) AI가입 전/후 이체유형 비교 (노출기간 보정 포함)

- `a03_reuse_rate.py`  
  3) 재사용률 분석 (가입시점 차이 고려 코호트)

- `a04_reuser_characteristics.py`  
  4) 재사용자 특징 가설(STT/연령/메뉴/이체) 검증

- `a05_nonreuse_causes.py`  
  5) 미사용/미재사용 원인 가설(초기 답변불가/여신/탈회직군) 검증

- `run_all_5to9.py`  
  위 5개를 한 번에 실행

- `ai_5to9_refactor_workbook.ipynb`  
  1~5 분석을 노트북 셀에서 실행하고, 핵심 지표를 시각화하는 워크북

---

## 실행 예시

```bash
python3 analysis/refactor/run_all_5to9.py \
  --profile-file data/customer_profile.csv \
  --chat-file data/ai_chat_daily_by_user.csv \
  --ai-transfer-file data/ai_transfer_daily_by_user.csv \
  --event-file data/event_calendar.csv \
  --open-date 2026-03-23 \
  --output-dir output_5to9
```

또는 개별 실행:

```bash
python3 analysis/refactor/a01_signup_alignment.py --profile-file data/customer_profile.csv --event-file data/event_calendar.csv --output-dir output_5to9
python3 analysis/refactor/a02_transfer_prepost.py --profile-file data/customer_profile.csv --chat-file data/ai_chat_daily_by_user.csv --ai-transfer-file data/ai_transfer_daily_by_user.csv --output-dir output_5to9
python3 analysis/refactor/a03_reuse_rate.py --profile-file data/customer_profile.csv --chat-file data/ai_chat_daily_by_user.csv --output-dir output_5to9
python3 analysis/refactor/a04_reuser_characteristics.py --profile-file data/customer_profile.csv --chat-file data/ai_chat_daily_by_user.csv --output-dir output_5to9
python3 analysis/refactor/a05_nonreuse_causes.py --profile-file data/customer_profile.csv --chat-file data/ai_chat_daily_by_user.csv --output-dir output_5to9
```

노트북 실행:

```bash
jupyter notebook analysis/refactor/ai_5to9_refactor_workbook.ipynb
```

노트북에서 먼저 경로 셀(`PROFILE_FILE`, `CHAT_FILE` 등)을 실제 파일명으로 바꾼 뒤 순서대로 실행하세요.

---

## 현재 반영된 컬럼 매핑 (사용자 제공 3개 파일 기준)

### 1) 고객정보 데이터
- `고객번호` → `customer_id`
- `연령대` → `age_band`
- `임직원여부` → `is_employee`
- `전자금융가입일` → `ebank_signup_date`
- `AI가입일` → `ai_signup_date`
- `대출건수` → `loan_account_count` (여신고객 판정에 사용)
- `STT전체요청건수` → `stt_request_count`
- `답변불가경험건수` → `unanswered_count`
- `직군대분류/직군중분류/직군소분류/직군세분류` → 직군 통합(`job_group`) 자동 생성

이체 전후 비교(A02)용 집계는 아래처럼 자동 보강합니다.
- 가입 전 1개월 이체 건수 합(`AI가입전_1개월_일반/쭉/오픈뱅킹/충전/잔돈적립`)  
  → `pre30_transfer_count`
- 가입 후 비AI 이체 건수 합(`AI가입후_일반/쭉/오픈뱅킹/AI충전/잔돈적립`)  
  → `post30_other_transfer_count`
- `AI가입후_AI이체건수` → `post30_ai_transfer_count`

### 2) 고객 AI요청 로그
- `고객번호` → `customer_id`
- `AI가입일` → `ai_signup_date`
- `AI가입경과일` → `ai_signup_elapsed_days`
- `TRX_DT`(예: 20260323) → `chat_date` (자동 날짜 파싱)
- `서비스분류` → `service_category`
- `의도분류` → `intent_code`
- `건수` → `request_count`

### 3) 고객 AI이체 실행 로그
- `고객번호` → `customer_id`
- `AI가입일` → `ai_signup_date`
- `AI가입경과일` → `ai_signup_elapsed_days`
- `AI이체일` → `ai_transfer_date` (자동 날짜 파싱)
- `AI이체건수` → `ai_transfer_count`
- `AI이체금액` → `ai_transfer_amount`

---

## 분석/해석 기준 핵심

### 재사용 기준
- 기본: `total_requests >= 3` 을 재사용으로 분류
- `total_requests <= 2` 는 미사용/미재사용

### “재사용률이 낮게 나오면 뭐라고 말하나?”
- 권장 표현:
  - “재사용률은 초기 도입단계 특성상 제한적으로 확인되며, 현재는 가입 확대보다 첫 성공경험 및 재방문 유도 설계가 우선 과제입니다.”
  - “구조적 확산 전 단계로 판단되며, FAQ/RAG 응답 고도화와 대출 관련 핵심 시나리오 보강으로 재사용 전환을 개선하겠습니다.”

### 첫응답 답변불가 판정
- `request_datetime` 있고 이벤트 단위면 정확 판정
- 없으면 첫요청일 기준 준정확 판정

