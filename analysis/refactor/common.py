#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


def safe_div(n: float, d: float) -> float:
    if d is None or d == 0 or pd.isna(d):
        return np.nan
    return n / d


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    cset = set(df.columns)
    for c in candidates:
        if c in cset:
            return c
    return None


def to_datetime(df: pd.DataFrame, columns: Iterable[str]) -> None:
    for c in columns:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")


def parse_dates(df: pd.DataFrame, columns: Iterable[str]) -> None:
    to_datetime(df, columns)


def parse_date(value: Optional[str]) -> Optional[pd.Timestamp]:
    if value is None or str(value).strip() == "":
        return None
    v = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(v) else v


def load_csv(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"[WARN] 파일 없음: {p}")
        return None
    return pd.read_csv(p)


def load_csv_or_empty(path: Optional[str]) -> pd.DataFrame:
    df = load_csv(path)
    return df if df is not None else pd.DataFrame()


def normalize_bool_series(s: pd.Series) -> pd.Series:
    txt = s.astype(str).str.strip().str.lower()
    is_true_text = txt.isin(["1", "y", "yes", "true", "t", "on"])
    num = pd.to_numeric(s, errors="coerce").fillna(0)
    return is_true_text | num.gt(0)


def to_bool_series(primary: pd.Series, secondary: Optional[pd.Series] = None) -> pd.Series:
    base = normalize_bool_series(primary.fillna(""))
    if secondary is not None:
        sec = pd.to_numeric(secondary, errors="coerce").fillna(0).gt(0)
        base = base | sec
    return base.fillna(False)


def parse_age_num(v: object) -> float:
    if pd.isna(v):
        return np.nan
    nums = re.findall(r"\d+", str(v))
    if not nums:
        return np.nan
    return float(nums[0])


def permutation_pvalue_mean_diff(a: pd.Series, b: pd.Series, n_perm: int = 1000) -> float:
    x = pd.to_numeric(a, errors="coerce").dropna().values
    y = pd.to_numeric(b, errors="coerce").dropna().values
    if len(x) < 2 or len(y) < 2:
        return np.nan
    rng = np.random.default_rng(42)
    obs = abs(np.mean(x) - np.mean(y))
    combined = np.concatenate([x, y])
    n_x = len(x)
    cnt = 0
    for _ in range(n_perm):
        rng.shuffle(combined)
        diff = abs(np.mean(combined[:n_x]) - np.mean(combined[n_x:]))
        if diff >= obs:
            cnt += 1
    return (cnt + 1) / (n_perm + 1)


def print_md_table(title: str, df: pd.DataFrame, digits: int = 4) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)
    if df is None or len(df) == 0:
        print("(데이터 없음)")
        return
    out = df.copy()
    num_cols = out.select_dtypes(include=["number"]).columns
    for c in num_cols:
        out[c] = out[c].round(digits)
    try:
        print(out.to_markdown(index=False))
    except Exception:
        print(out.to_string(index=False))


