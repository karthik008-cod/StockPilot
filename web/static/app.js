/**
 * StockPilot NIFTY 50 Market Data Explorer Client Logic
 */

let stocksList = [];
let currentTicker = "RELIANCE.NS";
let currentPeriod = "max";
let currentTier = "NIFTY 100";
let currentSector = "";
let allRecords = [];
let filteredRecords = [];
let currentPage = 1;
let pageSize = 50;
let sortCol = "Date";
let sortAsc = false;

// DOM Elements
const stockSelect = document.getElementById("stockSelect");
const sectorSelect = document.getElementById("sectorSelect");
const stockCountBadge = document.getElementById("stockCountBadge");
const tableSearch = document.getElementById("tableSearch");
const refreshBtn = document.getElementById("refreshBtn");
const exportCsvBtn = document.getElementById("exportCsvBtn");
const recordsTableBody = document.getElementById("recordsTableBody");
const recordsBadge = document.getElementById("recordsBadge");
const pageSizeSelect = document.getElementById("pageSizeSelect");
const prevPageBtn = document.getElementById("prevPageBtn");
const nextPageBtn = document.getElementById("nextPageBtn");
const pageIndicator = document.getElementById("pageIndicator");
const priceChart = document.getElementById("priceChart");
const chartHoverInfo = document.getElementById("chartHoverInfo");

// Summary DOM Elements
const companyNameEl = document.getElementById("companyName");
const tickerBadgeEl = document.getElementById("tickerBadge");
const sectorBadgeEl = document.getElementById("sectorBadge");
const latestPriceEl = document.getElementById("latestPrice");
const changeBadgeEl = document.getElementById("changeBadge");
const latestDateEl = document.getElementById("latestDate");
const dayLowEl = document.getElementById("dayLow");
const dayHighEl = document.getElementById("dayHigh");
const dayOpenEl = document.getElementById("dayOpen");
const dayRangeProgress = document.getElementById("dayRangeProgress");
const high52LowEl = document.getElementById("high52Low");
const high52HighEl = document.getElementById("high52High");
const prevCloseEl = document.getElementById("prevClose");
const yearRangeProgress = document.getElementById("yearRangeProgress");
const latestVolumeEl = document.getElementById("latestVolume");
const totalRecordCountEl = document.getElementById("totalRecordCount");

// Trade Strategy & Capital Horizon State
let currentStrategy = "full"; // "full" (Option A) or "deadline" (Option B)
let currentTradeTerm = "medium"; // "short", "medium", "long"
let currentTradingType = "swing"; // "swing", "positional", "investing", "intraday", "futures", "options"
let currentTradeSetup = null;
let tradeSetupDebounceTimer = null;

// Strategy DOM Elements
const strategyTrendBadge = document.getElementById("strategyTrendBadge");
const optACard = document.getElementById("optACard");
const optBCard = document.getElementById("optBCard");
const radioOptA = document.getElementById("radioOptA");
const radioOptB = document.getElementById("radioOptB");
const deadlineConfigBar = document.getElementById("deadlineConfigBar");
const termConfigBar = document.getElementById("termConfigBar");
const deadlineDateInput = document.getElementById("deadlineDateInput");
const borrowedCapitalInput = document.getElementById("borrowedCapitalInput");
const borrowRateInput = document.getElementById("borrowRateInput");
const planDetailsPanel = document.getElementById("planDetailsPanel");

// Global Config DOM Elements
const tradingTypeSelect = document.getElementById("tradingTypeSelect");
const availableCapitalInput = document.getElementById("availableCapitalInput");
const maxLossInput = document.getElementById("maxLossInput");

async function init() {
    setupEventListeners();
    setupTradeStrategyListeners();
    initDeadlineDefaults();
    await loadSectorsList();
    await loadStocksList();
    await loadStockData(currentTicker);
}

async function loadSectorsList() {
    if (!sectorSelect) return;
    try {
        const res = await fetch("/api/sectors");
        const data = await res.json();
        const sectors = data.sectors || [];
        sectorSelect.innerHTML = `<option value="">All Sectors (${sectors.length})</option>`;
        sectors.forEach(sec => {
            const opt = document.createElement("option");
            opt.value = sec;
            opt.textContent = sec;
            sectorSelect.appendChild(opt);
        });
    } catch (err) {
        console.warn("Could not load sectors list:", err);
    }
}

async function loadStocksList() {
    try {
        const params = new URLSearchParams();
        if (currentTier && currentTier !== "ALL") params.append("tier", currentTier);
        if (currentSector) params.append("sector", currentSector);

        const res = await fetch(`/api/stocks?${params.toString()}`);
        const data = await res.json();
        stocksList = data.stocks || [];

        if (stockCountBadge) stockCountBadge.textContent = stocksList.length;

        const sectors = {};
        stocksList.forEach(s => {
            const secName = s.sector || "Other";
            if (!sectors[secName]) sectors[secName] = [];
            sectors[secName].push(s);
        });

        stockSelect.innerHTML = "";
        let foundCurrent = false;

        Object.keys(sectors).sort().forEach(sec => {
            const optgroup = document.createElement("optgroup");
            optgroup.label = sec;

            sectors[sec].forEach(stock => {
                const opt = document.createElement("option");
                opt.value = stock.symbol;
                opt.textContent = `${stock.name} (${stock.symbol})`;
                if (stock.symbol === currentTicker) {
                    opt.selected = true;
                    foundCurrent = true;
                }
                optgroup.appendChild(opt);
            });
            stockSelect.appendChild(optgroup);
        });

        // If currently selected stock is not in this filtered tier, select the first available stock
        if (!foundCurrent && stocksList.length > 0) {
            currentTicker = stocksList[0].symbol;
            stockSelect.value = currentTicker;
            await loadStockData(currentTicker);
        }
    } catch (err) {
        console.error("Failed to load stocks list:", err);
    }
}


