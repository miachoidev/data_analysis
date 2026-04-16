#!/usr/bin/env python3
"""
AI 서비스 임원보고용 분석 스크립트

사용 목적
- 사용자 요청 9개 항목을 데이터 기반으로 재현 가능한 형태로 계산
- 결과 테이블(CSV) + 임원보고용 요약 문구(Markdown) 자동 생성
- 오픈 초기(짧은 관측기간) 한계를 보완하기 위해 절대값 외 비율 지표 추가
  (예: 로그인 1천명당 AI 가입자, 가입자당 AI 요청 건수)

실행 예시
python analysis/ai_exec_report.py \
  --daily-file data/daily_metrics.csv \
  --profile-file data/customer_profile.csv \
  --chat-file data/ai_chat_daily_by_user.csv \
  --ai-transfer-file data/ai_transfer_daily_by_user.csv \
  --event-file data/event_calendar.csv \
  --banner-file data/banner_funnel.csv \
  --open-date 2026-03-23 \
  --output-dir output_exec
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt

    HAS_MPL = True
except Exception:
    HAS_MPL = False


def safe_div(n: float, d: float) -> float:
    if d is None or d == 0 or pd.isna(d):
        return np.nan
    return n / d


def pct_change(new: float, old: float) -> float:
    if old is None or old == 0 or pd.isna(old):
        return np.nan
    return (new - old) / old


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    colset = set(df.columns)
    for c in candidates:
        if c in colset:
            return c
    return None


def load_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"[WARN] 파일 없음: {p}")
        return None
    return pd.read_csv(p)


def to_datetime(df: pd.DataFrame, columns: Iterable[str]) -> None:
    for c in columns:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")


def save_table(df: pd.DataFrame, out_dir: Path, name: str) -> Path:
    path = out_dir / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def comment_by_delta(
    metric_name: str,
    delta_pct: float,
    high_th: float = 0.10,
    low_th: float = 0.03,
) -> str:
    if pd.isna(delta_pct):
        return f"{metric_name}은(는) 비교 구간 데이터가 부족해 방향성 판단이 제한적입니다."
    if delta_pct >= high_th:
        return (
            f"{metric_name}은(는) 기준 구간 대비 뚜렷한 증가가 관측됩니다. "
            "단기 반응을 유지 성장으로 연결하는 후속 장치(재사용 유도)가 중요합니다."
        )
    if delta_pct >= low_th:
        return (
            f"{metric_name}은(는) 완만한 개선 신호가 있습니다. "
            "구조적 전환 여부는 추가 관측이 필요합니다."
        )
    if delta_pct <= -high_th:
        return (
            f"{metric_name}은(는) 감소 폭이 커서, 유입보다 전환/정착 병목을 우선 점검해야 합니다."
        )
    return (
        f"{metric_name}은(는) 구조적 변화가 제한적입니다. "
        "오픈 초기 국면에서는 절대규모보다 전환율·재사용률 지표를 병행 관리하는 것이 적절합니다."
    )


def plot_line(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    title: str,
    out_path: Path,
    open_date: Optional[pd.Timestamp] = None,
) -> None:
    if not HAS_MPL or df.empty:
        return
    tmp = df.sort_values(date_col).copy()
    if value_col not in tmp.columns:
        return
    tmp["ma7"] = tmp[value_col].rolling(7, min_periods=1).mean()
    plt.figure(figsize=(11, 4.5))
    plt.plot(tmp[date_col], tmp[value_col], alpha=0.35, label=value_col)
    plt.plot(tmp[date_col], tmp["ma7"], linewidth=2, label="7일 이동평균")
    if open_date is not None:
        plt.axvline(open_date, color="crimson", linestyle="--", label="오픈일")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    plt.close()


@dataclass
class AnalysisOutputs:
    tables: Dict[str, Path]
    comments: Dict[str, str]
    extras: Dict[str, pd.DataFrame]


def analyze_pre_post_metric(
    daily_df: pd.DataFrame,
    date_col: str,
    metric_col: str,
    open_date: pd.Timestamp,
    window_days: int = 28,
) -> pd.DataFrame:
    d = daily_df[[date_col, metric_col]].dropna().copy()
    pre_start = open_date - pd.Timedelta(days=window_days)
    post_end = open_date + pd.Timedelta(days=window_days)
    pre = d[(d[date_col] >= pre_start) & (d[date_col] < open_date)]
    post = d[(d[date_col] >= open_date) & (d[date_col] < post_end)]
    row = {
        "metric": metric_col,
        "pre_days": len(pre),
        "post_days": len(post),
        "pre_mean": pre[metric_col].mean(),
        "post_mean": post[metric_col].mean(),
        "abs_change": post[metric_col].mean() - pre[metric_col].mean(),
        "pct_change": pct_change(post[metric_col].mean(), pre[metric_col].mean()),
        "pre_sum": pre[metric_col].sum(),
        "post_sum": post[metric_col].sum(),
    }
    return pd.DataFrame([row])


def analyze_event_impact(
    daily_df: pd.DataFrame,
    event_df: pd.DataFrame,
    date_col: str,
    metric_col: str,
) -> pd.DataFrame:
    if event_df is None or event_df.empty:
        return pd.DataFrame()
    event_date_col = first_existing_column(event_df, ["event_date", "일자", "날짜"])
    event_name_col = first_existing_column(event_df, ["event_name", "이벤트명", "event"])
    event_type_col = first_existing_column(event_df, ["event_type", "이벤트유형", "type"])
    if not event_date_col:
        return pd.DataFrame()

    e = event_df.copy()
    e[event_date_col] = pd.to_datetime(e[event_date_col], errors="coerce")
    out_rows = []
    for _, r in e.dropna(subset=[event_date_col]).iterrows():
        dt = r[event_date_col]
        pre7 = daily_df[(daily_df[date_col] >= dt - pd.Timedelta(days=7)) & (daily_df[date_col] < dt)]
        post7 = daily_df[(daily_df[date_col] > dt) & (daily_df[date_col] <= dt + pd.Timedelta(days=7))]
        post14_tail = daily_df[
            (daily_df[date_col] > dt + pd.Timedelta(days=7))
            & (daily_df[date_col] <= dt + pd.Timedelta(days=14))
        ]
        pre_mean = pre7[metric_col].mean()
        post_mean = post7[metric_col].mean()
        tail_mean = post14_tail[metric_col].mean()
        post_delta = pct_change(post_mean, pre_mean)
        tail_delta = pct_change(tail_mean, pre_mean)
        if pd.notna(post_delta) and post_delta >= 0.10 and pd.notna(tail_delta) and tail_delta >= 0.05:
            impact_type = "지속 증가"
        elif pd.notna(post_delta) and post_delta >= 0.05:
            impact_type = "단기 반응"
        else:
            impact_type = "유의 변화 제한"
        out_rows.append(
            {
                "event_name": r[event_name_col] if event_name_col else f"event_{dt.date()}",
                "event_type": r[event_type_col] if event_type_col else "미분류",
                "event_date": dt.date(),
                "pre7_mean": pre_mean,
                "post7_mean": post_mean,
                "post7_pct_change": post_delta,
                "post8_14_mean": tail_mean,
                "post8_14_pct_change": tail_delta,
                "impact_type": impact_type,
            }
        )
    return pd.DataFrame(out_rows)


def make_usage_summary(chat_df: pd.DataFrame) -> pd.DataFrame:
    if chat_df is None or chat_df.empty:
        return pd.DataFrame()
    cols_needed = ["customer_id", "ai_signup_date", "chat_date", "request_count"]
    if any(c not in chat_df.columns for c in cols_needed):
        return pd.DataFrame()

    c = chat_df.copy()
    c = c.dropna(subset=["customer_id", "ai_signup_date", "chat_date"])
    c = c[c["chat_date"] >= c["ai_signup_date"]]
    c["day_offset"] = (c["chat_date"] - c["ai_signup_date"]).dt.days

    user = c.groupby("customer_id").agg(
        total_requests=("request_count", "sum"),
        use_days=("chat_date", "nunique"),
        first_use_date=("chat_date", "min"),
        last_use_date=("chat_date", "max"),
        req_7d=("request_count", lambda s: s[c.loc[s.index, "day_offset"] <= 7].sum()),
        req_30d=("request_count", lambda s: s[c.loc[s.index, "day_offset"] <= 30].sum()),
        days_30d=("chat_date", lambda s: c.loc[s.index][c.loc[s.index, "day_offset"] <= 30]["chat_date"].nunique()),
    )
    user["is_reuser"] = user["use_days"] >= 2
    user["is_30d_2plus"] = user["req_30d"] >= 2
    user["is_30d_3days"] = user["days_30d"] >= 3
    return user.reset_index()


def maybe_build_datasets(
    daily_df: Optional[pd.DataFrame],
    profile_df: Optional[pd.DataFrame],
    chat_df: Optional[pd.DataFrame],
    ai_transfer_df: Optional[pd.DataFrame],
    event_df: Optional[pd.DataFrame],
    banner_df: Optional[pd.DataFrame],
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    # daily
    if daily_df is not None:
        daily_map = {
            "date": ["date", "일자", "날짜"],
            "app_logins": ["app_logins", "일일 앱 로그인고객수", "daily_app_login_users", "login_users"],
            "new_signups": ["new_signups", "일일 신규가입자", "전자금융신규가입자", "first_account_open_users"],
            "ai_signups": ["ai_signups", "일일 ai 가입자", "daily_ai_signups", "ai_join_users"],
        }
        rename = {}
        for k, cands in daily_map.items():
            found = first_existing_column(daily_df, cands)
            if found:
                rename[found] = k
        daily_df = daily_df.rename(columns=rename)
        to_datetime(daily_df, ["date"])

    # profile
    if profile_df is not None:
        profile_map = {
            "customer_id": ["customer_id", "고객번호"],
            "age_band": ["age_band", "나이대"],
            "is_employee": ["is_employee", "임직원여부"],
            "ebank_signup_date": ["ebank_signup_date", "전자금융가입일", "첫계좌튼날", "first_account_open_date"],
            "ai_signup_date": ["ai_signup_date", "AI가입일", "ai_join_date"],
            "last_login_date": ["last_login_date", "최근접속일"],
            "pre30_transfer_count": ["pre30_transfer_count", "AI가입전30일_이체건수", "가입전30일이체건수"],
            "post30_other_transfer_count": ["post30_other_transfer_count", "AI가입후30일_기존이체건수", "가입후30일기존이체건수"],
            "post30_ai_transfer_count": ["post30_ai_transfer_count", "AI가입후30일_ai이체건수", "가입후30일AI이체건수"],
            "pre_year_avg_transfer_count": ["pre_year_avg_transfer_count", "AI가입전1년_월평균이체건수", "월평균이체건수_1y"],
            "feedback_like_count": ["feedback_like_count", "피드백좋아요건"],
            "feedback_dislike_count": ["feedback_dislike_count", "피드백싫어요건"],
            "unanswered_count": ["unanswered_count", "답변불가경험건수"],
        }
        rename = {}
        for k, cands in profile_map.items():
            found = first_existing_column(profile_df, cands)
            if found:
                rename[found] = k
        profile_df = profile_df.rename(columns=rename)
        to_datetime(profile_df, ["ebank_signup_date", "ai_signup_date", "last_login_date"])

    # chat
    if chat_df is not None:
        chat_map = {
            "customer_id": ["customer_id", "고객번호"],
            "ai_signup_date": ["ai_signup_date", "AI가입일", "ai_join_date"],
            "chat_date": ["chat_date", "채팅요청일", "요청일", "date"],
            "service_category": ["service_category", "서비스분류", "서비스분류코드"],
            "request_count": ["request_count", "건수", "cnt"],
        }
        rename = {}
        for k, cands in chat_map.items():
            found = first_existing_column(chat_df, cands)
            if found:
                rename[found] = k
        chat_df = chat_df.rename(columns=rename)
        to_datetime(chat_df, ["ai_signup_date", "chat_date"])

    # ai transfer
    if ai_transfer_df is not None:
        t_map = {
            "customer_id": ["customer_id", "고객번호"],
            "ai_signup_date": ["ai_signup_date", "AI가입일"],
            "ai_transfer_date": ["ai_transfer_date", "ai이체일"],
            "ai_transfer_count": ["ai_transfer_count", "ai이체건수"],
            "ai_transfer_amount": ["ai_transfer_amount", "금액합", "amount_sum"],
        }
        rename = {}
        for k, cands in t_map.items():
            found = first_existing_column(ai_transfer_df, cands)
            if found:
                rename[found] = k
        ai_transfer_df = ai_transfer_df.rename(columns=rename)
        to_datetime(ai_transfer_df, ["ai_signup_date", "ai_transfer_date"])

    # events
    if event_df is not None:
        to_datetime(event_df, ["event_date", "일자", "날짜"])

    # banner
    if banner_df is not None:
        b_map = {
            "date": ["date", "일자", "날짜"],
            "banner_name": ["banner_name", "배너위치", "배너명"],
            "banner_clicks": ["banner_clicks", "클릭수", "배너클릭수"],
            "banner_signups": ["banner_signups", "가입자수", "클릭후가입자수", "ai가입자수"],
        }
        rename = {}
        for k, cands in b_map.items():
            found = first_existing_column(banner_df, cands)
            if found:
                rename[found] = k
        banner_df = banner_df.rename(columns=rename)
        to_datetime(banner_df, ["date"])

    return daily_df, profile_df, chat_df, ai_transfer_df, event_df, banner_df


def run_analysis(
    daily_df: Optional[pd.DataFrame],
    profile_df: Optional[pd.DataFrame],
    chat_df: Optional[pd.DataFrame],
    ai_transfer_df: Optional[pd.DataFrame],
    event_df: Optional[pd.DataFrame],
    banner_df: Optional[pd.DataFrame],
    open_date: pd.Timestamp,
    out_dir: Path,
) -> AnalysisOutputs:
    ensure_dir(out_dir)
    tables: Dict[str, Path] = {}
    comments: Dict[str, str] = {}
    extras: Dict[str, pd.DataFrame] = {}

    # 1) 오픈 전후 로그인 추이
    if daily_df is not None and {"date", "app_logins"}.issubset(daily_df.columns):
        t1 = analyze_pre_post_metric(daily_df, "date", "app_logins", open_date, window_days=28)
        t1["analysis_item"] = "1) 오픈 전후 로그인"
        tables["item1_login_prepost"] = save_table(t1, out_dir, "item1_login_prepost")
        delta = t1.loc[0, "pct_change"]
        comments["item1"] = comment_by_delta("오픈 전후 로그인", delta)
        plot_line(
            daily_df,
            "date",
            "app_logins",
            "일별 앱 로그인 추이",
            out_dir / "item1_login_trend.png",
            open_date=open_date,
        )
        # 보완지표: 로그인 1천명당 AI 가입자
        if "ai_signups" in daily_df.columns:
            rate = daily_df[["date", "ai_signups", "app_logins"]].copy()
            rate["ai_signup_per_1000_login"] = rate.apply(
                lambda x: safe_div(x["ai_signups"], x["app_logins"]) * 1000, axis=1
            )
            tables["item1b_signup_rate"] = save_table(
                rate[["date", "ai_signup_per_1000_login"]], out_dir, "item1b_signup_per_1000_login"
            )
            extras["signup_rate_daily"] = rate

    # 2) 오픈 전후 신규가입 추이
    if daily_df is not None and {"date", "new_signups"}.issubset(daily_df.columns):
        t2 = analyze_pre_post_metric(daily_df, "date", "new_signups", open_date, window_days=28)
        t2["analysis_item"] = "2) 오픈 전후 신규가입"
        tables["item2_new_signup_prepost"] = save_table(t2, out_dir, "item2_new_signup_prepost")
        comments["item2"] = comment_by_delta("오픈 전후 신규가입", t2.loc[0, "pct_change"])
        plot_line(
            daily_df,
            "date",
            "new_signups",
            "일별 신규가입 추이",
            out_dir / "item2_new_signup_trend.png",
            open_date=open_date,
        )

    # 3) AI가입 추이 + 이벤트 효과
    if daily_df is not None and {"date", "ai_signups"}.issubset(daily_df.columns):
        t3 = analyze_pre_post_metric(daily_df, "date", "ai_signups", open_date, window_days=28)
        t3["analysis_item"] = "3) 오픈 전후 AI가입"
        tables["item3_ai_signup_prepost"] = save_table(t3, out_dir, "item3_ai_signup_prepost")
        comments["item3"] = comment_by_delta("일자별 AI가입", t3.loc[0, "pct_change"])
        plot_line(
            daily_df,
            "date",
            "ai_signups",
            "일자별 AI가입 추이",
            out_dir / "item3_ai_signup_trend.png",
            open_date=open_date,
        )
        if event_df is not None and not event_df.empty:
            event_result = analyze_event_impact(daily_df, event_df, "date", "ai_signups")
            if not event_result.empty:
                tables["item3_event_impact"] = save_table(event_result, out_dir, "item3_event_impact")
                limited_ratio = safe_div(
                    (event_result["impact_type"] == "유의 변화 제한").sum(), len(event_result)
                )
                if pd.notna(limited_ratio) and limited_ratio >= 0.6:
                    comments["item3_event"] = (
                        "이벤트 다수에서 구조적 증분은 제한적이며, 단기 피크 후 정상화되는 패턴이 확인됩니다. "
                        "향후에는 이벤트 볼륨보다 가입 후 재사용 전환 장치가 우선입니다."
                    )
                else:
                    comments["item3_event"] = (
                        "일부 이벤트에서 단기/지속 반응이 관측됩니다. 반응 이벤트 유형을 표준화해 재현성을 높일 필요가 있습니다."
                    )

    # 4) 배너 클릭 후 가입 전환
    if banner_df is not None and {"banner_clicks", "banner_signups"}.issubset(banner_df.columns):
        g_cols = ["banner_name"] if "banner_name" in banner_df.columns else []
        if g_cols:
            t4 = banner_df.groupby(g_cols, dropna=False).agg(
                clicks=("banner_clicks", "sum"),
                signups=("banner_signups", "sum"),
            ).reset_index()
        else:
            t4 = pd.DataFrame(
                [
                    {
                        "banner_name": "전체",
                        "clicks": banner_df["banner_clicks"].sum(),
                        "signups": banner_df["banner_signups"].sum(),
                    }
                ]
            )
        t4["click_to_signup_cvr"] = t4.apply(lambda x: safe_div(x["signups"], x["clicks"]), axis=1)
        tables["item4_banner_conversion"] = save_table(t4, out_dir, "item4_banner_conversion")
        overall = safe_div(t4["signups"].sum(), t4["clicks"].sum())
        if pd.notna(overall) and overall < 0.03:
            comments["item4"] = (
                "배너는 인지(클릭) 확보는 가능하나 가입 전환(CVR)이 낮아 전환 단계 병목이 큽니다. "
                "메시지/랜딩/첫 사용가치 문구 개선이 우선입니다."
            )
        else:
            comments["item4"] = (
                "배너 유입의 가입 전환이 일정 수준 확인됩니다. "
                "고CVR 배너 위치/문구를 기준으로 확장하는 전략이 유효합니다."
            )

    # 5) AI가입일 = 신규가입일 비교
    if profile_df is not None and {"customer_id", "ebank_signup_date", "ai_signup_date"}.issubset(profile_df.columns):
        p = profile_df.dropna(subset=["ai_signup_date", "ebank_signup_date"]).copy()
        p["diff_days"] = (p["ai_signup_date"] - p["ebank_signup_date"]).dt.days
        dist = pd.DataFrame(
            [
                {"group": "동일일(0일)", "users": int((p["diff_days"] == 0).sum())},
                {"group": "1~7일", "users": int(((p["diff_days"] >= 1) & (p["diff_days"] <= 7)).sum())},
                {"group": "8~30일", "users": int(((p["diff_days"] >= 8) & (p["diff_days"] <= 30)).sum())},
                {"group": "30일 초과", "users": int((p["diff_days"] > 30).sum())},
            ]
        )
        dist["ratio"] = dist["users"] / max(dist["users"].sum(), 1)
        tables["item5_signup_gap"] = save_table(dist, out_dir, "item5_ai_signup_vs_new_signup")
        same_day_ratio = dist.loc[dist["group"] == "동일일(0일)", "ratio"].iloc[0]
        if same_day_ratio < 0.1:
            comments["item5"] = (
                "AI가입은 신규가입 당일보다는 일정 사용 이후 전환되는 후행형 패턴입니다. "
                "신규 온보딩 한 번에 가입을 기대하기보다, 사용 맥락 기반 재노출이 적합합니다."
            )
        else:
            comments["item5"] = (
                "신규가입 당일 AI가입이 일정 수준 확인됩니다. "
                "온보딩 단계의 가치제안(즉시 효용)을 강화하면 초기 전환 확대 여지가 있습니다."
            )

    usage_user = make_usage_summary(chat_df) if chat_df is not None else pd.DataFrame()

    # 6) AI가입 전후 이체 사용 비교 + 실행 퍼널
    if profile_df is not None and "customer_id" in profile_df.columns:
        p = profile_df.copy()
        for c in ["pre30_transfer_count", "post30_ai_transfer_count", "post30_other_transfer_count"]:
            if c not in p.columns:
                p[c] = np.nan
        p["post30_total_transfer_count"] = (
            p["post30_ai_transfer_count"].fillna(0) + p["post30_other_transfer_count"].fillna(0)
        )
        summary = pd.DataFrame(
            [
                {
                    "metric": "가입 전 30일 평균 이체건수",
                    "value": p["pre30_transfer_count"].mean(),
                },
                {
                    "metric": "가입 후 30일 평균 전체 이체건수",
                    "value": p["post30_total_transfer_count"].mean(),
                },
                {
                    "metric": "가입 후 30일 평균 AI이체건수",
                    "value": p["post30_ai_transfer_count"].mean(),
                },
                {
                    "metric": "가입 후 30일 평균 기존이체건수",
                    "value": p["post30_other_transfer_count"].mean(),
                },
            ]
        )
        tables["item6_transfer_compare"] = save_table(summary, out_dir, "item6_transfer_before_after")

        signup_users = p["customer_id"].nunique()
        req_users = usage_user["customer_id"].nunique() if not usage_user.empty else np.nan
        transfer_req_users = np.nan
        if chat_df is not None and "service_category" in chat_df.columns and "customer_id" in chat_df.columns:
            transfer_mask = chat_df["service_category"].astype(str).str.contains("이체|transfer", case=False, na=False)
            transfer_req_users = chat_df.loc[transfer_mask, "customer_id"].nunique()
        transfer_exec_users = (
            ai_transfer_df.loc[ai_transfer_df["ai_transfer_count"] > 0, "customer_id"].nunique()
            if ai_transfer_df is not None and {"customer_id", "ai_transfer_count"}.issubset(ai_transfer_df.columns)
            else np.nan
        )
        funnel = pd.DataFrame(
            [
                {"stage": "AI가입자", "users": signup_users, "ratio_vs_signup": 1.0},
                {
                    "stage": "AI요청 경험자",
                    "users": req_users,
                    "ratio_vs_signup": safe_div(req_users, signup_users),
                },
                {
                    "stage": "AI이체 요청 경험자",
                    "users": transfer_req_users,
                    "ratio_vs_signup": safe_div(transfer_req_users, signup_users),
                },
                {
                    "stage": "AI이체 실제 실행자",
                    "users": transfer_exec_users,
                    "ratio_vs_signup": safe_div(transfer_exec_users, signup_users),
                },
            ]
        )
        tables["item6_transfer_funnel"] = save_table(funnel, out_dir, "item6_transfer_funnel")
        exec_ratio = funnel.loc[funnel["stage"] == "AI이체 실제 실행자", "ratio_vs_signup"].iloc[0]
        if pd.notna(exec_ratio) and exec_ratio < 0.08:
            comments["item6"] = (
                "AI이체는 일부 고객에 한정된 초기 사용 단계입니다. "
                "전면 대체보다 목적형 시나리오(반복이체/소액이체/급한송금) 중심 확장이 효과적입니다."
            )
        else:
            comments["item6"] = (
                "AI가입 이후 이체 실행 전환이 일정 수준 형성되고 있습니다. "
                "고반응 구간을 중심으로 기능 안내를 강화하면 추가 확장이 가능합니다."
            )

    # 7) AI 재사용 현황
    if not usage_user.empty:
        signup_base = (
            profile_df.loc[profile_df["ai_signup_date"].notna(), "customer_id"].nunique()
            if profile_df is not None and {"customer_id", "ai_signup_date"}.issubset(profile_df.columns)
            else usage_user["customer_id"].nunique()
        )
        m = {
            "가입자수": signup_base,
            "가입 후 1회 이상 사용자": usage_user["customer_id"].nunique(),
            "가입 후 재사용자(2일 이상)": int(usage_user["is_reuser"].sum()),
            "가입 후 30일 내 2회 이상 요청자": int(usage_user["is_30d_2plus"].sum()),
            "가입 후 30일 내 3일 이상 사용자": int(usage_user["is_30d_3days"].sum()),
        }
        t7 = pd.DataFrame(
            [{"metric": k, "users": v, "ratio_vs_signup": safe_div(v, signup_base)} for k, v in m.items()]
        )
        tables["item7_reuse_metrics"] = save_table(t7, out_dir, "item7_reuse_metrics")
        reuse_ratio = safe_div(m["가입 후 재사용자(2일 이상)"], signup_base)
        if pd.notna(reuse_ratio) and reuse_ratio < 0.2:
            comments["item7"] = (
                "재사용은 아직 제한적이며, 가입 대비 정착 단계에서 이탈이 큽니다. "
                "초기 7일 내 재방문 트리거(리마인드/개인화 추천/성공사례 노출) 설계가 핵심입니다."
            )
        else:
            comments["item7"] = (
                "재사용 기반이 형성되고 있습니다. "
                "서비스별 고반응 시나리오를 중심으로 반복 사용 경험을 확장할 수 있습니다."
            )

        if chat_df is not None and {"service_category", "customer_id"}.issubset(chat_df.columns):
            service_user = chat_df.groupby("service_category")["customer_id"].nunique().reset_index(name="users")
            service_reuse = chat_df.groupby(["service_category", "customer_id"])["chat_date"].nunique().reset_index(name="use_days")
            service_reuse["is_reuser"] = service_reuse["use_days"] >= 2
            rr = service_reuse.groupby("service_category")["is_reuser"].mean().reset_index(name="reuse_ratio")
            t7b = service_user.merge(rr, on="service_category", how="left").sort_values("users", ascending=False)
            tables["item7_service_reuse"] = save_table(t7b, out_dir, "item7_service_reuse")

    # 8) 가입 후 미사용자
    segment_df = pd.DataFrame()
    if profile_df is not None and {"customer_id", "ai_signup_date"}.issubset(profile_df.columns):
        base = profile_df.loc[profile_df["ai_signup_date"].notna(), ["customer_id", "ai_signup_date"]].drop_duplicates()
        segment_df = base.copy()
        if not usage_user.empty:
            segment_df = segment_df.merge(
                usage_user[["customer_id", "total_requests", "use_days", "last_use_date"]],
                on="customer_id",
                how="left",
            )
        else:
            segment_df["total_requests"] = 0
            segment_df["use_days"] = 0
            segment_df["last_use_date"] = pd.NaT

        max_date = None
        if chat_df is not None and "chat_date" in chat_df.columns:
            max_date = chat_df["chat_date"].max()
        if max_date is None or pd.isna(max_date):
            max_date = pd.Timestamp.today().normalize()

        def assign_segment(r: pd.Series) -> str:
            req = r.get("total_requests", 0)
            days = r.get("use_days", 0)
            last = r.get("last_use_date", pd.NaT)
            if pd.isna(req) or req <= 0 or pd.isna(days) or days <= 0:
                return "미사용"
            if days == 1:
                return "1회성"
            if pd.notna(last) and last < (max_date - pd.Timedelta(days=30)):
                return "휴면(최근30일 미사용)"
            return "재사용"

        segment_df["usage_segment"] = segment_df.apply(assign_segment, axis=1)
        t8 = (
            segment_df.groupby("usage_segment")["customer_id"]
            .nunique()
            .reset_index(name="users")
            .sort_values("users", ascending=False)
        )
        t8["ratio"] = t8["users"] / max(t8["users"].sum(), 1)
        tables["item8_non_use"] = save_table(t8, out_dir, "item8_non_use_segment")
        non_use_ratio = t8.loc[t8["usage_segment"] == "미사용", "ratio"]
        non_use_ratio = non_use_ratio.iloc[0] if len(non_use_ratio) else np.nan
        if pd.notna(non_use_ratio) and non_use_ratio >= 0.5:
            comments["item8"] = (
                "가입 후 미사용 비중이 높아, KPI를 가입자수에서 '가입 후 첫 사용률' 중심으로 전환할 필요가 있습니다."
            )
        else:
            comments["item8"] = (
                "미사용/이탈 비중은 관리 가능한 수준으로 보이며, 재사용군 확대를 위한 타깃 메시지 최적화가 유효합니다."
            )

    # 9) 미사용 vs 재사용 특성
    if profile_df is not None and not segment_df.empty:
        p = profile_df.copy()
        p = p.merge(segment_df[["customer_id", "usage_segment"]], on="customer_id", how="left")
        p["usage_segment"] = p["usage_segment"].fillna("미분류")
        compare_features = [
            "pre_year_avg_transfer_count",
            "pre30_transfer_count",
            "post30_ai_transfer_count",
            "feedback_like_count",
            "feedback_dislike_count",
            "unanswered_count",
        ]
        num_cols = [c for c in compare_features if c in p.columns]
        out_rows = []
        for c in num_cols:
            grp = p.groupby("usage_segment")[c].mean().reset_index()
            for _, r in grp.iterrows():
                out_rows.append({"feature": c, "usage_segment": r["usage_segment"], "mean_value": r[c]})
        t9_num = pd.DataFrame(out_rows)
        if not t9_num.empty:
            tables["item9_characteristics_numeric"] = save_table(t9_num, out_dir, "item9_characteristics_numeric")

        # 범주형(나이대/임직원) 분포
        cat_tables = []
        for c in ["age_band", "is_employee"]:
            if c in p.columns:
                t = (
                    p.groupby(["usage_segment", c])["customer_id"]
                    .nunique()
                    .reset_index(name="users")
                    .sort_values(["usage_segment", "users"], ascending=[True, False])
                )
                t["ratio_in_segment"] = t.groupby("usage_segment")["users"].transform(lambda s: s / s.sum())
                t["feature"] = c
                cat_tables.append(t)
        if cat_tables:
            t9_cat = pd.concat(cat_tables, ignore_index=True)
            tables["item9_characteristics_categorical"] = save_table(
                t9_cat, out_dir, "item9_characteristics_categorical"
            )

        comments["item9"] = (
            "재사용군/미사용군의 사전 활동성(이체경험, 최근접속, 피드백 반응)을 분리해 보면 "
            "확장 타깃과 개선 타깃을 분리 운영할 수 있습니다."
        )

    return AnalysisOutputs(tables=tables, comments=comments, extras=extras)


def md_table_from_csv(path: Optional[Path], max_rows: int = 8) -> str:
    if path is None or not path.exists():
        return "_데이터 없음_"
    df = pd.read_csv(path)
    if df.empty:
        return "_빈 테이블_"
    return df.head(max_rows).to_markdown(index=False)


def build_exec_markdown(
    output: AnalysisOutputs,
    out_dir: Path,
    open_date: pd.Timestamp,
) -> Path:
    # 핵심: "성과 과장" 대신 "초기 도입단계 + 전환개선 과제" 구조
    lines: List[str] = []
    lines.append("# AI서비스 오픈 후 이용현황 점검 및 전환개선 과제")
    lines.append("")
    lines.append(f"- 기준 오픈일: **{open_date.date()}**")
    lines.append("- 보고 관점: **팩트 → 해석 → 액션**")
    lines.append("")
    lines.append("## 0) 이번 보고에서 GPT 초안 대비 보완한 분석 포인트")
    lines.append("- 단순 전후 평균 비교만으로 결론 내리면 왜곡될 수 있어, **비율 지표(로그인 1천명당 AI가입)**를 병행했습니다.")
    lines.append("- 오픈 후 기간이 짧아(4주 내외) 통계적 단정이 어려우므로, **이벤트 전후 7일/14일 반응 형태**를 분리했습니다.")
    lines.append("- 가입시점이 제각각인 이슈는 **가입일 기준 코호트(7일/30일 재사용)**로 정렬해 해결했습니다.")
    lines.append("")

    section_map = [
        ("1) AI서비스 오픈 전후 로그인 추이", "item1", "item1_login_prepost"),
        ("2) 오픈 전후 신규가입자(첫계좌) 추이", "item2", "item2_new_signup_prepost"),
        ("3) 일자별 AI가입 추이 + 이벤트 시점 비교", "item3", "item3_ai_signup_prepost"),
        ("4) 배너 클릭 후 AI가입 전환율", "item4", "item4_banner_conversion"),
        ("5) AI가입일과 신규가입일 일치 여부", "item5", "item5_signup_gap"),
        ("6) AI가입 전후 이체 사용 양상 비교", "item6", "item6_transfer_funnel"),
        ("7) AI서비스 재사용 현황", "item7", "item7_reuse_metrics"),
        ("8) AI가입 후 미사용 고객", "item8", "item8_non_use"),
        ("9) 미사용자 vs 재사용자 특성", "item9", "item9_characteristics_numeric"),
    ]

    for title, c_key, t_key in section_map:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("### 팩트")
        lines.append(md_table_from_csv(output.tables.get(t_key)))
        lines.append("")
        lines.append("### 해석")
        lines.append(output.comments.get(c_key, "해석 코멘트를 생성할 수 없습니다."))
        lines.append("")
        lines.append("### 액션")
        lines.append(
            "- 좋을 때 멘트: `초기 반응이 확인되어, 반응군 중심 확장 전략을 적용하겠습니다.`  \n"
            "- 나쁠 때 멘트: `구조적 변화는 제한적이며, 가입 규모보다 첫사용/재사용 전환 개선에 집중하겠습니다.`"
        )
        lines.append("")

    lines.append("## 임원 한 장 요약")
    lines.append(
        "- AI서비스는 현재 **대규모 외연확장 단계**라기보다, 기존 활성고객 중심의 **초기 탐색/체험 단계**로 판단됩니다."
    )
    lines.append(
        "- 이벤트/배너는 관심 유발에는 기여하나, 가입·재사용 전환 병목이 남아 있어 **퍼널 중하단 개선**이 우선입니다."
    )
    lines.append(
        "- 향후 KPI는 총가입자 중심에서 `가입 후 첫사용률`, `7일/30일 재사용률`, `AI이체 실행률` 중심으로 전환을 권고합니다."
    )
    lines.append("")

    path = out_dir / "executive_report_draft.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI 임원보고 분석 코드")
    p.add_argument("--daily-file", type=str, default=None)
    p.add_argument("--profile-file", type=str, default=None)
    p.add_argument("--chat-file", type=str, default=None)
    p.add_argument("--ai-transfer-file", type=str, default=None)
    p.add_argument("--event-file", type=str, default=None)
    p.add_argument("--banner-file", type=str, default=None)
    p.add_argument("--open-date", type=str, required=True, help="예: 2026-03-23")
    p.add_argument("--output-dir", type=str, default="output_exec")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)
    open_date = pd.to_datetime(args.open_date, errors="coerce")
    if pd.isna(open_date):
        raise ValueError("--open-date 형식이 잘못되었습니다. 예: 2026-03-23")

    daily_df = load_csv(args.daily_file)
    profile_df = load_csv(args.profile_file)
    chat_df = load_csv(args.chat_file)
    ai_transfer_df = load_csv(args.ai_transfer_file)
    event_df = load_csv(args.event_file)
    banner_df = load_csv(args.banner_file)

    daily_df, profile_df, chat_df, ai_transfer_df, event_df, banner_df = maybe_build_datasets(
        daily_df, profile_df, chat_df, ai_transfer_df, event_df, banner_df
    )

    output = run_analysis(
        daily_df=daily_df,
        profile_df=profile_df,
        chat_df=chat_df,
        ai_transfer_df=ai_transfer_df,
        event_df=event_df,
        banner_df=banner_df,
        open_date=open_date,
        out_dir=out_dir,
    )
    md_path = build_exec_markdown(output, out_dir, open_date)

    print("[DONE] 분석 완료")
    print(f"- 테이블 수: {len(output.tables)}")
    print(f"- 보고서 초안: {md_path}")
    print(f"- 출력 폴더: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
