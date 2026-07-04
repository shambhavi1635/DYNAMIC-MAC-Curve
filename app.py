"""
Marginal Abatement Cost (MAC) Curve Explorer — Indian Integrated Steel Plants
==============================================================================

This app combines four datasets:
  1. CompanyDataset.xlsx                -> which plants exist, their scale and
                                            which decarbonization technologies
                                            they already have installed.
  2. DecarbonizationTechnologyDataset.xlsx -> techno-economic data for each
                                            candidate decarbonization technology
                                            (CapEx, OpEx change, energy saved,
                                            CO2 abated, lifetime, etc).
  3. MarketPrices2010-2025.xlsx         -> historical energy/carbon/scrap
                                            prices (actuals).
  4. predicted_market_prices.xlsx       -> a modeled/forecast price series for
                                            2010-2050 (same columns as #3),
                                            used to project how each
                                            technology's economics evolve.

For any technology, the annualized cost of abatement depends on:
  - the annualized CapEx (spread over the technology's lifetime at a discount
    rate),
  - the recurring OpEx change (savings or extra cost), and
  - how that OpEx change is expected to move over time as the underlying
    energy/material price it depends on rises or falls.

We therefore *escalate* each technology's OpEx change year-by-year using the
ratio of the predicted price (in the requested year) to the price in a fixed
base year (2025, the last actual year in the historical dataset). This lets a
single techno-economic snapshot (the technology dataset) be projected forward
using the price forecast, producing a different MAC curve for every year.

    MAC (INR / tCO2, for year Y) =
        [ Annualized CapEx  +  OpEx_change(2025) * PriceIndex(Y) ] * 10
        --------------------------------------------------------------
                          CO2 Reduction (Mt CO2/yr)

  (the factor of 10 converts INR-Crore-per-year over Mt-CO2-per-year into
  INR-per-tonne-CO2: 1 Cr = 1e7 INR, 1 Mt = 1e6 t, 1e7/1e6 = 10)

Technologies are then sorted from cheapest to most expensive and stacked
along the x-axis by their CO2 abatement potential -> the classic MAC "staircase".

ASSUMPTIONS / LIMITATIONS (please read):
  - The technology dataset gives costs "per typical plant installation", not
    per tonne of steel produced. We do not disaggregate this to individual
    companies by default; an optional production-based scaling toggle is
    provided as a rough approximation only.
  - The predicted_market_prices.xlsx file is a straight-line style
    extrapolation and a few series (electricity/grid tariff) cross zero into
    negative territory after ~2040. We floor all prices at a small positive
    value before computing ratios so the model stays numerically stable; the
    app flags this in the sidebar.
  - "PCI" reports its energy saving as a text field (coal reduction in
    kg/tHM) rather than MWh/yr; since its OpEx change already captures the
    coal cost saving, we treat its Energy Saving as non-monetized (0) to
    avoid double counting.
  - CCU/CCS's benefit is only its CapEx/OpEx/CO2 columns; we do not credit it
    with avoided carbon-cess revenue since that price series is a coal cess,
    not a traded carbon price.
"""

import os
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "notebooks")
BASE_YEAR = 2025          # reference year for the technology dataset's cost snapshot
PRICE_FLOOR = 1.0         # floor (in original units) applied before ratio-ing prices

# Which market-price column drives each technology's OpEx escalation.
# Chosen based on the technology's description / the fuel or input it displaces.
TECH_PRICE_DRIVER = {
    "CDQ":             "Steam Price (INR/GJ)",
    "PCI":             "Coking Coal Price (INR/t)",
    "TRT":             "Grid Power Tariff (INR/kWh)",
    "BOFG Recovery":   "Industrial Fuel Price (INR/GJ)",
    "EAF Upgrade":     "Scrap Steel Price (INR/t)",
    "DRI-H2":          "Green Hydrogen Price (INR/kg)",
    "CCU/CCS":         "Carbon Price - Coal Cess / GST Compensation Cess (INR/tonne coal)",
    "CCPP":            "Grid Power Tariff (INR/kWh)",
    "Electrolysis-O2": "Green Hydrogen Price (INR/kg)",
    "Waste Heat ORC":  "Electricity Price - HT Industrial (INR/kWh)",
}