function getStartDateForPeriod(period) {
    const now = new Date();
    if (period === "1mo") {
        now.setMonth(now.getMonth() - 1);
        return now.toISOString().split("T")[0];
    } else if (period === "6mo") {
        now.setMonth(now.getMonth() - 6);
        return now.toISOString().split("T")[0];
    } else if (period === "1y") {
        now.setFullYear(now.getFullYear() - 1);
        return now.toISOString().split("T")[0];
    } else if (period === "3y") {
        now.setFullYear(now.getFullYear() - 3);
        return now.toISOString().split("T")[0];
    }
    // "max" returns null to fetch the entire history from the very first day of trading!
    return null;
}

async function loadStockData(ticker) {
    showLoading();
    const startDate = getStartDateForPeriod(currentPeriod);
    const params = new URLSearchParams({
        ticker: ticker,
        period: currentPeriod,
    });
    if (startDate) {
        params.append("start", startDate);
    }

    try {
        const res = await fetch(`/api/data?${params.toString()}`);
        if (!res.ok) {
            throw new Error(`Server returned status ${res.status}`);
        }
        const data = await res.json();

        allRecords = data.records || [];
        filteredRecords = [...allRecords];
        currentPage = 1;

        updateSummary(data);
        renderTable();
        renderChart(allRecords);
        fetchTradeSetup(ticker);

    } catch (err) {
        console.error("Error loading stock data:", err);
        recordsTableBody.innerHTML = `
            <tr>
                <td colspan="10" class="loading-state" style="color: #FB7185;">
                    Failed to load data for ${ticker}: ${err.message}. Please try again.
                </td>
            </tr>
        `;
    }
}

function showLoading() {
    recordsTableBody.innerHTML = `
        <tr>
            <td colspan="10" class="loading-state">
                <div class="spinner"></div>
                <div>Fetching all historical observations for ${currentTicker}...</div>
            </td>
        </tr>
    `;
}

function updateSummary(data) {
    const s = data.summary;
    companyNameEl.textContent = data.company_name;
    tickerBadgeEl.textContent = data.ticker;
    sectorBadgeEl.textContent = data.sector;

    latestPriceEl.textContent = `₹${formatNumber(s.latest_close)}`;
    latestDateEl.textContent = `${s.latest_date} (First Traded: ${s.first_trading_date || '--'})`;

    const isPositive = s.change >= 0;
    const sign = isPositive ? "+" : "";
    changeBadgeEl.textContent = `${sign}${formatNumber(s.change)} (${sign}${s.change_pct.toFixed(2)}%)`;
    changeBadgeEl.className = `change-badge ${isPositive ? "positive" : "negative"}`;

    dayLowEl.textContent = `₹${formatNumber(s.day_low)}`;
    dayHighEl.textContent = `₹${formatNumber(s.day_high)}`;
    dayOpenEl.textContent = `₹${formatNumber(s.day_open)}`;

    // Day range percentage progress
    const dayRangeSpan = s.day_high - s.day_low;
    const dayProgress = dayRangeSpan > 0 ? ((s.latest_close - s.day_low) / dayRangeSpan) * 100 : 50;
    dayRangeProgress.style.width = `${Math.min(Math.max(dayProgress, 5), 100)}%`;

    high52LowEl.textContent = `₹${formatNumber(s.low_52w)}`;
    high52HighEl.textContent = `₹${formatNumber(s.high_52w)}`;
    prevCloseEl.textContent = `₹${formatNumber(s.prev_close)}`;

    // 52-week range percentage progress
    const yearRangeSpan = s.high_52w - s.low_52w;
    const yearProgress = yearRangeSpan > 0 ? ((s.latest_close - s.low_52w) / yearRangeSpan) * 100 : 50;
    yearRangeProgress.style.width = `${Math.min(Math.max(yearProgress, 5), 100)}%`;

    latestVolumeEl.textContent = formatVolume(s.volume);
    totalRecordCountEl.textContent = s.total_records.toLocaleString();

    const chartRangeLabel = document.getElementById("chartRangeLabel");
    if (chartRangeLabel && allRecords.length > 0) {
        chartRangeLabel.textContent = `From ${allRecords[allRecords.length - 1].Date} to ${allRecords[0].Date} (${allRecords.length.toLocaleString()} observations)`;
    }

    if (data.company_details) {
        renderCompanyDetails(data.company_details);
    }
}

