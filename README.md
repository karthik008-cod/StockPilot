# StockPilot 🚀
### AI/ML-Based Stock Market Analysis & Feature Engineering Platform

StockPilot is an intelligent stock market analysis system designed to generate high-conviction trade setups with **entry zones, target prices, stop-loss levels, risk-to-reward ratios, expected holding periods, and supporting technical, fundamental, and sentiment insights**.

This repository contains the **production-grade data loading, cleaning, multi-asset alignment, feature engineering, and leakage-prevention pipeline**, along with a **live NIFTY 50 Market Data Explorer** web interface.

---

## 📌 Architecture & Pipeline Flow

```text
RAW DATA (yfinance: OHLCV, Indices, Quarterly Statements, News)
   ↓
CLEANING & VALIDATION (Chronological sort, OHLCV logic repair, non-destructive outlier tagging)
   ↓
MARKET + SECTOR + INDEX ALIGNMENT (Multi-asset alignment on common trading calendar)
   ↓
FUNDAMENTAL DATA ALIGNMENT (Point-in-time 45-day lag to strictly eliminate lookahead bias)
   ↓
TECHNICAL INDICATORS (Vectorized RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV, RVOL, 52W)
   ↓
RETURNS + VOLATILITY + RELATIVE STRENGTH (Rolling Beta, NIFTY/Sector relative return alpha)
   ↓
NEWS & SENTIMENT FEATURES (Financial domain polarity scoring, 5-day rolling sentiment)
   ↓
TARGET CREATION (5d, 10d, 20d future returns strictly backward-shifted)
   ↓
CHRONOLOGICAL SPLIT & PURGING (Train 70%, Val 15%, Test 15% with 20-day embargo buffer)
   ↓
LEAKAGE-FREE FEATURE SCALING (RobustScaler / StandardScaler fitted strictly on Train)
   ↓
AUTOMATED LEAKAGE AUDIT (Rigorous mathematical verification of zero lookahead)
   ↓
MODEL-READY PERSISTENCE (Parquet, CSV, and metadata JSON exports)
```

---

## ⚡ Key Features

1. **Multi-Source Ingestion & Expanded Universe**:
   - Covers official **NIFTY 50, NIFTY 100, NIFTY 200, and NIFTY 500** constituent equities (500+ stocks).
   - Broad benchmark market indices (**NIFTY 50 - `^NSEI`**, **NIFTY 100 - `^CNX100`**, **NIFTY 200 - `^CNX200`**, **NIFTY 500 - `^CRSLDX`**, **NIFTY Next 50 - `^NSMIDCP`**).
   - Sectoral indices (**`^NSEBANK`**, **`^CNXIT`**, **`^CNXENERGY`**, **`^CNXAUTO`**, **`^CNXPHARMA`**, **`^CNXFMCG`**, **`^CNXMETAL`**, etc.).
   - Full day-1 historical OHLCV data with dividend and stock split adjustments.
   - Resilient multi-threaded ingestion engine with persistent Parquet caching and rate-limit backoff.
   - Quarterly financial statements (Revenue, Net Income, EPS, Debt, Equity, Free Cash Flow).
   - News headlines and financial sentiment polarity scoring.

2. **Hardened Data Cleaning & Quality Control**:
   - **OHLC Consistency Repair**: Auto-repairs bad ticks where $High < \max(Open, Close)$ or $Low > \min(Open, Close)$.
   - **Circuit Freeze Tagging**: Non-destructive tagging of locked upper/lower circuit days ($Open \approx High \approx Low \approx Close$).
   - **Extreme Event Tagging**: 60-day rolling Median Absolute Deviation (MAD) Z-score detection without deleting genuine flash crashes or budget days.
   - **Liquidity Checks**: Zero-volume detection and bounded forward-filling for trading suspension gaps.

