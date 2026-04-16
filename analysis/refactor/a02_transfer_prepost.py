#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from common import (
    ensure_dir,
    first_existing_column,
    load_csv,
    normalize_chat,
    normalize_profile,
    normalize_ai_transfer,
    parse_date,
    safe_div,
    save_csv,
)


def build_transfer_window_metrics(profile: pd.DataFrame) -> pd.DataFrame:
    needed = [
        "pre30_transfer_count",
        "post30_ai_transfer_count",
        "post30_other_transfer_count",
    ]
    for c in needed:
        if c not in profile.columns:
            profile[c] = np.nan
        profile[c] = pd.to_numeric(profile[c], errors="coerce")

    valid = profile.copy()
    valid["post30_total_transfer_count"] = (
        valid["post30_ai_transfer_count"].fillna(0)
        + valid["post30_other_transfer_count"].fillna(0)
    )
    valid["delta_count"] = valid["post30_total_transfer_count"] - valid["pre30_transfer_count"]

    return pd.DataFrame(
        [
            {"metric": "가입 전 30일 평균 이체건수", "value": valid["pre30_transfer_count"].mean()},
            {"metric": "가입 후 30일 평균 전체 이체건수", "value": valid["post30_total_transfer_count"].mean()},
            {"metric": "가입 후 30일 평균 AI이체건수", "value": valid["post30_ai_transfer_count"].mean()},
            {"metric": "가입 후 30일 평균 기존이체건수", "value": valid["post30_other_transfer_count"].mean()},
            {"metric": "가입 전후 평균 증감(건수)", "value": valid["delta_count"].mean()},
        ]
    )


def age_exposure_table(profile: pd.DataFrame, asof_date: pd.Timestamp | None) -> pd.DataFrame:
    if asof_date is None or "ai_signup_date" not in profile.columns:
        return pd.DataFrame()
    p = profile.dropna(subset=["ai_signup_date"]).copy()
    p["days_since_signup"] = (asof_date - p["ai_signup_date"]).dt.days
    p["exposure_group"] = pd.cut(
        p["days_since_signup"],
        bins=[-10_000, 7, 30, 60, 10_000],
        labels=["~7일", "8~30일", "31~60일", "61일+"],
    )
    t = p.groupby("exposure_group", dropna=False)["customer_id"].nunique().reset_index(name="users")
    t["ratio"] = t["users"] / max(t["users"].sum(), 1)
    return t


def build_funnel(
    profile: pd.DataFrame,
    chat: pd.DataFrame,
    ai_transfer: pd.DataFrame,
) -> pd.DataFrame:
    signup_users = profile["customer_id"].nunique() if "customer_id" in profile.columns else np.nan
    req_users = chat.loc[chat["request_count"] > 0, "customer_id"].nunique() if not chat.empty else np.nan

    transfer_req_users = np.nan
    if not chat.empty and {"customer_id", "service_category"}.issubset(chat.columns):
        mask = chat["service_category"].astype(str).str.contains("이체|transfer", case=False, na=False)
        transfer_req_users = chat.loc[mask, "customer_id"].nunique()

    transfer_exec_users = (
        ai_transfer.loc[ai_transfer["ai_transfer_count"] > 0, "customer_id"].nunique()
        if not ai_transfer.empty and {"customer_id", "ai_transfer_count"}.issubset(ai_transfer.columns)
        else np.nan
    )

    return pd.DataFrame(
        [
            {"stage": "AI가입자", "users": signup_users, "ratio_vs_signup": 1.0},
            {"stage": "AI요청 경험자", "users": req_users, "ratio_vs_signup": safe_div(req_users, signup_users)},
            {"stage": "AI이체 요청 경험자", "users": transfer_req_users, "ratio_vs_signup": safe_div(transfer_req_users, signup_users)},
            {"stage": "AI이체 실행자", "users": transfer_exec_users, "ratio_vs_signup": safe_div(transfer_exec_users, signup_users)},
        ]
    )


def interpretation(metrics: pd.DataFrame, exposure: pd.DataFrame, funnel: pd.DataFrame) -> str:
    delta = metrics.loc[metrics["metric"] == "가입 전후 평균 증감(건수)", "value"]
    delta = float(delta.iloc[0]) if len(delta) else np.nan
    exec_ratio = funnel.loc[funnel["stage"] == "AI이체 실행자", "ratio_vs_signup"]
    exec_ratio = float(exec_ratio.iloc[0]) if len(exec_ratio) else np.nan

    short_share = np.nan
    if not exposure.empty:
        s = exposure.loc[exposure["exposure_group"].astype(str).isin(["~7일", "8~30일"]), "ratio"].sum()
        short_share = float(s)

    msgs = []
    if pd.notna(short_share) and short_share >= 0.5:
        msgs.append(
            f"- 관측기간 보정: 가입 후 30일 이내 표본이 {short_share:.1%}로 높아, 장기 정착효과는 과소추정/불안정할 수 있습니다."
        )
    if pd.isna(exec_ratio):
        msgs.append("- AI이체 실행 전환률 계산에 필요한 로그가 불충분합니다.")
    elif exec_ratio < 0.08:
        msgs.append("- 현재는 AI이체 전면확산 단계보다는 탐색/부분 사용 단계로 해석하는 것이 타당합니다.")
    else:
        msgs.append("- AI이체 실행 전환률이 일정 수준 보여, 반복 시나리오 중심 확장 여지가 있습니다.")

    if pd.notna(delta):
        if delta > 0:
            msgs.append("- 가입 전후 전체 이체건수는 소폭 증가 방향입니다(단, 인과는 단정 금지).")
        else:
            msgs.append("- 가입 전후 전체 이체건수 증가 신호는 제한적입니다. 초기 퍼널 개선이 우선입니다.")
    return "\n".join(msgs)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A02: AI가입 전후 이체 비교")
    p.add_argument("--profile-file", required=True)
    p.add_argument("--chat-file", required=True)
    p.add_argument("--ai-transfer-file", required=True)
    p.add_argument("--asof-date", default=None, help="예: 2026-04-20, 미입력시 로그 max date")
    p.add_argument("--output-dir", default="output_refactor/a02")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)

    profile = normalize_profile(load_csv(args.profile_file))
    chat = normalize_chat(load_csv(args.chat_file))

    ai_transfer = normalize_ai_transfer(load_csv(args.ai_transfer_file))

    asof = parse_date(args.asof_date) if args.asof_date else None
    if asof is None and not chat.empty and "chat_date" in chat.columns:
        asof = chat["chat_date"].max()

    metrics = build_transfer_window_metrics(profile)
    exposure = age_exposure_table(profile, asof)
    funnel = build_funnel(profile, chat, ai_transfer)
    note = interpretation(metrics, exposure, funnel)

    save_csv(metrics, out_dir / "a02_transfer_prepost_metrics.csv")
    save_csv(exposure, out_dir / "a02_exposure_distribution.csv")
    save_csv(funnel, out_dir / "a02_transfer_funnel.csv")
    (out_dir / "a02_interpretation.txt").write_text(note + "\n", encoding="utf-8")

    print("[DONE] A02 완료")
    print(f"- output: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

