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

