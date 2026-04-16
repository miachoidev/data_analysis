#!/usr/bin/env python3
"""
5) 미사용/미재사용 원인 가설 검증
- N1: 초기 답변불가 경험이 미재사용과 연관되는가
- N2: 여신고객(대출계좌건수>=1)이 미재사용에 많은가
- N3: 탈회/특정 직군이 미재사용에 많은가
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import (
    ensure_dir,
    load_csv,
    normalize_chat,
    normalize_profile,
    print_md_table,
    save_csv,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A05 미재사용 원인 분석")
    p.add_argument("--profile-file", required=True)
    p.add_argument("--chat-file", required=True)
    p.add_argument("--output-dir", default="output_refactor")
    p.add_argument("--nonreuse-max-req", type=int, default=2)
    return p.parse_args()


def group_labels(nonreuse_max_req: int) -> tuple[str, str]:
    return (
        f"미사용/미재사용(0~{nonreuse_max_req}건)",
        f"재사용({nonreuse_max_req + 1}건 이상)",
    )


def build_reuse_group(
    profile_df: pd.DataFrame,
    chat_df: pd.DataFrame,
    nonreuse_max_req: int,
) -> pd.DataFrame:
    ai_base = (
        profile_df[["customer_id", "ai_signup_date"]]
        .dropna(subset=["customer_id", "ai_signup_date"])
        .drop_duplicates(subset=["customer_id"])
    )
    c = chat_df.copy()
    user = c.groupby("customer_id", as_index=False).agg(total_ai_requests=("request_count", "sum"))
    user = ai_base[["customer_id"]].merge(user, on="customer_id", how="left")
    user["total_ai_requests"] = pd.to_numeric(user["total_ai_requests"], errors="coerce").fillna(0)
    non_label, reuse_label = group_labels(nonreuse_max_req)
    user["reuse_group"] = np.where(
        user["total_ai_requests"] <= nonreuse_max_req,
        non_label,
        reuse_label,
    )
    return user


def build_unanswered_features(chat_df: pd.DataFrame) -> pd.DataFrame:
    c = chat_df.copy()
    txt = c["service_category"].astype(str) + "|" + c["intent_code"].astype(str)
    txt = txt.str.lower()
    c["is_unanswered"] = txt.str.contains("답변불가|unanswered|not_answerable|fallback", regex=True, na=False)
    c["unans_req"] = np.where(c["is_unanswered"], c["request_count"], 0)

    user = c.groupby("customer_id", as_index=False).agg(
        total_ai_requests=("request_count", "sum"),
        unanswered_count=("unans_req", "sum"),
        first_chat_date=("chat_date", "min"),
    )
    user["unanswered_rate"] = np.where(
        user["total_ai_requests"] > 0,
        user["unanswered_count"] / user["total_ai_requests"],
        np.nan,
    )
    user["has_unanswered"] = user["unanswered_count"] > 0
    user["all_unanswered"] = user["unanswered_count"] >= user["total_ai_requests"]

    # first-response (exact/proxy)
    has_dt = "request_datetime" in c.columns and c["request_datetime"].notna().any()
    event_like = c["request_count"].le(1).all()

    if has_dt and event_like:
        first = c.sort_values(["customer_id", "request_datetime"]).groupby("customer_id", as_index=False).first()
        first_flag = first[["customer_id", "is_unanswered"]].rename(
            columns={"is_unanswered": "first_unanswered_flag"}
        )
        mode = "exact_first_response"
    else:
        day = c.groupby(["customer_id", "chat_date"], as_index=False).agg(
            day_total=("request_count", "sum"),
            day_unans=("unans_req", "sum"),
        )
        first = day.sort_values(["customer_id", "chat_date"]).groupby("customer_id", as_index=False).first()
        first["first_unanswered_flag"] = first["day_unans"] > 0
        first_flag = first[["customer_id", "first_unanswered_flag"]]
        mode = "first_day_proxy"

    out = user.merge(first_flag, on="customer_id", how="left")
    out["first_unanswered_flag"] = out["first_unanswered_flag"].fillna(False)
    out["first_unanswered_mode"] = mode
    return out


def test_n1(df: pd.DataFrame, non_label: str, reuse_label: str) -> pd.DataFrame:
    rows = []
    grp = df.groupby("reuse_group")
    for col, label in [
        ("has_unanswered", "답변불가 경험률"),
        ("unanswered_rate", "답변불가 비율"),
        ("first_unanswered_flag", "첫응답(또는첫요청일) 답변불가율"),
        ("all_unanswered", "요청 전부 답변불가율"),
    ]:
        if col not in df.columns:
            continue
        vals = grp[col].mean()
        non = vals.get(non_label, np.nan)
        reu = vals.get(reuse_label, np.nan)
        rows.append(
            {
                "hypothesis": "N1",
                "metric": label,
                "nonreuse_rate": non,
                "reuse_rate": reu,
                "diff_nonreuse_minus_reuse": non - reu,
            }
        )
    return pd.DataFrame(rows)


def test_n2(df: pd.DataFrame, non_label: str, reuse_label: str) -> pd.DataFrame:
    if "loan_customer_flag" not in df.columns:
        return pd.DataFrame()
    vals = df.groupby("reuse_group")["loan_customer_flag"].mean()
    return pd.DataFrame(
        [
            {
                "hypothesis": "N2",
                "metric": "여신고객 비율(대출계좌건수>=1 포함)",
                "nonreuse_rate": vals.get(non_label, np.nan),
                "reuse_rate": vals.get(reuse_label, np.nan),
                "diff_nonreuse_minus_reuse": vals.get(non_label, np.nan) - vals.get(reuse_label, np.nan),
            }
        ]
    )


def test_n3(df: pd.DataFrame, non_label: str, reuse_label: str) -> pd.DataFrame:
    rows = []
    if "is_churned" in df.columns:
        vals = df.groupby("reuse_group")["is_churned"].mean()
        rows.append(
            {
                "hypothesis": "N3",
                "metric": "탈회비율",
                "nonreuse_rate": vals.get(non_label, np.nan),
                "reuse_rate": vals.get(reuse_label, np.nan),
                "diff_nonreuse_minus_reuse": vals.get(non_label, np.nan) - vals.get(reuse_label, np.nan),
            }
        )
    if "job_group" in df.columns:
        top = (
            df.groupby(["reuse_group", "job_group"])["customer_id"]
            .nunique()
            .reset_index(name="users")
            .sort_values(["reuse_group", "users"], ascending=[True, False])
        )
        top["ratio_in_group"] = top.groupby("reuse_group")["users"].transform(lambda s: s / s.sum())
        # top 3 by nonreuse
        non = top[top["reuse_group"] == non_label].head(3).copy()
        for _, r in non.iterrows():
            rows.append(
                {
                    "hypothesis": "N3",
                    "metric": f"미재사용 상위직군:{r['job_group']}",
                    "nonreuse_rate": r["ratio_in_group"],
                    "reuse_rate": np.nan,
                    "diff_nonreuse_minus_reuse": np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)

    profile = normalize_profile(load_csv(args.profile_file))
    chat = normalize_chat(load_csv(args.chat_file))

    if "customer_id" not in profile.columns or "customer_id" not in chat.columns:
        raise ValueError("profile/chat 모두 customer_id 필요")

    non_label, reuse_label = group_labels(args.nonreuse_max_req)
    reuse = build_reuse_group(profile, chat, args.nonreuse_max_req)
    unans = build_unanswered_features(chat)

    base = profile.merge(reuse, on="customer_id", how="inner")
    base = base.merge(unans, on="customer_id", how="left")

    # optional columns normalization
    if "is_churned" in base.columns:
        base["is_churned"] = base["is_churned"].astype(str).str.strip().str.upper().isin(["Y", "TRUE", "1"])
    elif "withdrawn_yn" in base.columns:
        base["is_churned"] = base["withdrawn_yn"].astype(str).str.strip().str.upper().eq("Y")

    t_n1 = test_n1(base, non_label, reuse_label)
    t_n2 = test_n2(base, non_label, reuse_label)
    t_n3 = test_n3(base, non_label, reuse_label)
    t_all = pd.concat([t_n1, t_n2, t_n3], ignore_index=True)

    mode = unans["first_unanswered_mode"].dropna().iloc[0] if not unans.empty else "unknown"
    t_mode = pd.DataFrame([{"first_unanswered_mode": mode}])

    save_csv(t_all, out_dir, "a05_nonreuse_hypothesis")
    save_csv(t_mode, out_dir, "a05_first_unanswered_mode")

    print_md_table("A05 미사용 원인 가설 검증", t_all)
    print_md_table("A05 첫응답 판별 모드", t_mode)

    # short interpretation helper
    low = t_n1[t_n1["metric"] == "첫응답(또는첫요청일) 답변불가율"]
    if not low.empty:
        diff = low["diff_nonreuse_minus_reuse"].iloc[0]
        if pd.notna(diff) and diff > 0.05:
            print("[해석] 미재사용군의 초기 답변불가 경험률이 높아, 초기 실패경험이 이탈에 기여했을 가능성이 큽니다.")
        else:
            print("[해석] 초기 답변불가 단일 요인만으로 미재사용을 설명하기 어렵고, 가입허들/가치체감 요인을 함께 봐야 합니다.")


if __name__ == "__main__":
    main()
