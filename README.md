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

1. **Multi-Source Ingestion**:
   - Daily OHLCV data with both raw and split/dividend-adjusted prices.
   - Benchmark market index (**NIFTY 50 - `^NSEI`**).
   - Sectoral indices (**`^CNXIT`**, **`^NSEBANK`**, **`^CNXENERGY`**).
   - Quarterly financial statements (Revenue, Net Income, EPS, Debt, Equity, Free Cash Flow).
   - News headlines and sentiment polarity.
   - Local raw caching to avoid API rate limits.

2. **Strict Leakage Prevention**:
   - **Point-in-Time Fundamentals**: 45-day reporting lag prevents quarterly results from leaking into past trading days.
   - **Chronological Splitting with Embargo**: 20-day embargo buffer prevents overlapping multi-day target returns between Train, Validation, and Test sets.
   - **Train-Only Scaling**: Scalers are fitted exclusively on the Training set and persisted for production inference.
   - **Automated Leakage Audit**: Automated checks verify date monotonicity, target shifts, and scaler isolation.

3. **NIFTY 50 Live Explorer Web App**:
   - Fast, interactive UI to view all 50 constituent stocks.
   - Detailed date-wise OHLCV records (1,600+ to 1,900+ rows).
   - Dynamic price/volume trend chart with hover crosshairs.
   - Date filtering, sorting, and 1-click CSV export.

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

### 1. Launch the NIFTY 50 Web Explorer
```bash
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### 2. Run the Data Pipeline via CLI
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