3. **Strict Leakage Prevention & Multi-Asset Alignment**:
   - **Point-in-Time Fundamentals**: 45-day reporting lag prevents quarterly results from leaking into past trading days.
   - **Dual-Benchmark Alignment**: Aligns stocks against both NIFTY 50 and broad market NIFTY 500 on common trading calendars.
   - **Chronological Splitting with Embargo**: 20-day embargo buffer prevents overlapping multi-day target returns between Train, Validation, and Test sets.
   - **Train-Only Scaling**: Scalers are fitted exclusively on the Training set and persisted for production inference.
   - **Automated Leakage Audit**: Automated checks verify date monotonicity, target shifts, and scaler isolation.

4. **Interactive Market Explorer Web App**:
   - Browse across **NIFTY 50, NIFTY 100, NIFTY 200, or NIFTY 500** universes with dynamic tier tabs.
   - Filter by specific industry sector (Banking, IT, Auto, Energy, FMCG, Pharma, etc.).
   - Date-wise OHLCV records with circuit and outlier visual flags.
   - Dynamic price/volume trend chart with hover crosshairs.
   - 1-click CSV export with data quality flags.

---

## 🛠️ Installation & Setup

```bash
# Clone the repository
git clone <your-repository-url>
cd StockPilot

# Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Usage

### 1. Ingest Market Data for Any Tier
```bash
# Download and clean full Day 1 historical data for NIFTY 100 + Benchmark Indices
python scripts/import_market_data.py --tier "NIFTY 100" --workers 5

# Scale ingestion to full NIFTY 500 broad universe
python scripts/import_market_data.py --tier "NIFTY 500" --workers 6
```

### 2. Launch the Market Explorer Web App
```bash
# Using uvicorn directly
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000

# Or run the batch file on Windows
start_server.bat
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### 3. Run the Feature Engineering & ML Pipeline via CLI
```bash
# Run pipeline for default configured universe (RELIANCE.NS, TCS.NS, HDFCBANK.NS, INFY.NS)
python scripts/run_pipeline.py

# Run for custom tickers and date range

python scripts/run_pipeline.py --tickers RELIANCE.NS TCS.NS INFY.NS HDFCBANK.NS --start 2019-01-01

# Bypass cache and re-download fresh data
python scripts/run_pipeline.py --tickers RELIANCE.NS --force-reload
```

### 3. Run Automated Tests
```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 📂 Project Structure

```
StockPilot/
├── configs/
│   └── pipeline_config.yaml         # Central pipeline configuration
├── stockpilot/
│   ├── data/
│   │   ├── loader.py                # yfinance loader with caching
│   │   ├── cleaner.py               # Validation and non-destructive outlier tagging
│   │   └── aligner.py               # Multi-asset & point-in-time fundamental alignment
│   ├── features/
│   │   ├── technical.py             # Vectorized technical indicators
│   │   ├── market_relative.py       # Relative strength, beta, correlation
│   │   ├── fundamental.py           # Fundamental financial ratios
│   │   └── sentiment.py             # Financial news sentiment analyzer
│   ├── ml/
│   │   ├── targets.py               # 5d, 10d, 20d backward-shifted targets
│   │   ├── split.py                 # Time-series splitter with embargo buffer
│   │   ├── scaler.py                # Train-only feature scaling
│   │   └── leakage_audit.py         # Automated leakage verification tests
│   ├── nifty50.py                   # Complete NIFTY 50 constituent metadata
│   └── pipeline.py                  # End-to-end master pipeline orchestrator
├── web/
│   ├── app.py                       # FastAPI web backend
│   └── static/
│       ├── index.html               # Glassmorphic UI
│       ├── style.css                # Dark mode design system
│       └── app.js                   # Interactive client logic
├── scripts/
│   └── run_pipeline.py              # CLI entry point
├── tests/                           # Comprehensive test suite (15/15 passing)
├── data/
│   ├── processed/                   # Model-ready Parquet and CSV files
│   └── scalers/                     # Fitted scalers (.pkl) for deployment
└── requirements.txt
```

---

## 📜 License
MIT License