function renderCompanyDetails(details) {
    if (!details) return;

    // 1. Returns Comparison (1W, 1M, YTD, 1Y, 3Y, 5Y)
    const returnsGrid = document.getElementById("returnsGrid");
    if (returnsGrid && details.returns_comparison) {
        const timeframes = [
            { key: "1W", label: "1W" },
            { key: "1M", label: "1M" },
            { key: "YTD", label: "YTD" },
            { key: "1Y", label: "1Y" },
            { key: "3Y", label: "3Y" },
            { key: "5Y", label: "5Y" }
        ];

        const sRet = details.returns_comparison.stock || {};
        const bRet = details.returns_comparison.benchmark || {};

        returnsGrid.innerHTML = timeframes.map(tf => {
            const sVal = sRet[tf.key];
            const bVal = bRet[tf.key];

            const sClass = sVal !== null && sVal !== undefined ? (sVal >= 0 ? "pos" : "neg") : "neutral";
            const bClass = bVal !== null && bVal !== undefined ? (bVal >= 0 ? "pos" : "neg") : "neutral";

            const sText = sVal !== null && sVal !== undefined ? `${sVal >= 0 ? "+" : ""}${sVal.toFixed(2)}%` : "--";
            const bText = bVal !== null && bVal !== undefined ? `${bVal >= 0 ? "+" : ""}${bVal.toFixed(2)}%` : "--";

            return `
                <div class="return-pill-card">
                    <span class="return-tf-label">${tf.label}</span>
                    <div class="return-badges-pair">
                        <span class="return-badge stock-badge ${sClass}">${sText}</span>
                        <span class="return-badge bench-badge ${bClass}">${bText}</span>
                    </div>
                </div>
            `;
        }).join("");
    }

    // 2. Trade Information
    const t = details.trade_info;
    if (t) {
        setElText("tradeVolLakhs", t.traded_volume_lakhs ? `${formatNumber(t.traded_volume_lakhs)}` : "--");
        setElText("tradeValCr", t.traded_value_cr ? `₹${formatNumber(t.traded_value_cr)}` : "--");
        setElText("totalMarketCap", t.total_market_cap_cr ? `₹${formatNumber(t.total_market_cap_cr)}` : "--");
        setElText("freeFloatMarketCap", t.free_float_market_cap_cr ? `₹${formatNumber(t.free_float_market_cap_cr)}` : "--");
        setElText("impactCost", t.impact_cost ? `${t.impact_cost.toFixed(2)}%` : "0.04%");
        setElText("faceValue", t.face_value ? `₹${formatNumber(t.face_value)}` : "₹10.00");
        setElText("marginRate", t.applicable_margin_rate ? `${t.applicable_margin_rate.toFixed(2)}%` : "18.50%");
        setElText("deliverableQty", t.deliverable_pct ? `${t.deliverable_pct.toFixed(2)}%` : "55.23%");
    }

    // 3. Price Information
    const p = details.price_info;
    if (p) {
        setElText("priceHigh52", p.high_52w ? `₹${formatNumber(p.high_52w)}` : "--");
        setElText("high52Date", p.high_52w_date || "--");
        setElText("priceLow52", p.low_52w ? `₹${formatNumber(p.low_52w)}` : "--");
        setElText("low52Date", p.low_52w_date || "--");
        setElText("upperBand", p.upper_band ? `₹${formatNumber(p.upper_band)}` : "--");
        setElText("lowerBand", p.lower_band ? `₹${formatNumber(p.lower_band)}` : "--");
        setElText("priceBand", p.price_band || "No Band (F&O)");
        setElText("tickSize", p.tick_size ? p.tick_size.toFixed(2) : "0.05");
        setElText("dailyVolatility", p.daily_volatility ? `${p.daily_volatility.toFixed(2)}%` : "--");
        setElText("annualVolatility", p.annualised_volatility ? `${p.annualised_volatility.toFixed(2)}%` : "--");
    }

    // 4. Securities Information
    const s = details.securities_info;
    if (s) {
        setElText("secStatus", s.status || "Listed");
        setElText("secTradingStatus", s.trading_status || "Active");
        setElText("symbolPe", s.symbol_pe ? s.symbol_pe.toFixed(2) : "--");
        setElText("adjustedPe", s.adjusted_pe ? s.adjusted_pe.toFixed(2) : "--");
        setElText("listingDate", s.date_of_listing || "--");
        setElText("indexName", s.index || "NIFTY 50");
        setElText("basicIndustry", s.basic_industry || "--");
    }
}

