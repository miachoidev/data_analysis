#!/usr/bin/env python3
"""
분석 1)
- AI가입일 = 전자금융가입일 사용자 건수/비율
- 이벤트 날짜(오픈/광고/이벤트/배너추가) 기준 신규가입→AI가입 동시전환 검증
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from common import (
    ensure_dir,
    first_existing_column,
    load_csv,
    print_md_table,
    to_datetime,
    safe_div,
)


def normalize_profile(df: pd.DataFrame) -> pd.DataFrame:
    mapper = {
        "customer_id": ["customer_id", "고객번호"],
        "ebank_signup_date": ["ebank_signup_date", "전자금융가입일", "first_account_open_date"],
        "ai_signup_date": ["ai_signup_date", "AI가입일", "ai_join_date"],
        "ai_signup_yn": ["ai_signup_yn", "AI가입여부", "ai_join_yn"],
    }
    rename = {}
    for std, cands in mapper.items():
        c = first_existing_column(df, cands)
        if c:
            rename[c] = std
    out = df.rename(columns=rename).copy()
    to_datetime(out, ["ebank_signup_date", "ai_signup_date"])
    if "ai_signup_yn" in out.columns:
        s = out["ai_signup_yn"].astype(str).str.strip().str.lower()
        out["ai_signup_yn"] = s.isin(["1", "y", "yes", "true", "t", "가입", "완료"])
    return out


def analyze_signup_alignment(profile: pd.DataFrame) -> pd.DataFrame:
    p = profile.copy()
    if not {"customer_id", "ebank_signup_date", "ai_signup_date"}.issubset(p.columns):
        return pd.DataFrame()
    p = p.dropna(subset=["customer_id", "ebank_signup_date", "ai_signup_date"])
    p["gap_days"] = (p["ai_signup_date"] - p["ebank_signup_date"]).dt.days

    rows = []
    rows.append(("동일일(0일)", (p["gap_days"] == 0)))
    rows.append(("1~7일", (p["gap_days"] >= 1) & (p["gap_days"] <= 7)))
    rows.append(("8~30일", (p["gap_days"] >= 8) & (p["gap_days"] <= 30)))
    rows.append(("30일 초과", (p["gap_days"] > 30)))
    rows.append(("AI가입이 더 빠름(데이터점검)", (p["gap_days"] < 0)))

    out = []
    total = p["customer_id"].nunique()
    for name, mask in rows:
        users = p.loc[mask, "customer_id"].nunique()
        out.append({"구간": name, "고객수": users, "비율": safe_div(users, total)})
    return pd.DataFrame(out)


def build_daily_from_profile(profile: pd.DataFrame) -> pd.DataFrame:
    """
    profile 기반으로 일자별 신규가입/AI가입 집계 생성
    """
    out_rows: List[dict] = []

    if {"customer_id", "ebank_signup_date"}.issubset(profile.columns):
        t = (
            profile.dropna(subset=["ebank_signup_date"])
            .groupby("ebank_signup_date")["customer_id"]
            .nunique()
            .reset_index(name="new_signups")
            .rename(columns={"ebank_signup_date": "date"})
        )
        out_rows.append(t)

    if {"customer_id", "ai_signup_date"}.issubset(profile.columns):
        t = (
            profile.dropna(subset=["ai_signup_date"])
            .groupby("ai_signup_date")["customer_id"]
            .nunique()
            .reset_index(name="ai_signups")
            .rename(columns={"ai_signup_date": "date"})
        )
        out_rows.append(t)

    if not out_rows:
        return pd.DataFrame()

    daily = out_rows[0]
    for t in out_rows[1:]:
        daily = daily.merge(t, on="date", how="outer")
    daily = daily.sort_values("date")
    daily["new_signups"] = daily.get("new_signups", 0).fillna(0)
    daily["ai_signups"] = daily.get("ai_signups", 0).fillna(0)
    daily["same_day_new_and_ai"] = daily[["new_signups", "ai_signups"]].min(axis=1)
    daily["same_day_conv_proxy"] = daily.apply(
        lambda r: safe_div(r["same_day_new_and_ai"], r["new_signups"]), axis=1
    )
    return daily


def analyze_event_windows(daily: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or events.empty:
        return pd.DataFrame()
    event_date_col = first_existing_column(events, ["event_date", "일자", "날짜"])
    event_name_col = first_existing_column(events, ["event_name", "이벤트명", "event"])
    if not event_date_col:
        return pd.DataFrame()

    e = events.copy()
    to_datetime(e, [event_date_col])
    rows = []
    for _, r in e.dropna(subset=[event_date_col]).iterrows():
        dt = r[event_date_col]
        pre = daily[(daily["date"] >= dt - pd.Timedelta(days=7)) & (daily["date"] < dt)]
        post = daily[(daily["date"] >= dt) & (daily["date"] < dt + pd.Timedelta(days=7))]

        pre_new = pre["new_signups"].mean()
        post_new = post["new_signups"].mean()
        pre_ai = pre["ai_signups"].mean()
        post_ai = post["ai_signups"].mean()
        pre_conv = pre["same_day_conv_proxy"].mean()
        post_conv = post["same_day_conv_proxy"].mean()

        rows.append(
            {
                "이벤트명": r[event_name_col] if event_name_col else str(dt.date()),
                "이벤트일": dt.date(),
                "신규가입_전7일평균": pre_new,
                "신규가입_후7일평균": post_new,
                "신규가입_증감률": safe_div(post_new - pre_new, pre_new),
                "AI가입_전7일평균": pre_ai,
                "AI가입_후7일평균": post_ai,
                "AI가입_증감률": safe_div(post_ai - pre_ai, pre_ai),
                "동일일전환_전7일평균": pre_conv,
                "동일일전환_후7일평균": post_conv,
                "동일일전환_증감": post_conv - pre_conv if pd.notna(pre_conv) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def suggest_comment(alignment: pd.DataFrame) -> str:
    if alignment.empty:
        return "가입일 정합 분석을 위한 컬럼(전자금융가입일, AI가입일)이 부족합니다."
    same_ratio = alignment.loc[alignment["구간"] == "동일일(0일)", "비율"]
    same_ratio = same_ratio.iloc[0] if len(same_ratio) else np.nan
    if pd.isna(same_ratio):
        return "동일일 가입 비율 계산이 불가능합니다."
    if same_ratio >= 0.20:
        return (
            f"동일일 가입 비율이 {same_ratio:.1%}로, 신규유입 구간에서 AI 동시진입 신호가 확인됩니다."
        )
    if same_ratio >= 0.10:
        return (
            f"동일일 가입 비율은 {same_ratio:.1%}로 중간 수준이며, 온보딩 메시지 개선 시 동시진입 확대 여지가 있습니다."
        )
    return (
        f"동일일 가입 비율은 {same_ratio:.1%}로 제한적이며, 현재는 신규가입자 즉시전환보다 기존사용자의 탐색적 수용 패턴이 우세합니다."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--profile-file", required=True)
    p.add_argument("--event-file", default=None)
    p.add_argument("--open-date", default=None)  # run_all 호환용(미사용)
    p.add_argument("--output-dir", default="output_exec")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)

    profile_raw = load_csv(args.profile_file)
    profile = normalize_profile(profile_raw if profile_raw is not None else pd.DataFrame())
    events_raw = load_csv(args.event_file)
    events = events_raw if events_raw is not None else pd.DataFrame()

    alignment = analyze_signup_alignment(profile)
    daily = build_daily_from_profile(profile)
    event_table = analyze_event_windows(daily, events) if not events.empty else pd.DataFrame()

    print_md_table("1-A) AI가입일 vs 전자금융가입일", alignment)
    print_md_table("1-B) 이벤트 전후 신규/AI/동일일전환", event_table)
    print("\n[해석가이드]")
    print("-", suggest_comment(alignment))

    alignment.to_csv(out_dir / "a01_signup_alignment.csv", index=False, encoding="utf-8-sig")
    event_table.to_csv(out_dir / "a01_event_new_ai_conversion.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()

