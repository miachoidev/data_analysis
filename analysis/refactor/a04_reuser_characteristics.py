#!/usr/bin/env python3
"""
분석 4) 재사용자 특징 가설 검증
- 가설1: STT가 편해서 재사용
- 가설2: 특정 연령대(60+ 또는 젊은층)가 재사용
- 가설3: 메뉴이동/추천 편의 때문에 재사용
- 가설4: 이체 편의 때문에 재사용
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from common import (
    ensure_dir,
    load_csv,
    normalize_chat,
    normalize_profile,
    parse_age_num,
    permutation_pvalue_mean_diff,
    safe_div,
    save_csv,
)


def group_labels(reuse_min_req: int) -> tuple[str, str]:
    return (
        f"재사용({reuse_min_req}건 이상)",
        f"미사용/미재사용(0~{max(reuse_min_req - 1, 0)}건)",
    )


def build_reuse_group(profile_df: pd.DataFrame, chat_df: pd.DataFrame, reuse_min_req: int) -> pd.DataFrame:
    ai_base = (
        profile_df[["customer_id", "ai_signup_date"]]
        .dropna(subset=["customer_id", "ai_signup_date"])
        .drop_duplicates(subset=["customer_id"])
    )
    c = chat_df.copy()
    g = c.groupby("customer_id", as_index=False).agg(total_ai_requests=("request_count", "sum"))
    g = ai_base[["customer_id"]].merge(g, on="customer_id", how="left")
    g["total_ai_requests"] = pd.to_numeric(g["total_ai_requests"], errors="coerce").fillna(0)
    reuse_label, non_label = group_labels(reuse_min_req)
    g["reuse_group"] = np.where(
        g["total_ai_requests"] >= reuse_min_req,
        reuse_label,
        non_label,
    )
    return g


def add_signals(
    profile_df: pd.DataFrame,
    chat_df: pd.DataFrame,
    group_df: pd.DataFrame,
    senior_age: int,
) -> pd.DataFrame:
    base = group_df.merge(profile_df, on="customer_id", how="left")

    c = chat_df.copy()
    c["svc_txt"] = c.get("service_category", "").astype(str).str.lower()
    c["intent_txt"] = c.get("intent_code", "").astype(str).str.lower()
    c["txt"] = c["svc_txt"] + "|" + c["intent_txt"]

    c["stt_sig"] = c["txt"].str.contains(r"stt|음성|voice", regex=True, na=False)
    c["menu_sig"] = c["txt"].str.contains(r"메뉴|menu|추천|이동", regex=True, na=False)
    c["transfer_sig"] = c["txt"].str.contains(r"이체|transfer", regex=True, na=False)

    sig = c.groupby("customer_id", as_index=False).agg(
        stt_signal_count=("request_count", lambda s: s[c.loc[s.index, "stt_sig"]].sum()),
        menu_signal_count=("request_count", lambda s: s[c.loc[s.index, "menu_sig"]].sum()),
        transfer_signal_count=("request_count", lambda s: s[c.loc[s.index, "transfer_sig"]].sum()),
        total_ai_requests_log=("request_count", "sum"),
    )
    base = base.merge(sig, on="customer_id", how="left")
    for col in ["stt_signal_count", "menu_signal_count", "transfer_signal_count", "total_ai_requests_log"]:
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0)

    base["age_num"] = base["age_band"].apply(parse_age_num) if "age_band" in base.columns else np.nan
    base["is_senior"] = base["age_num"] >= senior_age
    base["is_young"] = base["age_num"] < 40

    base["stt_share"] = np.where(
        base["total_ai_requests_log"] > 0,
        base["stt_signal_count"] / base["total_ai_requests_log"],
        np.nan,
    )
    base["menu_share"] = np.where(
        base["total_ai_requests_log"] > 0,
        base["menu_signal_count"] / base["total_ai_requests_log"],
        np.nan,
    )
    base["transfer_share"] = np.where(
        base["total_ai_requests_log"] > 0,
        base["transfer_signal_count"] / base["total_ai_requests_log"],
        np.nan,
    )
    return base


def compare_feature(
    df: pd.DataFrame,
    feature: str,
    reuse_label: str,
    non_label: str,
) -> Dict[str, float]:
    r = df[df["reuse_group"] == reuse_label][feature]
    n = df[df["reuse_group"] == non_label][feature]
    reuse_mean = pd.to_numeric(r, errors="coerce").mean()
    non_mean = pd.to_numeric(n, errors="coerce").mean()
    return {
        "feature": feature,
        "reuse_mean": reuse_mean,
        "nonreuse_mean": non_mean,
        "diff": reuse_mean - non_mean,
        "uplift_ratio": safe_div(reuse_mean, non_mean),
        "perm_pvalue": permutation_pvalue_mean_diff(r, n, n_perm=1200),
    }


def run(
    profile_file: str,
    chat_file: str,
    out_dir: Path,
    reuse_min_req: int,
    senior_age: int,
) -> Dict[str, Path]:
    profile = normalize_profile(load_csv(profile_file))
    chat = normalize_chat(load_csv(chat_file))
    if profile.empty or chat.empty:
        raise ValueError("profile/chat 데이터가 필요합니다.")

    for col in ["customer_id", "request_count"]:
        if col not in chat.columns:
            raise ValueError(f"chat 필수컬럼 없음: {col}")
    if "customer_id" not in profile.columns:
        raise ValueError("profile 필수컬럼 없음: customer_id")

    if "ai_signup_date" not in profile.columns:
        raise ValueError("profile 필수컬럼 없음: ai_signup_date")

    reuse_label, non_label = group_labels(reuse_min_req)
    grp = build_reuse_group(profile, chat, reuse_min_req)
    df = add_signals(profile, chat, grp, senior_age)

    # 가설별 지표
    features: List[str] = [
        "stt_signal_count",   # 가설1
        "stt_share",          # 가설1
        "is_senior",          # 가설2(60+)
        "is_young",           # 가설2(젊은층 대안)
        "menu_signal_count",  # 가설3
        "menu_share",         # 가설3
        "transfer_signal_count",  # 가설4
        "transfer_share",         # 가설4
    ]
    rows = []
    for f in features:
        if f in df.columns:
            rows.append(compare_feature(df, f, reuse_label, non_label))
    t = pd.DataFrame(rows)
    save1 = save_csv(t, out_dir, "a04_reuser_hypothesis_results.csv")

    # 요약 판정
    verdict_rows = []
    mapping = {
        "stt_signal_count": "가설1_STT",
        "stt_share": "가설1_STT",
        "is_senior": "가설2_노년층",
        "is_young": "가설2_젊은층",
        "menu_signal_count": "가설3_메뉴",
        "menu_share": "가설3_메뉴",
        "transfer_signal_count": "가설4_이체",
        "transfer_share": "가설4_이체",
    }
    for _, r in t.iterrows():
        verdict = "약한신호"
        if pd.notna(r["diff"]) and pd.notna(r["perm_pvalue"]):
            if r["diff"] > 0 and r["perm_pvalue"] < 0.10:
                verdict = "가설지지"
            elif r["diff"] <= 0 and r["perm_pvalue"] < 0.10:
                verdict = "가설기각"
        verdict_rows.append(
            {
                "hypothesis": mapping.get(r["feature"], r["feature"]),
                "feature": r["feature"],
                "diff": r["diff"],
                "perm_pvalue": r["perm_pvalue"],
                "verdict": verdict,
            }
        )
    verdict_df = pd.DataFrame(verdict_rows).sort_values(["hypothesis", "perm_pvalue"])
    save2 = save_csv(verdict_df, out_dir, "a04_reuser_hypothesis_verdict.csv")
    return {"a04_reuser_hypothesis_results": save1, "a04_reuser_hypothesis_verdict": save2}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="분석4) 재사용자 특징 가설 검증")
    p.add_argument("--profile-file", required=True)
    p.add_argument("--chat-file", required=True)
    p.add_argument("--output-dir", default="output_refactor")
    p.add_argument("--reuse-min-req", type=int, default=3)
    p.add_argument("--senior-age", type=int, default=60)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.output_dir)
    ensure_dir(out)
    saved = run(
        profile_file=args.profile_file,
        chat_file=args.chat_file,
        out_dir=out,
        reuse_min_req=args.reuse_min_req,
        senior_age=args.senior_age,
    )
    print("[DONE] a04 완료")
    for k, v in saved.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()

