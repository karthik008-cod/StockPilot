/**
 * StockPilot NIFTY 50 Market Data Explorer Client Logic
 */

let stocksList = [];
let currentTicker = "RELIANCE.NS";
let currentPeriod = "max";
let allRecords = [];
let filteredRecords = [];
let currentPage = 1;
let pageSize = 50;
let sortCol = "Date";
let sortAsc = false;

// DOM Elements
const stockSelect = document.getElementById("stockSelect");
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

async function init() {
    setupEventListeners();
    await loadStocksList();
    await loadStockData(currentTicker);
}

async function loadStocksList() {
    try {
        const res = await fetch("/api/stocks");
        const data = await res.json();
        stocksList = data.stocks || [];

        const sectors = {};
        stocksList.forEach(s => {
            if (!sectors[s.sector]) sectors[s.sector] = [];
            sectors[s.sector].push(s);
        });

        stockSelect.innerHTML = "";
        Object.keys(sectors).sort().forEach(sec => {
            const optgroup = document.createElement("optgroup");
            optgroup.label = sec;

            sectors[sec].forEach(stock => {
                const opt = document.createElement("option");
                opt.value = stock.symbol;
                opt.textContent = `${stock.name} (${stock.symbol})`;
                if (stock.symbol === currentTicker) opt.selected = true;
                optgroup.appendChild(opt);
            });
            stockSelect.appendChild(optgroup);
        });
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
}

function renderTable() {
    recordsBadge.textContent = `${filteredRecords.length.toLocaleString()} Rows`;

    if (filteredRecords.length === 0) {
        recordsTableBody.innerHTML = `
            <tr>
                <td colspan="10" class="loading-state">
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

    document.querySelectorAll(".toggle-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".toggle-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentPeriod = btn.dataset.period;
            loadStockData(currentTicker);
        });
    });

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

    const headers = ["Date", "Open", "High", "Low", "Close", "Adj_Close", "Volume", "Change", "Change_Pct", "Return_1d_Pct"];
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
            r.Return_1d_Pct
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

document.addEventListener("DOMContentLoaded", init);