TECH_COLORS = {
    "CDQ": "#1f77b4", "PCI": "#ff7f0e", "TRT": "#2ca02c", "BOFG Recovery": "#d62728",
    "EAF Upgrade": "#9467bd", "DRI-H2": "#8c564b", "CCU/CCS": "#e377c2",
    "CCPP": "#7f7f7f", "Electrolysis-O2": "#bcbd22", "Waste Heat ORC": "#17becf",
}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
@st.cache_data
def load_data():
    company_df = pd.read_excel(
    os.path.join(DATA_DIR, "CompanyDataset.xlsx"))
    company_df = company_df[company_df["Company"] != "Industry Average / Total"].copy()

    tech_df = pd.read_excel(
    os.path.join(DATA_DIR,
                 "DecarbonizationTechnologyDataset.xlsx"),
    sheet_name="Technology Dataset",
    header=2)
    tech_df.columns = [c.replace("\n", " ").strip() for c in tech_df.columns]
    for col in ["Technology Readiness Level (TRL)", "CapEx (INR Cr)",
                "OpEx Change (INR Cr/yr)", "CO₂ Reduction (Mt CO₂/yr)",
                "Payback Period (yrs)", "Lifetime (yrs)"]:
        tech_df[col] = pd.to_numeric(tech_df[col], errors="coerce")
    # Energy Saving column is mostly MWh/yr but one row (PCI) is a text note.
    tech_df["Energy Saving (MWh/yr)"] = pd.to_numeric(
        tech_df["Energy Saving (MWh/yr)"], errors="coerce"
    ).fillna(0)

    price_hist_df = pd.read_excel(os.path.join(DATA_DIR, "MarketPrices2010-2025.xlsx"))
    price_pred_df = pd.read_excel(os.path.join(DATA_DIR, "predicted_market_prices.xlsx"))

    return company_df, tech_df, price_hist_df, price_pred_df


def get_price_row(price_df, year):
    row = price_df.loc[price_df["Year"] == year]
    if row.empty:
        # fall back to nearest available year
        nearest = price_df.iloc[(price_df["Year"] - year).abs().argsort()[:1]]
        return nearest.iloc[0]
    return row.iloc[0]


# --------------------------------------------------------------------------- #
# MAC curve calculation
# --------------------------------------------------------------------------- #
def compute_mac_curve(year, tech_df, price_pred_df, discount_rate,
                       excluded_techs=None, scale_factor=1.0):
    excluded_techs = excluded_techs or set()
    base_prices = get_price_row(price_pred_df, BASE_YEAR)
    year_prices = get_price_row(price_pred_df, year)

    rows = []
    for _, r in tech_df.iterrows():
        tech = r["Technology"]
        if tech in excluded_techs:
            continue

        n = r["Lifetime (yrs)"]
        rr = discount_rate
        crf = (rr * (1 + rr) ** n) / (((1 + rr) ** n) - 1) if rr > 0 else 1 / n
        annualized_capex = r["CapEx (INR Cr)"] * crf

        driver_col = TECH_PRICE_DRIVER.get(tech)
        base_p = max(base_prices[driver_col], PRICE_FLOOR)
        year_p = max(year_prices[driver_col], PRICE_FLOOR)
        price_index = year_p / base_p

        escalated_opex = r["OpEx Change (INR Cr/yr)"] * price_index

        total_annual_cost_cr = annualized_capex + escalated_opex   # INR Cr/yr
        co2_reduction = r["CO₂ Reduction (Mt CO₂/yr)"] * scale_factor  # Mt CO2/yr

        mac = (total_annual_cost_cr / co2_reduction) * 10 if co2_reduction > 0 else np.nan

        rows.append({
            "Technology": tech,
            "Full Name": r["Full Name"],
            "MAC (INR/tCO2)": mac,
            "CO2 Abatement (Mt/yr)": co2_reduction,
            "Annualized CapEx (INR Cr/yr)": annualized_capex,
            "Escalated OpEx (INR Cr/yr)": escalated_opex,
            "Price Index vs 2025": price_index,
        })

    df = pd.DataFrame(rows).dropna(subset=["MAC (INR/tCO2)"])
    df = df.sort_values("MAC (INR/tCO2)").reset_index(drop=True)
    df["Cumulative CO2 (Mt/yr)"] = df["CO2 Abatement (Mt/yr)"].cumsum()
    df["Start CO2 (Mt/yr)"] = df["Cumulative CO2 (Mt/yr)"] - df["CO2 Abatement (Mt/yr)"]
    return df


def plot_mac_curve(df, year):
    fig, ax = plt.subplots(figsize=(10, 6))
    for _, r in df.iterrows():
        color = TECH_COLORS.get(r["Technology"], "#999999")
        ax.bar(
            x=r["Start CO2 (Mt/yr)"],
            height=r["MAC (INR/tCO2)"],
            width=r["CO2 Abatement (Mt/yr)"],
            align="edge",
            color=color,
            edgecolor="black",
            linewidth=0.6,
        )
        ax.text(
            r["Start CO2 (Mt/yr)"] + r["CO2 Abatement (Mt/yr)"] / 2,
            r["MAC (INR/tCO2)"],
            r["Technology"],
            ha="center",
            va="bottom" if r["MAC (INR/tCO2)"] >= 0 else "top",
            fontsize=8,
            rotation=90 if r["CO2 Abatement (Mt/yr)"] < 0.6 else 0,
        )

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Cumulative CO2 Abatement Potential (Mt CO2/yr)")
    ax.set_ylabel("Marginal Abatement Cost (INR / tCO2)")
    ax.set_title(f"MAC Curve — Indian Integrated Steel Sector — {year}")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Steel Decarbonization MAC Curve", layout="wide")
