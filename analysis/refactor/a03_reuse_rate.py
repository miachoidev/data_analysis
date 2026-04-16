#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from common import (
    ensure_dir,
    load_csv,
    normalize_chat,
    normalize_profile,
    print_md_table,
    safe_div,
    save_csv,
)


def run(
    profile_df: pd.DataFrame,
    chat_df: pd.DataFrame,
    out_dir: Path,
    reuse_min_days: int = 2,
) -> None:
    if profile_df.empty or chat_df.empty:
        print("[WARN] profile/chat 데이터가 없어 분석 불가")
        return

    needed = {"customer_id", "chat_date", "request_count"}
    if not needed.issubset(chat_df.columns):
        print("[WARN] chat 필수 컬럼 누락")
        return

    if not {"customer_id", "ai_signup_date"}.issubset(profile_df.columns):
        print("[WARN] profile 필수 컬럼 누락(customer_id, ai_signup_date)")
        return

    ai_base = (
        profile_df[["customer_id", "ai_signup_date"]]
        .dropna(subset=["customer_id", "ai_signup_date"])
        .drop_duplicates(subset=["customer_id"])
    )
    if ai_base.empty:
        print("[WARN] AI가입자 모수가 없어 분석 불가")
        return

    c = chat_df.dropna(subset=["customer_id", "chat_date"]).copy()
    c = c.merge(ai_base, on="customer_id", how="inner")
    c["day_offset"] = (c["chat_date"] - c["ai_signup_date"]).dt.days
    c = c[c["day_offset"] >= 0]

    user_agg = c.groupby("customer_id", as_index=False).agg(
        total_requests=("request_count", "sum"),
        use_days=("chat_date", "nunique"),
    )
    user = ai_base.merge(user_agg, on="customer_id", how="left")
    user["total_requests"] = user["total_requests"].fillna(0)
    user["use_days"] = user["use_days"].fillna(0)
    user["is_reuser"] = user["use_days"] >= reuse_min_days

    ai_signup_base = ai_base["customer_id"].nunique()

    m = pd.DataFrame(
        [
            {"지표": "AI가입자수", "값": ai_signup_base},
            {"지표": "가입 후 1회 이상 사용자", "값": int((user["total_requests"] > 0).sum())},
            {"지표": f"{reuse_min_days}일 이상 사용자(재사용)", "값": int(user["is_reuser"].sum())},
        ]
    )
    m["비율"] = m["값"].apply(lambda x: safe_div(x, ai_signup_base))
    print_md_table("3) 재사용 핵심지표", m)
    save_csv(m, out_dir, "a03_reuse_summary.csv")

    ratio = safe_div(int(user["is_reuser"].sum()), ai_signup_base)
    if pd.notna(ratio):
        if ratio >= 0.25:
            print(f"[해석] 재사용률 {ratio:.1%}: 초기 정착 신호가 확인됩니다.")
        elif ratio >= 0.12:
            print(f"[해석] 재사용률 {ratio:.1%}: 초기 수용은 있으나 정착 전환은 더 강화가 필요합니다.")
        else:
            print(f"[해석] 재사용률 {ratio:.1%}: 가입 대비 재방문 유도가 핵심 병목입니다.")

    print("[가이드] 재사용자 기준은 2일 이상/3일 이상을 병행 제시하면 해석 안정성이 높아집니다.")


def main() -> None:
    p = argparse.ArgumentParser(description="A03 재사용률 분석")
    p.add_argument("--profile-file", required=True)
    p.add_argument("--chat-file", required=True)
    p.add_argument("--output-dir", default="output_refactor")
    p.add_argument("--reuse-min-days", type=int, default=2)
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)

    profile_df = normalize_profile(load_csv(args.profile_file))
    chat_df = normalize_chat(load_csv(args.chat_file))
    run(profile_df, chat_df, out_dir, args.reuse_min_days)


if __name__ == "__main__":
    main()
