"""Automated leakage audit and validation checks for StockPilot pipeline."""

from dataclasses import dataclass, field
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from stockpilot.ml.scaler import LeakageFreeScaler
from stockpilot.ml.split import SplitResult

logger = logging.getLogger(__name__)


@dataclass
class AuditReport:
    passed_all: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    details: Dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = ["=== STOCKPILOT LEAKAGE AUDIT REPORT ==="]
        for check, passed in self.checks.items():
            status = "PASS [OK]" if passed else "FAIL [X]"
            detail = self.details.get(check, "")
            lines.append(f"{status} | {check}: {detail}")
        overall = "ALL AUDIT CHECKS PASSED [LEAKAGE FREE]" if self.passed_all else "LEAKAGE DETECTED [FAILED]"
        lines.append(f"OVERALL STATUS: {overall}")
        return "\n".join(lines)


class LeakageAuditor:
    """Runs automated mathematical and logical checks to verify zero data leakage."""

    def audit_splits(self, split_result: SplitResult) -> Dict[str, bool]:
        """Audits time-series splits for chronological monotonicity and embargo integrity."""
        checks = {}
        details = {}

        train_max = split_result.train["Date"].max()
        val_min = split_result.val["Date"].min()
        val_max = split_result.val["Date"].max()
        test_min = split_result.test["Date"].min()

        chrono_ok = bool((train_max < val_min) and (val_max < test_min))
        checks["Split Chronology Check"] = chrono_ok
        details["Split Chronology Check"] = (
            f"Train max ({train_max.date()}) < Val min ({val_min.date()}) < "
            f"Val max ({val_max.date()}) < Test min ({test_min.date()})"
        )

        embargo_train_val = (val_min - train_max).days
        embargo_val_test = (test_min - val_max).days
        embargo_ok = bool(embargo_train_val >= split_result.embargo_days and embargo_val_test >= split_result.embargo_days)
        checks["Embargo Buffer Check"] = embargo_ok
        details["Embargo Buffer Check"] = (
            f"Train-Val gap: {embargo_train_val} days, Val-Test gap: {embargo_val_test} days "
            f"(required >= {split_result.embargo_days})"
        )

        return checks, details

    def audit_target_shift(self, df: pd.DataFrame, horizons: List[int] = [5, 10, 20]) -> Dict[str, bool]:
        """Verifies that target returns strictly align with future price changes."""
        checks = {}
        details = {}

        for h in horizons:
            col = f"Target_Return_{h}d"
            if col not in df.columns:
                continue

            valid_mask = ~df[col].isna()
            sample_indices = df[valid_mask].index[:20]

            math_matches = True
            for idx in sample_indices:
                future_idx = idx + h
                if future_idx < len(df):
                    actual_return = (df.loc[future_idx, "Close"] - df.loc[idx, "Close"]) / df.loc[idx, "Close"]
                    recorded_target = df.loc[idx, col]
                    if not np.isclose(actual_return, recorded_target, rtol=1e-5):
                        math_matches = False
                        break

            tail_nans = bool(df[col].iloc[-h:].isna().all())

            check_name = f"Target {h}d Shift & Tail NaN Check"
            checks[check_name] = bool(math_matches and tail_nans)
            details[check_name] = f"Sample math correct: {math_matches}, Tail {h} rows NaN: {tail_nans}"

        return checks, details

    def audit_scaler(self, train_df: pd.DataFrame, test_df: pd.DataFrame, scaler: LeakageFreeScaler) -> Dict[str, bool]:
        """Verifies scaler was fitted strictly on train data and not influenced by test data."""
        checks = {}
        details = {}

        targets_in_features = [c for c in scaler.feature_columns if c.startswith("Target_") or c == "Date"]
        checks["Target Exclusion from Features"] = (len(targets_in_features) == 0)
        details["Target Exclusion from Features"] = (
            "No targets or dates in scaled features" if len(targets_in_features) == 0
            else f"Targets found in features: {targets_in_features}"
        )

        if hasattr(scaler.scaler, "center_"):
            train_medians = train_df[scaler.feature_columns].median().fillna(0.0).values
            scaler_centers = scaler.scaler.center_
            diff = np.max(np.abs(train_medians - scaler_centers))
            is_train_based = bool(diff < 1e-4)
            checks["Scaler Train-Only Statistics Check"] = is_train_based
            details["Scaler Train-Only Statistics Check"] = (
                f"Max discrepancy between scaler center and train medians: {diff:.6e}"
            )

        return checks, details

    def run_full_audit(
        self,
        full_df: pd.DataFrame,
        split_result: SplitResult,
        scaler: LeakageFreeScaler,
        horizons: List[int] = [5, 10, 20],
    ) -> AuditReport:
        """Executes all audit tests and returns a consolidated AuditReport."""
        all_checks = {}
        all_details = {}

        c, d = self.audit_splits(split_result)
        all_checks.update(c)
        all_details.update(d)

        c, d = self.audit_target_shift(full_df, horizons=horizons)
        all_checks.update(c)
        all_details.update(d)

        c, d = self.audit_scaler(split_result.train, split_result.test, scaler)
        all_checks.update(c)
        all_details.update(d)

        passed_all = all(all_checks.values())
        report = AuditReport(passed_all=passed_all, checks=all_checks, details=all_details)

        logger.info("\n" + report.summary())
        return report