function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function renderTable() {
    recordsBadge.textContent = `${filteredRecords.length.toLocaleString()} Rows`;

    if (filteredRecords.length === 0) {
        recordsTableBody.innerHTML = `
            <tr>
                <td colspan="11" class="loading-state">
                    No matching records found.
                </td>
            </tr>
        `;
        pageIndicator.textContent = "Page 0 of 0";
        prevPageBtn.disabled = true;
        nextPageBtn.disabled = true;
        return;
    }

    const totalPages = pageSize === Infinity ? 1 : Math.ceil(filteredRecords.length / pageSize);
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const startIdx = pageSize === Infinity ? 0 : (currentPage - 1) * pageSize;
    const endIdx = pageSize === Infinity ? filteredRecords.length : Math.min(startIdx + pageSize, filteredRecords.length);
    const pageRows = filteredRecords.slice(startIdx, endIdx);

    const html = pageRows.map(r => {
        const changeClass = r.Change >= 0 ? "val-positive" : "val-negative";
        const signChange = r.Change >= 0 ? "+" : "";
        const signReturn = r.Return_1d_Pct >= 0 ? "+" : "";

        let flagHtml = `<span style="color:#64748B; font-size:11px;">Normal</span>`;
        if (r.is_circuit) {
            flagHtml = `<span class="badge-circuit" style="background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600;">🔒 Circuit</span>`;
        } else if (r.is_outlier) {
            flagHtml = `<span class="badge-outlier" style="background: rgba(245, 158, 11, 0.15); color: #F59E0B; border: 1px solid rgba(245, 158, 11, 0.3); padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600;">⚡ Outlier</span>`;
        }

        return `
            <tr>
                <td class="date-col">${r.Date}</td>
                <td>₹${formatNumber(r.Open)}</td>
                <td>₹${formatNumber(r.High)}</td>
                <td>₹${formatNumber(r.Low)}</td>
                <td><strong>₹${formatNumber(r.Close)}</strong></td>
                <td>₹${formatNumber(r.Adj_Close)}</td>
                <td>${r.Volume.toLocaleString()}</td>
                <td class="${changeClass}">${signChange}₹${formatNumber(r.Change)}</td>
                <td class="${changeClass}">${signChange}${r.Change_Pct.toFixed(2)}%</td>
                <td class="${changeClass}">${signReturn}${r.Return_1d_Pct.toFixed(2)}%</td>
                <td>${flagHtml}</td>
            </tr>
        `;
    }).join("");

    recordsTableBody.innerHTML = html;

    pageIndicator.textContent = `Page ${currentPage} of ${totalPages}`;
    prevPageBtn.disabled = currentPage <= 1;
    nextPageBtn.disabled = currentPage >= totalPages;
}

function renderChart(records) {
    if (!records || records.length === 0) return;

    const chartData = [...records].reverse();
    const canvas = priceChart;
    const ctx = canvas.getContext("2d");

    const rect = canvas.parentElement.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const dpr = window.devicePixelRatio || 1;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    const padding = { top: 20, right: 60, bottom: 40, left: 20 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;

    const prices = chartData.map(d => d.Close);
    const volumes = chartData.map(d => d.Volume);

    const minPrice = Math.min(...prices) * 0.98;
    const maxPrice = Math.max(...prices) * 1.02;
    const maxVolume = Math.max(...volumes) * 3;

    const priceY = p => padding.top + chartHeight - ((p - minPrice) / (maxPrice - minPrice)) * chartHeight;
    const timeX = i => padding.left + (i / (chartData.length - 1)) * chartWidth;

    ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    ctx.lineWidth = 1;
    const numPriceSteps = 5;
    for (let i = 0; i <= numPriceSteps; i++) {
        const priceVal = minPrice + (i / numPriceSteps) * (maxPrice - minPrice);
        const y = priceY(priceVal);

        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();

        ctx.fillStyle = "#64748B";
        ctx.font = "10px Inter";
        ctx.textAlign = "left";
        ctx.fillText(`₹${Math.round(priceVal).toLocaleString()}`, width - padding.right + 8, y + 3);
    }

    const barWidth = Math.max(1, (chartWidth / chartData.length) * 0.7);
    chartData.forEach((d, i) => {
        const x = timeX(i);
        const barHeight = (d.Volume / maxVolume) * (chartHeight * 0.4);
        const y = padding.top + chartHeight - barHeight;

        ctx.fillStyle = d.Close >= d.Open ? "rgba(16, 185, 129, 0.3)" : "rgba(244, 63, 94, 0.3)";
        ctx.fillRect(x - barWidth / 2, y, barWidth, barHeight);
    });

    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + chartHeight);
    gradient.addColorStop(0, "rgba(6, 182, 212, 0.35)");
    gradient.addColorStop(1, "rgba(99, 102, 241, 0.0)");

    ctx.beginPath();
    ctx.moveTo(timeX(0), priceY(chartData[0].Close));
    chartData.forEach((d, i) => ctx.lineTo(timeX(i), priceY(d.Close)));
    ctx.lineTo(timeX(chartData.length - 1), padding.top + chartHeight);
    ctx.lineTo(timeX(0), padding.top + chartHeight);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(timeX(0), priceY(chartData[0].Close));
    chartData.forEach((d, i) => ctx.lineTo(timeX(i), priceY(d.Close)));
    ctx.strokeStyle = "#06B6D4";
    ctx.lineWidth = 2;
    ctx.stroke();

    canvas.onmousemove = e => {
        const mouseX = e.offsetX;
        if (mouseX < padding.left || mouseX > width - padding.right) return;

        const fraction = (mouseX - padding.left) / chartWidth;
        const index = Math.min(chartData.length - 1, Math.max(0, Math.round(fraction * (chartData.length - 1))));
        const item = chartData[index];

        const changeSign = item.Change >= 0 ? "+" : "";
        chartHoverInfo.innerHTML = `
            <strong>${item.Date}</strong> | 
            Open: ₹${formatNumber(item.Open)} | 
            High: ₹${formatNumber(item.High)} | 
            Low: ₹${formatNumber(item.Low)} | 
            Close: <strong>₹${formatNumber(item.Close)}</strong> | 
            Change: <span style="color: ${item.Change >= 0 ? '#34D399' : '#FB7185'}">${changeSign}₹${formatNumber(item.Change)} (${changeSign}${item.Change_Pct.toFixed(2)}%)</span> | 
            Vol: ${item.Volume.toLocaleString()}
        `;
    };

    canvas.onmouseleave = () => {
        chartHoverInfo.textContent = "Hover over chart to view OHLCV details";
    };
}

