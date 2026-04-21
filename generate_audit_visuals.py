#!/usr/bin/env python3
"""
Generate ClearBias report visuals from CSV query outputs.

Input folder:
  ClearBias_Audit_Files/

Output folder:
  audit_visuals/

All PNGs are saved with transparent background for website/report compositing.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "ClearBias_Audit_Files"
OUTPUT_DIR = ROOT / "audit_visuals"
OUTPUT_DIR.mkdir(exist_ok=True)

# Required project colors (plus complementary accents)
PALETTE = [
    "#e1613b",  # orange
    "#1d355c",  # navy
    "#51aeb1",  # teal
    "#f3a261",  # sand
    "#2a9d8f",
    "#e9c46a",
    "#457b9d",
    "#264653",
]

sns.set_theme(style="whitegrid")
sns.set_palette(PALETTE)
plt.rcParams.update(
    {
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "savefig.facecolor": "none",
        "savefig.transparent": True,
    }
)


def _csv(name: str) -> Path:
    return INPUT_DIR / name


def _save(name: str) -> None:
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / name, dpi=300, transparent=True, bbox_inches="tight")
    plt.close()


def _exists(name: str) -> bool:
    return _csv(name).is_file()


def plot_performance() -> None:
    fn = "benchmark_performance_results.csv"
    if not _exists(fn):
        print(f"Skipping performance: {fn} not found")
        return
    perf = pd.read_csv(_csv(fn))
    melted = perf.melt(
        id_vars=["Task"],
        value_vars=["BPlusTree_ms", "PGM_Sim_ms"],
        var_name="IndexMethod",
        value_name="LatencyMs",
    )
    plt.figure(figsize=(12, 6))
    ax = sns.barplot(data=melted, x="LatencyMs", y="Task", hue="IndexMethod")
    ax.set_title("System Latency Audit: B+ Tree vs PGM Simulation", fontsize=14)
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Task")
    _save("A_performance_benchmark.png")


def plot_demographics() -> None:
    q4, q7 = "q4_Gender_Distribution.csv", "q7_Demographic_Intersection.csv"
    if _exists(q4):
        d = pd.read_csv(_csv(q4))
        plt.figure(figsize=(7, 7))
        plt.pie(
            d["count"],
            labels=d["gender"],
            autopct="%1.1f%%",
            colors=[PALETTE[0], PALETTE[2], PALETTE[1], PALETTE[3]],
            wedgeprops={"linewidth": 1, "edgecolor": "white"},
        )
        plt.title("Demographic Split: Gender Representation", fontsize=14)
        _save("B_gender_distribution.png")
    else:
        print(f"Skipping demographics pie: {q4} not found")

    if _exists(q7):
        d = pd.read_csv(_csv(q7))
        pivot = d.pivot(index="age_group", columns="gender", values="count").fillna(0)
        ax = pivot.plot(kind="bar", stacked=True, figsize=(10, 6), color=[PALETTE[1], PALETTE[2]])
        ax.set_title("Demographic Bias: Age and Gender Intersection", fontsize=14)
        ax.set_xlabel("Age Group")
        ax.set_ylabel("Impression Count")
        _save("C_age_gender_intersection.png")
    else:
        print(f"Skipping demographics bars: {q7} not found")


def plot_category_audit() -> None:
    q6, q8, q5 = "q6_Category_Volume.csv", "q8_CTR_by_Category.csv", "q5_Bias_Audit_Sample.csv"
    if _exists(q6):
        d = pd.read_csv(_csv(q6)).sort_values("count", ascending=False)
        plt.figure(figsize=(10, 5))
        ax = sns.barplot(data=d, x="count", y="ad_category")
        ax.set_title("Ad Category Saturation", fontsize=14)
        ax.set_xlabel("Impression Count")
        ax.set_ylabel("Ad Category")
        _save("D_category_volume.png")
    else:
        print(f"Skipping category volume: {q6} not found")

    if _exists(q8):
        d = pd.read_csv(_csv(q8)).sort_values("avg_ctr", ascending=False)
        plt.figure(figsize=(10, 5))
        ax = sns.barplot(data=d, x="avg_ctr", y="ad_category")
        ax.set_title("Algorithmic Efficiency: CTR by Industry", fontsize=14)
        ax.set_xlabel("Average CTR")
        ax.set_ylabel("Ad Category")
        _save("E_ctr_by_industry.png")
    else:
        print(f"Skipping CTR chart: {q8} not found")

    # Optional Q5 sample density chart (useful for method appendix)
    if _exists(q5):
        d = pd.read_csv(_csv(q5), usecols=["age_group", "gender", "ad_category"])
        top = (
            d.groupby(["age_group", "gender", "ad_category"])
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
            .head(12)
        )
        top["slice"] = top["age_group"] + " | " + top["gender"] + " | " + top["ad_category"]
        plt.figure(figsize=(12, 6))
        ax = sns.barplot(data=top, x="count", y="slice")
        ax.set_title("Query 5 Bias Sample: Highest-Density Demographic Slices", fontsize=14)
        ax.set_xlabel("Count")
        ax.set_ylabel("Slice")
        _save("Q5_bias_sample_density.png")


def plot_financial_regional_platform() -> None:
    q9, q12, q13 = "q9_Spend_by_Age_Group.csv", "q12_Regional_Bias_Audit.csv", "q13_Cross_Platform_Bias.csv"
    if _exists(q9):
        d = pd.read_csv(_csv(q9))
        plt.figure(figsize=(8, 5))
        ax = sns.barplot(data=d, x="age_group", y="total_spend")
        ax.set_title("Financial Bias: Budget Allocation per Age Group", fontsize=14)
        ax.set_xlabel("Age Group")
        ax.set_ylabel("Total Spend")
        _save("F_spend_allocation.png")
    else:
        print(f"Skipping spend chart: {q9} not found")

    if _exists(q12):
        d = pd.read_csv(_csv(q12))
        pivot = d.pivot(index="region", columns="ad_category", values="avg_spend")
        plt.figure(figsize=(12, 8))
        ax = sns.heatmap(
            pivot,
            cmap=sns.color_palette([PALETTE[1], PALETTE[2], PALETTE[3]], as_cmap=True),
            annot=True,
            fmt=".2f",
            linewidths=0.35,
            linecolor="white",
        )
        ax.set_title("Regional Ad Delivery Heatmap (Avg Spend)", fontsize=14)
        ax.set_xlabel("Ad Category")
        ax.set_ylabel("Region")
        _save("G_regional_bias_heatmap.png")
    else:
        print(f"Skipping regional heatmap: {q12} not found")

    if _exists(q13):
        d = pd.read_csv(_csv(q13))
        plt.figure(figsize=(10, 5))
        ax = sns.stripplot(
            data=d,
            x="platform",
            y="avg_ctr",
            hue="ad_category",
            dodge=True,
            size=5,
            alpha=0.85,
        )
        ax.set_title("Platform Variance Audit", fontsize=14)
        ax.set_xlabel("Platform")
        ax.set_ylabel("Average CTR")
        ax.legend(title="Category", bbox_to_anchor=(1.02, 1), loc="upper left")
        _save("H_platform_bias.png")
    else:
        print(f"Skipping platform chart: {q13} not found")


def plot_temporal_and_outliers() -> None:
    q10, q11 = "q10_Temporal_Analysis.csv", "q11_Highest_Spend_Ads.csv"
    if _exists(q10):
        d = pd.read_csv(_csv(q10))
        d["impression_time"] = pd.to_datetime(d["impression_time"], errors="coerce", utc=True)
        d = d.dropna(subset=["impression_time"])
        trend = (
            d.assign(day=d["impression_time"].dt.date)
            .groupby("day")
            .size()
            .reset_index(name="impressions")
        )
        plt.figure(figsize=(11, 4.5))
        ax = sns.lineplot(data=trend, x="day", y="impressions", color=PALETTE[1], linewidth=2.3)
        ax.set_title("Temporal Delivery Pattern (Query 10)", fontsize=14)
        ax.set_xlabel("Day")
        ax.set_ylabel("Impressions")
        for label in ax.get_xticklabels():
            label.set_rotation(35)
            label.set_ha("right")
        _save("I_temporal_delivery_pattern.png")

    if _exists(q11):
        d = pd.read_csv(_csv(q11)).head(20).sort_values("spend_usd", ascending=False)
        plt.figure(figsize=(10, 6))
        ax = sns.barplot(data=d, x="spend_usd", y="impression_id", color=PALETTE[0])
        ax.set_title("Highest Spend Impressions (Top 20)", fontsize=14)
        ax.set_xlabel("Spend (USD)")
        ax.set_ylabel("Impression ID")
        _save("J_highest_spend_outliers.png")


def main() -> None:
    if not INPUT_DIR.is_dir():
        raise FileNotFoundError(f"Missing input folder: {INPUT_DIR}")

    plot_performance()
    plot_demographics()
    plot_category_audit()
    plot_financial_regional_platform()
    plot_temporal_and_outliers()

    files = sorted([p.name for p in OUTPUT_DIR.glob("*.png")])
    print(f"Generated {len(files)} images in: {OUTPUT_DIR}")
    for f in files:
        print(f" - {f}")


if __name__ == "__main__":
    main()