st.title("🏭 Marginal Abatement Cost (MAC) Curve — Indian Steel Sector")
st.caption(
    "Pick a year to see how the cost-effectiveness of each decarbonization "
    "technology is projected to shift as energy, fuel and material prices change."
)

company_df, tech_df, price_hist_df, price_pred_df = load_data()

min_year = int(price_pred_df["Year"].min())
max_year = int(price_pred_df["Year"].max())

with st.sidebar:
    st.header("Controls")
    year = st.slider("Select year", min_value=min_year, max_value=max_year,
                      value=BASE_YEAR, step=1)
    discount_rate = st.slider("Discount rate (WACC)", 0.02, 0.20, 0.10, 0.01,
                               help="Used to annualize each technology's CapEx over its lifetime.")

    st.subheader("Scope")
    company_choice = st.selectbox(
        "Company view",
        ["Industry (all technologies)"] + company_df["Company"].tolist(),
        help="Selecting a company excludes technologies it has already deployed."
    )

    scale_to_company = False
    if company_choice != "Industry (all technologies)":
        scale_to_company = st.checkbox(
            "Scale CO2 abatement potential to company production size",
            value=True,
            help="Rough approximation: scales each technology's typical-plant CO2 "
                 "reduction by (company production / average plant production).",
        )

    st.divider()
    st.caption(
        f"Base year for technology cost snapshot: **{BASE_YEAR}**. "
        "Prices are taken from the predicted_market_prices dataset. "
        "Note: a few forecast price series (e.g. grid power tariff) turn negative "
        "after ~2040 due to linear extrapolation in the source data; these are "
        f"floored at {PRICE_FLOOR} for stability."
    )

excluded_techs = set()
scale_factor = 1.0
if company_choice != "Industry (all technologies)":
    row = company_df.loc[company_df["Company"] == company_choice].iloc[0]
    present = row["Decarbonization Technologies Present"]
    if isinstance(present, str):
        excluded_techs = {t.strip() for t in present.split(",")}
    if scale_to_company:
        avg_production = company_df["Production (MTPA)"].mean()
        scale_factor = row["Production (MTPA)"] / avg_production

mac_df = compute_mac_curve(
    year, tech_df, price_pred_df, discount_rate,
    excluded_techs=excluded_techs, scale_factor=scale_factor,
)

col1, col2 = st.columns([2.2, 1])

with col1:
    if mac_df.empty:
        st.warning("No technologies available for this selection (all may already be deployed).")
    else:
        fig = plot_mac_curve(mac_df, year)
        st.pyplot(fig)

with col2:
    st.subheader(f"Price context — {year}")
    yp = get_price_row(price_pred_df, year)
    bp = get_price_row(price_pred_df, BASE_YEAR)
    for col in TECH_PRICE_DRIVER.values():
        pass
    context_cols = [
        "Coking Coal Price (INR/t)", "Grid Power Tariff (INR/kWh)",
        "Green Hydrogen Price (INR/kg)", "Scrap Steel Price (INR/t)",
        "Electricity Price - HT Industrial (INR/kWh)",
    ]
    ctx = pd.DataFrame({
        "Price": [yp[c] for c in context_cols],
        f"Index vs {BASE_YEAR}": [max(yp[c], PRICE_FLOOR) / max(bp[c], PRICE_FLOOR) for c in context_cols],
    }, index=context_cols)
    st.dataframe(ctx.style.format({"Price": "{:,.1f}", f"Index vs {BASE_YEAR}": "{:.2f}x"}))

st.subheader("Underlying data")
display_df = mac_df.copy()
for c in ["MAC (INR/tCO2)", "CO2 Abatement (Mt/yr)", "Annualized CapEx (INR Cr/yr)",
          "Escalated OpEx (INR Cr/yr)", "Price Index vs 2025"]:
    display_df[c] = display_df[c].round(2)
st.dataframe(display_df, use_container_width=True)

st.download_button(
    "Download this year's MAC data as CSV",
    data=mac_df.to_csv(index=False).encode("utf-8"),
    file_name=f"mac_curve_{year}.csv",
    mime="text/csv",
)

with st.expander("Methodology & assumptions"):
    st.markdown(__doc__)