function setupEventListeners() {
    stockSelect.addEventListener("change", e => {
        currentTicker = e.target.value;
        loadStockData(currentTicker);
    });

    document.querySelectorAll("[data-period]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("[data-period]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentPeriod = btn.dataset.period;
            loadStockData(currentTicker);
        });
    });

    document.querySelectorAll(".tier-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            document.querySelectorAll(".tier-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTier = btn.dataset.tier;
            await loadStocksList();
        });
    });

    if (sectorSelect) {
        sectorSelect.addEventListener("change", async e => {
            currentSector = e.target.value;
            await loadStocksList();
        });
    }


    tableSearch.addEventListener("input", e => {
        const query = e.target.value.trim().toLowerCase();
        if (!query) {
            filteredRecords = [...allRecords];
        } else {
            filteredRecords = allRecords.filter(r => r.Date.toLowerCase().includes(query));
        }
        currentPage = 1;
        renderTable();
    });

    refreshBtn.addEventListener("click", () => loadStockData(currentTicker));
    exportCsvBtn.addEventListener("click", exportToCsv);

    pageSizeSelect.addEventListener("change", e => {
        pageSize = e.target.value === "all" ? Infinity : parseInt(e.target.value, 10);
        currentPage = 1;
        renderTable();
    });

    prevPageBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            renderTable();
        }
    });

    nextPageBtn.addEventListener("click", () => {
        const totalPages = pageSize === Infinity ? 1 : Math.ceil(filteredRecords.length / pageSize);
        if (currentPage < totalPages) {
            currentPage++;
            renderTable();
        }
    });

    document.querySelectorAll(".data-table th").forEach(th => {
        th.addEventListener("click", () => {
            const col = th.dataset.sort;
            if (!col) return;

            if (sortCol === col) {
                sortAsc = !sortAsc;
            } else {
                sortCol = col;
                sortAsc = false;
            }

            filteredRecords.sort((a, b) => {
                let vA = a[sortCol];
                let vB = b[sortCol];
                if (typeof vA === "string") {
                    return sortAsc ? vA.localeCompare(vB) : vB.localeCompare(vA);
                }
                return sortAsc ? vA - vB : vB - vA;
            });

            currentPage = 1;
            renderTable();
        });
    });

    window.addEventListener("resize", () => renderChart(allRecords));
}

function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return "0.00";
    return num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatVolume(vol) {
    if (!vol) return "0";
    if (vol >= 10000000) return `${(vol / 10000000).toFixed(2)} Cr`;
    if (vol >= 100000) return `${(vol / 100000).toFixed(2)} L`;
    if (vol >= 1000) return `${(vol / 1000).toFixed(1)} K`;
    return vol.toLocaleString();
}

