# 임원보고용 AI 분석 코드 가이드

## 1) 이 코드가 해주는 일

`analysis/ai_exec_report.py`는 아래 9개 항목을 한 번에 계산합니다.

1. AI서비스 오픈 전후 로그인 추이  
2. 오픈 전후 신규가입자(첫계좌) 추이  
3. 일자별 AI가입 추이 + 이벤트 시점 비교  
4. 배너 클릭 후 AI가입 전환율  
5. AI가입일 = 신규가입일 일치 여부  
6. AI가입 전후 이체 사용 양상 + 실행 퍼널  
7. AI 재사용 현황(7일/30일 코호트)  
8. AI가입 후 미사용자/1회성/재사용 분포  
9. 미사용자 vs 재사용자 특성 비교  

그리고 결과를:
- CSV 테이블
- 임원 보고서 초안(`executive_report_draft.md`)

으로 자동 생성합니다.

추가로, **주피터 노트북 버전**(`analysis/ai_exec_report_notebook.ipynb`)도 제공합니다.
- 그래프는 꼭 필요한 핵심 추이만 최소 구성
- 표는 `print` 시 마크다운 표 형태로 출력되어 바로 복붙 가능

---

## 2) 실행 방법

```bash
python analysis/ai_exec_report.py \
  --daily-file data/daily_metrics.csv \
  --profile-file data/customer_profile.csv \
  --chat-file data/ai_chat_daily_by_user.csv \
  --ai-transfer-file data/ai_transfer_daily_by_user.csv \
  --event-file data/event_calendar.csv \
  --banner-file data/banner_funnel.csv \
  --open-date 2026-03-23 \
  --output-dir output_exec
```

필수는 `--open-date`만입니다.  
파일이 없는 항목은 자동으로 스킵됩니다.

### 주피터(권장 분리본)

- 전체(1~9): `analysis/ai_exec_report_notebook.ipynb`
- **5~9만 전용(마케팅팀 범위 제외): `analysis/ai_exec_report_5to9_notebook.ipynb`**
  - 1~4번(로그인/신규/일자추이/배너전환)은 제외
  - 사용자행동 데이터(프로필/채팅/AI이체) 기반으로 5~9번만 수행
- **미사용/미재사용 원인 가설검증 전용: `analysis/ai_nonreuse_hypothesis_notebook.ipynb`**
  - 그룹: 미사용/미재사용(0~2건) vs 재사용(3건 이상)
  - `unanswered_count(답변불가경험건수)` 핵심 반영
  - 여신고객은 `loan_customer` 또는 **대출계좌건수(>=1)** 로 자동 파생(`loan_customer_flag`)
  - 요청일시가 있으면 **첫응답 답변불가를 정확 판별**, 없으면 첫요청일 기준 준정확 판별
  - STT/연령/메뉴/이체/여신고객 가설을 표 중심으로 검증

### 주피터 노트북으로 실행

```bash
jupyter notebook analysis/ai_exec_report_notebook.ipynb
```

노트북 상단 경로 변수(`DATA_DIR`, 파일명)를 실제 파일 위치에 맞춰 수정한 뒤 셀을 순서대로 실행하세요.

미사용 원인 가설검증 전용 노트북만 실행하려면:

```bash
jupyter notebook analysis/ai_nonreuse_hypothesis_notebook.ipynb
```

---

## 3) 컬럼명 규칙

코드는 한국어/영문 컬럼명을 둘 다 일부 자동 인식합니다.

### 일일 데이터(`--daily-file`) 권장 컬럼
- `date` (또는 `일자`, `날짜`)
- `app_logins` (또는 `일일 앱 로그인고객수`)
- `new_signups` (또는 `일일 신규가입자`, `전자금융신규가입자`)
- `ai_signups` (또는 `일일 ai 가입자`)

### 고객 프로필(`--profile-file`) 권장 컬럼
- `customer_id`(고객번호), `age_band`(나이대), `is_employee`(임직원여부)
- `ebank_signup_date`(전자금융가입일), `ai_signup_date`(AI가입일), `last_login_date`(최근접속일)
- `pre30_transfer_count`, `post30_ai_transfer_count`, `post30_other_transfer_count`
- `pre_year_avg_transfer_count`, `feedback_like_count`, `feedback_dislike_count`, `unanswered_count`

### 대화 로그(`--chat-file`) 권장 컬럼
- `customer_id`, `ai_signup_date`, `chat_date`, `service_category`, `request_count`
- (권장 추가) `intent_code(의도분류코드)`, `request_datetime(요청일시)`  
  → 첫응답 답변불가를 정확히 보려면 `request_datetime`이 필요

### AI이체 로그(`--ai-transfer-file`) 권장 컬럼
- `customer_id`, `ai_signup_date`, `ai_transfer_date`, `ai_transfer_count`, `ai_transfer_amount`

### 이벤트(`--event-file`) 권장 컬럼
- `event_date`, `event_name`, `event_type`

### 배너(`--banner-file`) 권장 컬럼
- `date`, `banner_name`, `banner_clicks`, `banner_signups`

---

## 4) GPT 초안 대비 보완/수정 포인트 (실무적으로 중요한 부분)

초안은 전반적으로 방향은 좋지만, 아래 3가지는 보완이 필요합니다.

1. **전후 평균만 보면 착시 가능**
   - 오픈 4주 데이터는 계절성/요일효과/기저효과 영향이 큼
   - 보완: `로그인 1천명당 AI가입`, `가입자당 요청건수` 같은 **비율 지표** 병행

2. **이벤트 효과를 “있다/없다” 이분법으로 보면 손해**
   - 실제는 “단기 피크 vs 지속 증가”가 다름
   - 보완: 이벤트별 `전7일`, `후7일`, `후8~14일`을 분리해 **반응 형태**로 보고

3. **가입시점이 달라 전후비교 불가하다는 오해**
   - 사용자별 가입일이 달라도 코호트(가입일=0일) 정렬하면 해결
   - 보완: `가입 후 7일/30일 재사용률`, `가입 후 30일 전환률`로 표준화

---

## 5) 결과가 안 좋게 나왔을 때 권장 멘트

- “효과가 없다” 대신  
  → “**구조적 변화는 제한적이며**, 초기 도입단계 특성상 전환지표 중심의 관리가 필요합니다.”

- “광고가 실패했다” 대신  
  → “상단 퍼널(인지/클릭)은 작동하나, **가입 전환 단계 병목**이 확인됩니다.”

- “재사용이 낮다” 대신  
  → “대규모 일상화 전 단계로, 현재 핵심과제는 **첫 사용 이후 재방문 설계**입니다.”

---

## 6) 샘플 표 (보고서 붙여넣기용 포맷)

| 구분 | 값 |
|---|---:|
| AI가입자 | 8,000 |
| 가입 후 1회 이상 사용자 | 3,600 (45.0%) |
| 가입 후 재사용자(2일 이상) | 1,120 (14.0%) |
| 가입 후 30일 내 2회 이상 | 780 (9.8%) |
| 가입 후 30일 내 3일 이상 | 320 (4.0%) |

샘플은 예시이며, 실제 값은 스크립트 출력 CSV를 기준으로 교체하세요.

---

## 7) 실무 팁

- 현재 단계에서 임원에게 보여줄 핵심은 “성공/실패” 단정이 아니라  
  **초기 도입단계 진단 + 다음 분기 개선 우선순위**입니다.
- KPI는 총가입자 단일지표보다 아래 3개를 동시에 관리하는 것이 좋습니다.
  1) 가입 후 첫사용률  
  2) 7일/30일 재사용률  
  3) AI이체 실행률  
