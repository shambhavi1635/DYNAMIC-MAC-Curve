# DynamicMAC

An interactive Marginal Abatement Cost (MAC) curve dashboard for decarbonization technologies in Indian integrated steel plants — built with Streamlit.

**Live app:** https://dynamic-mac-curve-idffk4dts4v2ysngewum88.streamlit.app/

## What this does

Steel decarbonization technologies (e.g. PCI optimization, CCU/CCS, hydrogen-based routes) each carry a different cost per tonne of CO2 abated, and that cost isn't static — it shifts every year as capital costs, energy prices, and carbon costs change. This app lets a user pick a **year** and a **discount rate**, and renders a MAC curve showing which technologies are cheapest to deploy first at that point in time, for a selected company's plant(s).

Rather than using a single static techno-economic snapshot, the model:
- Annualizes each technology's CapEx using the Capital Recovery Factor (CRF) over its expected lifetime, at the user-selected discount rate.
- Escalates OpEx-relevant costs (fuel, power, feedstock) forward from a fixed 2025 base year using historical and forecast market price indices, so the curve actually moves as you change the year.
- Distinguishes a coal cess from a genuine traded carbon price so CCU/CCS technologies aren't credited with carbon revenue they wouldn't actually receive.
- Avoids double-counting energy savings already captured elsewhere (e.g. for PCI).
- Floors extrapolated market prices (e.g. grid tariff) at zero to avoid nonsensical negative costs from long-range extrapolation.

## Features

- **Year slider** — view the MAC curve for any year in the modeled range, with prices escalated to that year.
- **Discount rate slider** — see how sensitive technology rankings are to the assumed cost of capital.
- **Company/plant selector** — filter to a specific integrated steel plant, excluding technologies it has already deployed.
- **Production-scaling toggle** — approximate how abatement volumes scale with plant production capacity.
- **CSV export** — download the underlying MAC curve data for the selected scenario.
- **Methodology panel** — an in-app expander explaining the formulas and assumptions behind the numbers, so results aren't a black box.

## Data

The app draws on four inputs (see `/notebooks`):
| File | Contents |
|---|---|
| `DecarbonizationTechnologyDataset.xlsx` | Techno-economic parameters per technology (CapEx, OpEx, lifetime, abatement potential) |
| `CompanyDataset.xlsx` | Plant-level data per company (capacity, technologies already deployed) |
| `MarketPrices2010-2025.xlsx` | Historical market prices (fuel, power, carbon, etc.) |
| `predicted_market_prices.xlsx` | Forecast market prices beyond 2025, generated in `marketprediction.ipynb` |

Exploratory analysis and the price-forecasting model live in the notebooks:
- `EDA_Technology.ipynb` — exploration of the technology dataset
- `EDA_market.ipynb` — exploration of historical price series
- `marketprediction.ipynb` — forecasting model used to produce `predicted_market_prices.xlsx`

## Running locally

```bash
git clone https://github.com/shambhavi1635/DYNAMIC-MAC-Curve
cd MAC
pip install -r requirements.txt
streamlit run app.py
```

The app expects the four data files listed above to be present in the same data directory referenced in `app.py` (`notebooks/` by default).

## Project structure

```
MAC/
├── app.py                          # Streamlit app: MAC curve computation + UI
├── notebooks/
│   ├── EDA_Technology.ipynb
│   ├── EDA_market.ipynb
│   ├── marketprediction.ipynb
│   ├── DecarbonizationTechnologyDataset.xlsx
│   ├── CompanyDataset.xlsx
│   ├── MarketPrices2010-2025.xlsx
│   └── predicted_market_prices.xlsx
├── requirements.txt
└── README.md
```

## Known limitations

- Market price forecasts beyond the historical range are extrapolations and carry increasing uncertainty the further out the selected year is.
- If an exact year isn't available in the price dataset, the app currently falls back to the nearest available year without flagging this in the UI.
- Technology-to-price-driver mapping is currently hardcoded in `app.py` rather than stored as a column in the technology dataset.

## Author

Built by Shambhavi, IIT Bhubaneswar, as part of a project on decarbonization pathways and cost-abatement modeling in the Indian steel sector.