def normalize_profile(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    mapper = {
        "customer_id": ["customer_id", "고객번호", "사용자번호"],
        "age_band": ["age_band", "나이대"],
        "is_employee": ["is_employee", "임직원여부"],
        "job_group_large": ["job_group_large", "직군대분류", "직군대"],
        "job_group_mid": ["job_group_mid", "직군중분류", "직군중"],
        "job_group_small": ["job_group_small", "직군소분류", "직군소"],
        "job_group_detail": ["job_group_detail", "직군세분류", "직군세"],
        "withdrawn_yn": ["withdrawn_yn", "탈회여부", "해지여부"],
        "loan_customer": ["loan_customer", "여신고객여부", "is_loan_customer", "loan_yn"],
        "loan_account_count": ["loan_account_count", "대출계좌건수", "loan_acct_cnt", "loan_cnt"],
        "ebank_signup_date": ["ebank_signup_date", "전자금융가입일", "first_account_open_date"],
        "ai_signup_date": ["ai_signup_date", "AI가입일", "ai_join_date", "가입일자"],
        "pre30_transfer_count": ["pre30_transfer_count", "AI가입전30일_이체건수"],
        "post30_ai_transfer_count": ["post30_ai_transfer_count", "AI가입후30일_ai이체건수"],
        "post30_other_transfer_count": ["post30_other_transfer_count", "AI가입후30일_기존이체건수"],
        "stt_request_count": ["stt_request_count", "STT요청건수", "stt_count"],
        "menu_reco_request_count": ["menu_reco_request_count", "메뉴추천요청건수", "menu_request_count"],
        "unanswered_count": ["unanswered_count", "답변불가경험건수"],
    }
    rename: Dict[str, str] = {}
    for std, cands in mapper.items():
        found = first_existing_column(df, cands)
        if found:
            rename[found] = std
    out = df.rename(columns=rename).copy()
    to_datetime(out, ["ebank_signup_date", "ai_signup_date"])
    for c in [
        "pre30_transfer_count",
        "post30_ai_transfer_count",
        "post30_other_transfer_count",
        "stt_request_count",
        "menu_reco_request_count",
        "unanswered_count",
        "loan_account_count",
    ]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    loan_flag = pd.Series(False, index=out.index)
    if "loan_customer" in out.columns:
        loan_flag = loan_flag | to_bool_series(out["loan_customer"])
    if "loan_account_count" in out.columns:
        loan_flag = loan_flag | out["loan_account_count"].fillna(0).ge(1)
    out["loan_customer_flag"] = loan_flag

    if "withdrawn_yn" in out.columns:
        out["is_churned"] = out["withdrawn_yn"].astype(str).str.strip().str.upper().eq("Y")
    if {"job_group_large", "job_group_mid", "job_group_small", "job_group_detail"} & set(out.columns):
        out["job_group"] = (
            out.get("job_group_large", "").fillna("").astype(str)
            + "|"
            + out.get("job_group_mid", "").fillna("").astype(str)
            + "|"
            + out.get("job_group_small", "").fillna("").astype(str)
            + "|"
            + out.get("job_group_detail", "").fillna("").astype(str)
        ).str.strip("|")
    return out


def normalize_chat(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    mapper = {
        "customer_id": ["customer_id", "고객번호", "사용자번호"],
        "ai_signup_date": ["ai_signup_date", "AI가입일", "ai_join_date", "가입일자"],
        "chat_date": ["chat_date", "ai요청일자", "채팅요청일", "요청일", "date"],
        "request_datetime": ["request_datetime", "요청일시", "ai요청일시", "chat_datetime", "timestamp"],
        "service_category": ["service_category", "요청서비스", "서비스분류", "서비스분류코드"],
        "intent_code": ["intent_code", "의도분류코드", "intent", "intent_subtype"],
        "request_count": ["request_count", "건수", "cnt"],
    }
    rename: Dict[str, str] = {}
    for std, cands in mapper.items():
        found = first_existing_column(df, cands)
        if found:
            rename[found] = std
    out = df.rename(columns=rename).copy()
    to_datetime(out, ["ai_signup_date", "chat_date", "request_datetime"])
    if "chat_date" not in out.columns and "request_datetime" in out.columns:
        out["chat_date"] = out["request_datetime"].dt.floor("D")
    if "intent_code" not in out.columns:
        out["intent_code"] = ""
    if "service_category" not in out.columns:
        out["service_category"] = ""
    if "request_count" not in out.columns:
        out["request_count"] = 1
    out["request_count"] = pd.to_numeric(out["request_count"], errors="coerce").fillna(0)
    return out


def normalize_ai_transfer(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    mapper = {
        "customer_id": ["customer_id", "고객번호", "사용자번호"],
        "ai_signup_date": ["ai_signup_date", "AI가입일"],
        "ai_transfer_date": ["ai_transfer_date", "ai이체일"],
        "ai_transfer_count": ["ai_transfer_count", "ai이체건수"],
        "ai_transfer_amount": ["ai_transfer_amount", "금액합", "amount_sum"],
    }
    rename: Dict[str, str] = {}
    for std, cands in mapper.items():
        found = first_existing_column(df, cands)
        if found:
            rename[found] = std
    out = df.rename(columns=rename).copy()
    to_datetime(out, ["ai_signup_date", "ai_transfer_date"])
    for c in ["ai_transfer_count", "ai_transfer_amount"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
        else:
            out[c] = 0
    return out


def normalize_event(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    mapper = {
        "event_date": ["event_date", "일자", "날짜"],
        "event_name": ["event_name", "이벤트명", "event"],
        "event_type": ["event_type", "이벤트유형", "type"],
    }
    rename: Dict[str, str] = {}
    for std, cands in mapper.items():
        found = first_existing_column(df, cands)
        if found:
            rename[found] = std
    out = df.rename(columns=rename).copy()
    to_datetime(out, ["event_date"])
    return out


def save_csv(df: pd.DataFrame, out_dir_or_path: Path, filename: Optional[str] = None) -> Path:
    if filename is None:
        p = Path(out_dir_or_path)
    else:
        p = Path(out_dir_or_path) / filename
    if p.suffix == "":
        p = p.with_suffix(".csv")
    ensure_dir(p.parent)
    df.to_csv(p, index=False, encoding="utf-8-sig")
    return p