function exportToCsv() {
    if (!filteredRecords || filteredRecords.length === 0) return;

    const headers = ["Date", "Open", "High", "Low", "Close", "Adj_Close", "Volume", "Change", "Change_Pct", "Return_1d_Pct", "Is_Circuit", "Is_Outlier"];
    const rows = [headers.join(",")];

    filteredRecords.forEach(r => {
        rows.push([
            r.Date,
            r.Open,
            r.High,
            r.Low,
            r.Close,
            r.Adj_Close,
            r.Volume,
            r.Change,
            r.Change_Pct,
            r.Return_1d_Pct,
            r.is_circuit ? "1" : "0",
            r.is_outlier ? "1" : "0"
        ].join(","));
    });


    const csvContent = "data:text/csv;charset=utf-8," + rows.join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${currentTicker}_historical_records.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ==========================================
// Trade Strategy & Capital Horizon Logic
// ==========================================

function initDeadlineDefaults() {
    if (deadlineDateInput && !deadlineDateInput.value) {
        setDeadlineFromDays(30);
    }
}

function setDeadlineFromDays(days) {
    const d = new Date();
    d.setDate(d.getDate() + days);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const dateStr = `${yyyy}-${mm}-${dd}`;
    if (deadlineDateInput) {
        deadlineDateInput.value = dateStr;
    }
}

async function fetchTradeSetup(ticker) {
    if (!planDetailsPanel) return;

    try {
        const deadline = deadlineDateInput ? deadlineDateInput.value : "";
        const capital = borrowedCapitalInput ? parseFloat(borrowedCapitalInput.value) || 100000 : 100000;
        const rate = borrowRateInput ? parseFloat(borrowRateInput.value) || 10.0 : 10.0;
        const avlCapital = availableCapitalInput ? parseFloat(availableCapitalInput.value) || 100000 : 100000;
        const maxLoss = maxLossInput ? parseFloat(maxLossInput.value) || 2000 : 2000;
        const tradingType = tradingTypeSelect ? tradingTypeSelect.value : "swing";

        const params = new URLSearchParams({
            ticker: ticker || currentTicker,
            trade_term: currentTradeTerm,
            trading_type: tradingType,
            available_capital: avlCapital,
            max_loss: maxLoss,
            capital: capital,
            interest_rate: rate,
        });
        if (deadline) {
            params.append("deadline_date", deadline);
        }

        const res = await fetch(`/api/trade-setup?${params.toString()}`);
        if (!res.ok) {
            throw new Error(`Trade setup returned status ${res.status}`);
        }
        currentTradeSetup = await res.json();

        // Update Trend Badge
        if (strategyTrendBadge && currentTradeSetup.option_a_full_trade) {
            const trend = currentTradeSetup.option_a_full_trade.trend || "Neutral";
            strategyTrendBadge.textContent = `${trend} Setup`;
            if (trend.includes("Bullish")) {
                strategyTrendBadge.style.color = "#34D399";
                strategyTrendBadge.style.borderColor = "rgba(52, 211, 153, 0.4)";
                strategyTrendBadge.style.background = "rgba(52, 211, 153, 0.12)";
            } else if (trend.includes("Bearish")) {
                strategyTrendBadge.style.color = "#FB7185";
                strategyTrendBadge.style.borderColor = "rgba(251, 113, 133, 0.4)";
                strategyTrendBadge.style.background = "rgba(251, 113, 133, 0.12)";
            } else {
                strategyTrendBadge.style.color = "#A5B4FC";
                strategyTrendBadge.style.borderColor = "rgba(99, 102, 241, 0.4)";
                strategyTrendBadge.style.background = "rgba(99, 102, 241, 0.12)";
            }
        }

        renderTradePlan();
    } catch (err) {
        console.error("Failed to load trade setup:", err);
        if (planDetailsPanel) {
            planDetailsPanel.innerHTML = `
                <div style="color: #FB7185; padding: 12px; font-size: 0.9rem;">
                    Could not compute trade setup for ${ticker}: ${err.message}
                </div>
            `;
        }
    }
}

function renderTradePlan() {
    if (!planDetailsPanel || !currentTradeSetup) return;

    const cmp = currentTradeSetup.current_market_price || 0.0;

    if (currentStrategy === "full") {
        const a = currentTradeSetup.option_a_full_trade;
        if (!a) return;

        const ps = a.position_sizing || {};

        planDetailsPanel.innerHTML = `
            <div class="plan-stats-grid">
                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Optimal Entry Zone</span>
                        <span style="color: var(--accent-cyan); font-weight: 700;">CMP ₹${formatNumber(cmp)}</span>
                    </div>
                    <div class="plan-stat-val">₹${formatNumber(a.entry_zone_min)} - ₹${formatNumber(a.entry_zone_max)}</div>
                    <div class="plan-stat-sub">${a.trade_term_label || 'Medium-Term'} ${(a.trading_type || 'swing').charAt(0).toUpperCase() + (a.trading_type || 'swing').slice(1)} trade</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Target 1 (Primary)</span>
                        <span style="color: #34D399; font-weight: 700;">+${a.target_1_pct}%</span>
                    </div>
                    <div class="plan-stat-val" style="color: #34D399;">₹${formatNumber(a.target_1)}</div>
                    <div class="plan-stat-sub positive">${a.trade_term_label} ATR-scaled technical target</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Target 2 (Extended)</span>
                        <span style="color: #6EE7B7; font-weight: 700;">+${a.target_2_pct}%</span>
                    </div>
                    <div class="plan-stat-val" style="color: #6EE7B7;">₹${formatNumber(a.target_2)}</div>
                    <div class="plan-stat-sub positive">Breakout momentum expansion target</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Technical Stop-Loss</span>
                        <span style="color: #FB7185; font-weight: 700;">${a.stop_loss_pct}%</span>
                    </div>
                    <div class="plan-stat-val" style="color: #FB7185;">₹${formatNumber(a.stop_loss)}</div>
                    <div class="plan-stat-sub negative">Swing structure & ATR dynamic support</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Risk to Reward</span>
                        <span style="color: #A5B4FC; font-weight: 700;">Ratio</span>
                    </div>
                    <div class="plan-stat-val">1 : ${a.risk_reward_ratio}</div>
                    <div class="plan-stat-sub ${a.risk_reward_ratio >= 1.5 ? 'positive' : ''}">${a.risk_reward_ratio >= 1.5 ? 'Favorable Risk/Reward' : 'Standard R:R Profile'}</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Est. Completion Window</span>
                        <span style="color: #CBD5E1; font-weight: 700;">${a.trade_term_label || 'Swing'} Horizon</span>
                    </div>
                    <div class="plan-stat-val">~${a.expected_holding_days} Days</div>
                    <div class="plan-stat-sub">14-Day ATR: ₹${formatNumber(a.atr_14)} / session</div>
                </div>
            </div>

            ${renderPositionSizing(ps, a.target_1, a.target_2, a.stop_loss, cmp)}

            <div class="plan-rule-banner rule-banner-a">
                <span class="banner-icon">🎯</span>
                <div>
                    <strong>Option A ${a.trade_term_label} ${(a.trading_type || 'Swing').charAt(0).toUpperCase() + (a.trading_type || 'Swing').slice(1)} Execution Rule:</strong> ${a.exit_rule}
                    <div style="font-size: 0.82rem; color: #94A3B8; margin-top: 4px;">
                        ${a.strategy_summary}
                    </div>
                </div>
            </div>
        `;
    } else {
        const b = currentTradeSetup.option_b_deadline;
        if (!b) return;

        const isProfitable = b.net_projected_pnl >= 0;

        planDetailsPanel.innerHTML = `
            <div class="plan-stats-grid">
                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Repayment Countdown</span>
                        <span style="color: var(--accent-amber); font-weight: 700;">${b.deadline_date}</span>
                    </div>
                    <div class="plan-stat-val" style="color: var(--accent-amber);">${b.calendar_days_remaining} Days</div>
                    <div class="plan-stat-sub">~${b.trading_days_remaining} trading sessions until capital must be returned</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Realizable Target (By Date)</span>
                        <span style="color: #34D399; font-weight: 700;">+${b.target_pct}%</span>
                    </div>
                    <div class="plan-stat-val" style="color: #34D399;">₹${formatNumber(b.time_constrained_target)}</div>
                    <div class="plan-stat-sub positive">Bounded by volatility & time cone (&sigma;&radic;T)</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Tightened Protection SL</span>
                        <span style="color: #FB7185; font-weight: 700;">${b.stop_loss_pct}%</span>
                    </div>
                    <div class="plan-stat-val" style="color: #FB7185;">₹${formatNumber(b.tightened_stop_loss)}</div>
                    <div class="plan-stat-sub negative">Tightened 1.0x ATR for debt capital safety</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Debt Financing Cost</span>
                        <span style="color: #FCA5A5; font-weight: 700;">${b.annual_interest_rate}% p.a.</span>
                    </div>
                    <div class="plan-stat-val" style="color: #F87171;">₹${formatNumber(b.accrued_borrowing_cost)}</div>
                    <div class="plan-stat-sub negative">Accrued cost on ₹${formatNumber(b.borrowed_capital)} borrowed</div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Net P&L (Post-Debt Return)</span>
                        <span class="${isProfitable ? 'positive' : 'negative'}" style="font-weight: 700;">${isProfitable ? '+' : ''}${b.net_roi_pct}% Net ROI</span>
                    </div>
                    <div class="plan-stat-val ${isProfitable ? 'positive' : 'negative'}" style="color: ${isProfitable ? '#34D399' : '#FB7185'};">
                        ${isProfitable ? '+' : ''}₹${formatNumber(b.net_projected_pnl)}
                    </div>
                    <div class="plan-stat-sub ${isProfitable ? 'positive' : 'negative'}">
                        Gross ₹${formatNumber(b.gross_projected_pnl)} - Interest ₹${formatNumber(b.accrued_borrowing_cost)}
                    </div>
                </div>

                <div class="plan-stat-box">
                    <div class="plan-stat-label">
                        <span>Execution Feasibility</span>
                        <span style="color: #FCD34D; font-weight: 700;">Pacing</span>
                    </div>
                    <div class="plan-stat-val" style="font-size: 1.05rem;">${b.urgency_rating}</div>
                    <div class="plan-stat-sub">${b.feasibility_status}</div>
                </div>
            </div>

            ${renderPositionSizing(b.position_sizing || {}, b.time_constrained_target, b.time_constrained_target * 1.02, b.tightened_stop_loss, cmp)}

            <div class="plan-rule-banner rule-banner-b">
                <span class="banner-icon">⚠️</span>
                <div>
                    <strong style="color: #F87171;">MANDATORY BORROWED CAPITAL REPAYMENT RULE:</strong> ${b.mandatory_exit_rule}
                    <div style="font-size: 0.82rem; color: #FECACA; margin-top: 4px;">
                        Regardless of market condition, profit, or loss, you must close the position by <strong>${b.deadline_date}</strong> to return borrowed capital of ₹${formatNumber(b.borrowed_capital)}.
                    </div>
                    <div style="font-size: 0.78rem; color: #CBD5E1; margin-top: 3px;">
                        ${b.strategy_summary}
                    </div>
                </div>
            </div>
        `;
    }
}

function renderPositionSizing(ps, t1, t2, sl, entry) {
    if (!ps || ps.position_size_shares === undefined) return '';

    const riskPerShare = ps.risk_per_share || 0;
    const shares = ps.position_size_shares || 0;
    const capReq = ps.capital_required || 0;
    const maxLossActual = ps.max_loss_actual || 0;
    const profitT1 = ps.potential_profit_t1 || 0;
    const profitT2 = ps.potential_profit_t2 || 0;
    const capUtil = ps.capital_utilization_pct || 0;
    const note = ps.sizing_note || '';

    return `
        <div class="position-sizing-grid">
            <div class="pos-size-header">
                <span>📐</span> Position Sizing & Risk Management
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Position Size</span>
                <span class="pos-stat-mini-val highlight-shares">${shares.toLocaleString()} shares</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Capital Required</span>
                <span class="pos-stat-mini-val">₹${formatNumber(capReq)}</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Capital Utilization</span>
                <span class="pos-stat-mini-val">${capUtil.toFixed(1)}%</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Risk / Share</span>
                <span class="pos-stat-mini-val highlight-loss">₹${formatNumber(riskPerShare)}</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Max Loss (Actual)</span>
                <span class="pos-stat-mini-val highlight-loss">₹${formatNumber(maxLossActual)}</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Profit if T1 Hit</span>
                <span class="pos-stat-mini-val highlight-profit">+₹${formatNumber(profitT1)}</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Profit if T2 Hit</span>
                <span class="pos-stat-mini-val highlight-profit">+₹${formatNumber(profitT2)}</span>
            </div>

            <div class="pos-stat-mini">
                <span class="pos-stat-mini-label">Shares Affordable</span>
                <span class="pos-stat-mini-val">${(ps.shares_affordable || 0).toLocaleString()}</span>
            </div>

            ${note ? `<div class="sizing-note-bar">💡 ${note}</div>` : ''}
        </div>
    `;
}

function selectStrategy(strategy) {
    currentStrategy = strategy;
    if (strategy === "full") {
        if (optACard) optACard.classList.add("active");
        if (optBCard) optBCard.classList.remove("active");
        if (radioOptA) radioOptA.checked = true;
        if (radioOptB) radioOptB.checked = false;
        if (deadlineConfigBar) deadlineConfigBar.style.display = "none";
        if (termConfigBar) termConfigBar.style.display = "flex";
    } else {
        if (optBCard) optBCard.classList.add("active");
        if (optACard) optACard.classList.remove("active");
        if (radioOptB) radioOptB.checked = true;
        if (radioOptA) radioOptA.checked = false;
        if (deadlineConfigBar) deadlineConfigBar.style.display = "flex";
        if (termConfigBar) termConfigBar.style.display = "none";
    }
    renderTradePlan();
}

function setupTradeStrategyListeners() {
    if (optACard) {
        optACard.addEventListener("click", () => {
            selectStrategy("full");
        });
    }
    if (radioOptA) {
        radioOptA.addEventListener("change", () => {
            selectStrategy("full");
        });
    }

    if (optBCard) {
        optBCard.addEventListener("click", () => {
            selectStrategy("deadline");
        });
    }
    if (radioOptB) {
        radioOptB.addEventListener("change", () => {
            selectStrategy("deadline");
        });
    }

    // Quick Horizon Pills
    document.querySelectorAll(".horizon-pill-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            document.querySelectorAll(".horizon-pill-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const days = parseInt(btn.dataset.days, 10);
            if (!isNaN(days)) {
                setDeadlineFromDays(days);
                fetchTradeSetup(currentTicker);
            }
        });
    });

    if (deadlineDateInput) {
        deadlineDateInput.addEventListener("change", () => {
            document.querySelectorAll(".horizon-pill-btn").forEach(b => b.classList.remove("active"));
            fetchTradeSetup(currentTicker);
        });
    }

    if (borrowedCapitalInput) {
        borrowedCapitalInput.addEventListener("input", () => {
            clearTimeout(tradeSetupDebounceTimer);
            tradeSetupDebounceTimer = setTimeout(() => {
                fetchTradeSetup(currentTicker);
            }, 400);
        });
    }

    if (borrowRateInput) {
        borrowRateInput.addEventListener("input", () => {
            clearTimeout(tradeSetupDebounceTimer);
            tradeSetupDebounceTimer = setTimeout(() => {
                fetchTradeSetup(currentTicker);
            }, 400);
        });
    }

    // ─── Trade Term Pills ────────────────────────────────────────────
    document.querySelectorAll(".term-pill-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".term-pill-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTradeTerm = btn.dataset.term;
            fetchTradeSetup(currentTicker);
        });
    });

    // ─── Global Config: Trading Type ────────────────────────────────
    if (tradingTypeSelect) {
        tradingTypeSelect.addEventListener("change", () => {
            currentTradingType = tradingTypeSelect.value;
            fetchTradeSetup(currentTicker);
        });
    }

    // ─── Global Config: Available Capital ────────────────────────────
    if (availableCapitalInput) {
        availableCapitalInput.addEventListener("input", () => {
            clearTimeout(tradeSetupDebounceTimer);
            tradeSetupDebounceTimer = setTimeout(() => {
                fetchTradeSetup(currentTicker);
            }, 400);
        });
    }

    // ─── Global Config: Max Acceptable Loss ──────────────────────────
    if (maxLossInput) {
        maxLossInput.addEventListener("input", () => {
            clearTimeout(tradeSetupDebounceTimer);
            tradeSetupDebounceTimer = setTimeout(() => {
                fetchTradeSetup(currentTicker);
            }, 400);
        });
    }
}

document.addEventListener("DOMContentLoaded", init);
