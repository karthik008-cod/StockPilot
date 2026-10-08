/**
 * StockPilot Market Explorer & Trade Planner Client Logic
 * Follows a progressive disciplined flow:
 * Step 1: Select Index Universe
 * Step 2: Select Sector / Industry
 * Step 3: Select Stock
 * Step 4: Trade Strategy, Horizon & Position Sizing Planner
 */

let stocksList = [];
let currentTicker = null;
let currentPeriod = "max";
let currentTier = null;
let currentSector = null;
let currentSectorDetails = [];
let allRecords = [];
let filteredRecords = [];
let currentPage = 1;
let pageSize = 50;
let sortCol = "Date";
let sortAsc = false;

// Stepper & Workflow DOM Elements
const workflowStatusBadge = document.getElementById("workflowStatusBadge");
const step1Card = document.getElementById("step1Card");
const step2Card = document.getElementById("step2Card");
const step3Card = document.getElementById("step3Card");
const step4Card = document.getElementById("step4Card");
const step1SelectedVal = document.getElementById("step1SelectedVal");
const step2SelectedVal = document.getElementById("step2SelectedVal");
const step3SelectedVal = document.getElementById("step3SelectedVal");
const step4SelectedVal = document.getElementById("step4SelectedVal");
const step1Icon = document.getElementById("step1Icon");
const step2Icon = document.getElementById("step2Icon");
const step3Icon = document.getElementById("step3Icon");
const step4Icon = document.getElementById("step4Icon");
const conn1 = document.getElementById("conn1");
const conn2 = document.getElementById("conn2");
const conn3 = document.getElementById("conn3");

// Flow Sections & Inputs
const flowSectionStep1 = document.getElementById("flowSectionStep1");
const flowSectionStep2 = document.getElementById("flowSectionStep2");
const flowSectionStep3 = document.getElementById("flowSectionStep3");
const step2Hint = document.getElementById("step2Hint");
const step3Hint = document.getElementById("step3Hint");
const sectorPillsContainer = document.getElementById("sectorPillsContainer");
const guidedFlowState = document.getElementById("guidedFlowState");
const stockWorkspace = document.getElementById("stockWorkspace");

const guideStep1Box = document.getElementById("guideStep1Box");
const guideStep2Box = document.getElementById("guideStep2Box");
const guideStep3Box = document.getElementById("guideStep3Box");
const guideStep4Box = document.getElementById("guideStep4Box");
const guideStep1Status = document.getElementById("guideStep1Status");
const guideStep2Status = document.getElementById("guideStep2Status");
const guideStep3Status = document.getElementById("guideStep3Status");
const guideStep4Status = document.getElementById("guideStep4Status");

// Controls
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
    updateFlowUI();
    initTabNavigation();
    loadMarketStats();
}

/**
 * Updates UI state across the 4-step progressive flow
 */
function updateFlowUI() {
    // Step 1: Index Universe
    if (!currentTier) {
        step1Card.className = "step-card active";
        step1Icon.textContent = "●";
        step1SelectedVal.textContent = "Select Index";
        if (guideStep1Status) guideStep1Status.textContent = "👉 Choose above";

        step2Card.className = "step-card locked";
        step2Icon.textContent = "🔒";
        step2SelectedVal.textContent = "Waiting for Index";
        if (guideStep2Status) guideStep2Status.textContent = "🔒 Locked";

        step3Card.className = "step-card locked";
        step3Icon.textContent = "🔒";
        step3SelectedVal.textContent = "Waiting for Sector";
        if (guideStep3Status) guideStep3Status.textContent = "🔒 Locked";

        step4Card.className = "step-card locked";
        step4Icon.textContent = "🔒";
        step4SelectedVal.textContent = "Waiting for Stock";
        if (guideStep4Status) guideStep4Status.textContent = "🔒 Locked";

        conn1.className = "step-connector";
        conn2.className = "step-connector";
        conn3.className = "step-connector";

        flowSectionStep1.className = "flow-step-section is-active";
        flowSectionStep2.className = "flow-step-section is-disabled";
        flowSectionStep3.className = "flow-step-section is-disabled";

        sectorSelect.disabled = true;
        stockSelect.disabled = true;
        tableSearch.disabled = true;
        refreshBtn.disabled = true;
        exportCsvBtn.disabled = true;

        workflowStatusBadge.innerHTML = '<span class="pulse-dot"></span> Step 1 of 4: Select Index Universe';
        guidedFlowState.style.display = "flex";
        stockWorkspace.style.display = "none";
        return;
    }

    // Step 1 is chosen
    step1Card.className = "step-card completed";
    step1Icon.textContent = "✓";
    step1SelectedVal.textContent = currentTier;
    conn1.className = "step-connector completed";
    if (guideStep1Status) guideStep1Status.textContent = `✓ ${currentTier}`;

    // Step 2: Sector
    if (!currentSector) {
        step2Card.className = "step-card active";
        step2Icon.textContent = "●";
        step2SelectedVal.textContent = "Select Sector";
        if (guideStep2Status) guideStep2Status.textContent = "👉 Choose sector";

        step3Card.className = "step-card locked";
        step3Icon.textContent = "🔒";
        step3SelectedVal.textContent = "Waiting for Sector";
        if (guideStep3Status) guideStep3Status.textContent = "🔒 Locked";

        step4Card.className = "step-card locked";
        step4Icon.textContent = "🔒";
        step4SelectedVal.textContent = "Waiting for Stock";
        if (guideStep4Status) guideStep4Status.textContent = "🔒 Locked";

        conn2.className = "step-connector";
        conn3.className = "step-connector";

        flowSectionStep1.className = "flow-step-section is-completed";
        flowSectionStep2.className = "flow-step-section is-active";
        flowSectionStep3.className = "flow-step-section is-disabled";

        sectorSelect.disabled = false;
        stockSelect.disabled = true;
        tableSearch.disabled = true;
        refreshBtn.disabled = true;
        exportCsvBtn.disabled = true;

        workflowStatusBadge.innerHTML = `<span class="pulse-dot"></span> Step 2 of 4: Select Sector in ${currentTier}`;
        guidedFlowState.style.display = "flex";
        stockWorkspace.style.display = "none";
        return;
    }

    // Step 2 is chosen
    const displaySector = currentSector === "ALL" ? "All Sectors" : currentSector;
    step2Card.className = "step-card completed";
    step2Icon.textContent = "✓";
    step2SelectedVal.textContent = displaySector;
    conn2.className = "step-connector completed";
    if (guideStep2Status) guideStep2Status.textContent = `✓ ${displaySector}`;

    // Step 3: Stock
    if (!currentTicker) {
        step3Card.className = "step-card active";
        step3Icon.textContent = "●";
        step3SelectedVal.textContent = "Select Stock";
        if (guideStep3Status) guideStep3Status.textContent = "👉 Choose stock";

        step4Card.className = "step-card locked";
        step4Icon.textContent = "🔒";
        step4SelectedVal.textContent = "Waiting for Stock";
        if (guideStep4Status) guideStep4Status.textContent = "🔒 Locked";

        conn3.className = "step-connector";

        flowSectionStep1.className = "flow-step-section is-completed";
        flowSectionStep2.className = "flow-step-section is-completed";
        flowSectionStep3.className = "flow-step-section is-active";

        sectorSelect.disabled = false;
        stockSelect.disabled = false;
        tableSearch.disabled = false;
        refreshBtn.disabled = true;
        exportCsvBtn.disabled = true;

        workflowStatusBadge.innerHTML = `<span class="pulse-dot"></span> Step 3 of 4: Select Stock to Analyze`;
        guidedFlowState.style.display = "flex";
        stockWorkspace.style.display = "none";
        return;
    }

    // Step 3 is chosen & Stock is Loaded
    step3Card.className = "step-card completed";
    step3Icon.textContent = "✓";
    step3SelectedVal.textContent = currentTicker;
    conn3.className = "step-connector completed";
    if (guideStep3Status) guideStep3Status.textContent = `✓ ${currentTicker}`;

    // Step 4: Active Analysis Workspace
    step4Card.className = "step-card active completed";
    step4Icon.textContent = "✓";
    step4SelectedVal.textContent = "Setup Active";
    if (guideStep4Status) guideStep4Status.textContent = "✓ Active";

    flowSectionStep1.className = "flow-step-section is-completed";
    flowSectionStep2.className = "flow-step-section is-completed";
    flowSectionStep3.className = "flow-step-section is-completed";

    sectorSelect.disabled = false;
    stockSelect.disabled = false;
    tableSearch.disabled = false;
    refreshBtn.disabled = false;
    exportCsvBtn.disabled = false;

    workflowStatusBadge.innerHTML = `<span class="status-indicator live"></span> Active Analysis: ${currentTicker} (${currentTier} › ${displaySector})`;
    guidedFlowState.style.display = "none";
    stockWorkspace.style.display = "flex";
}

/**
 * Step 1 Action: Select Index Universe
 */
async function onSelectTier(tier) {
    if (currentTier === tier && currentSector) return;
    currentTier = tier;
    currentSector = null;
    currentTicker = null;

    document.querySelectorAll(".tier-choice-btn").forEach(btn => {
        if (btn.dataset.tier === tier) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    updateFlowUI();
    await loadSectorsForTier(tier);
}

/**
 * Loads sectors dynamically for the chosen Index Universe
 */
async function loadSectorsForTier(tier) {
    if (!sectorSelect) return;
    try {
        sectorSelect.innerHTML = `<option value="" disabled selected>⏳ Loading sectors in ${tier}...</option>`;
        const res = await fetch(`/api/sectors?tier=${encodeURIComponent(tier)}`);
        const data = await res.json();
        currentSectorDetails = data.sector_details || [];
        const sectors = data.sectors || [];

        sectorSelect.innerHTML = `
            <option value="" disabled selected>-- Select Sector (${sectors.length} sectors in ${tier}) --</option>
            <option value="ALL">All Sectors in ${tier} (All ${data.tier === 'NIFTY 50' ? 50 : data.tier === 'NIFTY 100' ? 100 : data.tier === 'NIFTY 200' ? 200 : '500+'} stocks)</option>
        `;

        currentSectorDetails.forEach(sec => {
            const opt = document.createElement("option");
            opt.value = sec.name;
            opt.textContent = `${sec.name} (${sec.count} stocks)`;
            sectorSelect.appendChild(opt);
        });

        // Quick sector chip pills for fast 1-click selection
        if (sectorPillsContainer) {
            sectorPillsContainer.innerHTML = "";
            sectorPillsContainer.style.display = "flex";

            const allPill = document.createElement("button");
            allPill.className = "sector-pill-chip";
            allPill.innerHTML = `<span>All Sectors</span> <span class="sector-chip-count">${tier}</span>`;
            allPill.addEventListener("click", () => {
                sectorSelect.value = "ALL";
                onSelectSector("ALL");
            });
            sectorPillsContainer.appendChild(allPill);

            // Show top sectors
            currentSectorDetails.slice(0, 10).forEach(sec => {
                const pill = document.createElement("button");
                pill.className = "sector-pill-chip";
                pill.innerHTML = `<span>${sec.name}</span> <span class="sector-chip-count">${sec.count}</span>`;
                pill.addEventListener("click", () => {
                    sectorSelect.value = sec.name;
                    onSelectSector(sec.name);
                });
                sectorPillsContainer.appendChild(pill);
            });
        }

        if (step2Hint) {
            step2Hint.textContent = `Choose a sector from ${tier} (${sectors.length} sectors available) or choose "All Sectors".`;
        }
    } catch (err) {
        console.error("Failed to load sectors for tier:", err);
        sectorSelect.innerHTML = `<option value="" disabled selected>Error loading sectors</option>`;
    }
}

/**
 * Step 2 Action: Select Sector
 */
async function onSelectSector(sector) {
    if (!sector) return;
    currentSector = sector;
    currentTicker = null;

    if (sectorPillsContainer) {
        sectorPillsContainer.querySelectorAll(".sector-pill-chip").forEach(p => {
            const pText = p.textContent;
            if ((sector === "ALL" && pText.includes("All Sectors")) || pText.includes(sector)) {
                p.classList.add("active");
            } else {
                p.classList.remove("active");
            }
        });
    }

    updateFlowUI();
    await loadStocksForSector(currentTier, sector);
}

/**
 * Loads stocks dynamically for the chosen Index Universe + Sector
 */
async function loadStocksForSector(tier, sector) {
    if (!stockSelect) return;
    try {
        stockSelect.innerHTML = `<option value="" disabled selected>⏳ Loading stocks...</option>`;
        const params = new URLSearchParams();
        if (tier && tier !== "ALL") params.append("tier", tier);
        if (sector && sector !== "ALL") params.append("sector", sector);

        const res = await fetch(`/api/stocks?${params.toString()}`);
        const data = await res.json();
        stocksList = data.stocks || [];

        if (stockCountBadge) stockCountBadge.textContent = stocksList.length;

        stockSelect.innerHTML = `<option value="" disabled selected>-- Select Stock to Analyze (${stocksList.length} available) --</option>`;

        if (sector === "ALL") {
            const sectors = {};
            stocksList.forEach(s => {
                const secName = s.sector || "Other";
                if (!sectors[secName]) sectors[secName] = [];
                sectors[secName].push(s);
            });

            Object.keys(sectors).sort().forEach(sec => {
                const optgroup = document.createElement("optgroup");
                optgroup.label = `${sec} (${sectors[sec].length})`;
                sectors[sec].forEach(stock => {
                    const opt = document.createElement("option");
                    opt.value = stock.symbol;
                    opt.textContent = `${stock.name} (${stock.symbol})`;
                    optgroup.appendChild(opt);
                });
                stockSelect.appendChild(optgroup);
            });
        } else {
            stocksList.forEach(stock => {
                const opt = document.createElement("option");
                opt.value = stock.symbol;
                opt.textContent = `${stock.name} (${stock.symbol})`;
                stockSelect.appendChild(opt);
            });
        }

        const plannerStockSelect = document.getElementById("plannerStockSelect");
        if (plannerStockSelect) {
            plannerStockSelect.innerHTML = `<option value="" disabled selected>-- Select stock to plan trade (${stocksList.length}) --</option>` + stockSelect.innerHTML;
        }

        if (step3Hint) {
            const displaySec = sector === "ALL" ? "All Sectors" : sector;
            step3Hint.textContent = `Choose a stock from ${tier} › ${displaySec} (${stocksList.length} stocks available).`;
        }
    } catch (err) {
        console.error("Failed to load stocks:", err);
        stockSelect.innerHTML = `<option value="" disabled selected>Error loading stocks</option>`;
    }
}

/**
 * Step 3 Action: Select Stock to Analyze
 */
async function onSelectStock(ticker) {
    if (!ticker) return;
    currentTicker = ticker;
    updateFlowUI();
    await loadStockData(ticker);
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

async function loadStockData(ticker, forceRefresh = false) {
    showLoading();
    const startDate = getStartDateForPeriod(currentPeriod);
    const params = new URLSearchParams({
        ticker: ticker,
        period: currentPeriod,
    });
    if (startDate) {
        params.append("start", startDate);
    }
    if (forceRefresh) {
        params.append("refresh", "true");
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
        fetchStockStrategyCheck(ticker);

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

    // Update Planner & Universe tab banners
    const quickStockName = document.getElementById("quickStockName");
    if (quickStockName) quickStockName.textContent = data.company_name || data.ticker;
    const plannerTicker = document.getElementById("plannerTickerBadge");
    if (plannerTicker) plannerTicker.textContent = (data.ticker || "").replace(".NS", "");
    const plannerPrice = document.getElementById("plannerPriceBadge");
    if (plannerPrice) plannerPrice.textContent = `₹${formatNumber(s.latest_close)}`;
    const syncCurrentLbl = document.getElementById("syncCurrentTickerLbl");
    if (syncCurrentLbl) syncCurrentLbl.textContent = (data.ticker || "").replace(".NS", "");
    const plannerStockSelect = document.getElementById("plannerStockSelect");
    if (plannerStockSelect && data.ticker) plannerStockSelect.value = data.ticker;

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
    // Flow Step 1: Index Selection
    document.querySelectorAll(".tier-choice-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const tier = btn.dataset.tier;
            onSelectTier(tier);
        });
    });

    // Flow Step 2: Sector Selection
    if (sectorSelect) {
        sectorSelect.addEventListener("change", e => {
            onSelectSector(e.target.value);
        });
    }

    // Flow Step 3: Stock Selection
    if (stockSelect) {
        stockSelect.addEventListener("change", e => {
            onSelectStock(e.target.value);
        });
    }

    // Timeframe Buttons
    document.querySelectorAll("[data-period]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("[data-period]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentPeriod = btn.dataset.period;
            if (currentTicker) {
                loadStockData(currentTicker);
            }
        });
    });

    // Table Search & Quick Filter
    if (tableSearch) {
        tableSearch.addEventListener("input", e => {
            const query = e.target.value.trim().toLowerCase();
            
            // If table has records, filter table
            if (allRecords.length > 0) {
                if (!query) {
                    filteredRecords = [...allRecords];
                } else {
                    filteredRecords = allRecords.filter(r => r.Date.toLowerCase().includes(query));
                }
                currentPage = 1;
                renderTable();
            }

            // Also filter stockSelect options if searching stock names
            if (stocksList.length > 0 && stockSelect && !stockSelect.disabled) {
                const options = stockSelect.querySelectorAll("option");
                let matchCount = 0;
                options.forEach(opt => {
                    if (!opt.value) return; // Skip placeholder
                    const text = opt.textContent.toLowerCase();
                    const val = opt.value.toLowerCase();
                    if (!query || text.includes(query) || val.includes(query)) {
                        opt.style.display = "";
                        matchCount++;
                    } else {
                        opt.style.display = "none";
                    }
                });
            }
        });
    }

    // Refresh & Export
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            if (currentTicker) handleRefreshStock(currentTicker);
        });
    }
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener("click", exportToCsv);
    }

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

    // ─── Initialize Strategy Recommendation Scanner ──────────────────
    initStrategyScanner();
}

// ==========================================================================
// Strategy Scanner & Multi-Timeframe Momentum Monitor Client Logic
// ==========================================================================

let activeScannerStrategyId = "ALL";
let registeredStrategies = [];

// DOM Elements for Strategy Scanner
const runScannerBtn = document.getElementById("runScannerBtn");
const scanBtnText = document.getElementById("scanBtnText");
const strategyTabsBar = document.getElementById("strategyTabsBar");
const currentStratName = document.getElementById("currentStratName");
const currentStratDesc = document.getElementById("currentStratDesc");
const currentStratUniverse = document.getElementById("currentStratUniverse");
const scannerEmptyState = document.getElementById("scannerEmptyState");
const candidatesGrid = document.getElementById("candidatesGrid");

// DOM Elements for MTF Momentum Monitor
const mtfSignalVerdict = document.getElementById("mtfSignalVerdict");
const dailyRsiVal = document.getElementById("dailyRsiVal");
const dailyRegime = document.getElementById("dailyRegime");
const dailyGaugeFill = document.getElementById("dailyGaugeFill");
const dailyStatusNote = document.getElementById("dailyStatusNote");

const weeklyRsiVal = document.getElementById("weeklyRsiVal");
const weeklyRegime = document.getElementById("weeklyRegime");
const weeklyGaugeFill = document.getElementById("weeklyGaugeFill");
const weeklyStatusNote = document.getElementById("weeklyStatusNote");

const monthlyRsiVal = document.getElementById("monthlyRsiVal");
const monthlyRegime = document.getElementById("monthlyRegime");
const monthlyGaugeFill = document.getElementById("monthlyGaugeFill");
const monthlyStatusNote = document.getElementById("monthlyStatusNote");

const strategyCheckDetails = document.getElementById("strategyCheckDetails");

// ─── Initialize Strategy Recommendation Scanner & Custom Builder ───────────
async function initStrategyScanner() {
    await fetchStrategiesList();

    // Run Scanner Button
    if (runScannerBtn) {
        runScannerBtn.addEventListener("click", runMarketScanner);
    }

    // Modal Triggers
    const btnOpenCreate = document.getElementById("btnOpenCreateScanner");
    if (btnOpenCreate) {
        btnOpenCreate.addEventListener("click", () => openStrategyModal(null));
    }

    const btnEditCurrent = document.getElementById("btnEditCurrentStrategy");
    if (btnEditCurrent) {
        btnEditCurrent.addEventListener("click", () => {
            if (activeScannerStrategyId && activeScannerStrategyId !== "ALL") {
                openStrategyModal(activeScannerStrategyId);
            }
        });
    }

    const btnResetCurrent = document.getElementById("btnResetCurrentStrategy");
    if (btnResetCurrent) {
        btnResetCurrent.addEventListener("click", () => {
            if (activeScannerStrategyId && activeScannerStrategyId !== "ALL") {
                handleResetStrategy(activeScannerStrategyId);
            }
        });
    }

    const btnDeleteCurrent = document.getElementById("btnDeleteCurrentStrategy");
    if (btnDeleteCurrent) {
        btnDeleteCurrent.addEventListener("click", () => {
            if (activeScannerStrategyId && activeScannerStrategyId !== "ALL") {
                handleDeleteStrategy(activeScannerStrategyId);
            }
        });
    }

    // Modal Close & Actions
    const btnCloseModal = document.getElementById("btnCloseStrategyModal");
    if (btnCloseModal) btnCloseModal.addEventListener("click", closeStrategyModal);

    const btnCancelModal = document.getElementById("btnCancelStrategyModal");
    if (btnCancelModal) btnCancelModal.addEventListener("click", closeStrategyModal);

    const btnSaveModal = document.getElementById("btnSaveStrategyModal");
    if (btnSaveModal) btnSaveModal.addEventListener("click", saveStrategyFromModal);

    const btnAddCond = document.getElementById("btnAddConditionRow");
    if (btnAddCond) btnAddCond.addEventListener("click", () => addConditionRow());
}

async function fetchStrategiesList() {
    try {
        const res = await fetch("/api/strategies");
        if (res.ok) {
            const data = await res.json();
            registeredStrategies = data.strategies || [];
            renderStrategyTabs();
            updateScannerInfoStrip(activeScannerStrategyId);
        }
    } catch (e) {
        console.warn("Could not fetch strategies metadata:", e);
    }
}

function renderStrategyTabs() {
    if (!strategyTabsBar) return;

    let html = `
        <button class="strat-tab-btn ${activeScannerStrategyId === "ALL" ? "active" : ""}" data-strategy="ALL">
            <span class="tab-title">All Setups (${registeredStrategies.length})</span>
            <span class="tab-sub">Comprehensive Market Scan</span>
        </button>
    `;

    registeredStrategies.forEach((strat, index) => {
        const isActive = activeScannerStrategyId === strat.strategy_id;
        const tagHtml = strat.is_builtin
            ? (strat.is_customized ? `<span class="strat-tag-modified" style="margin-left:4px;">Modified</span>` : "")
            : `<span class="strat-tag-custom" style="margin-left:4px;">Custom</span>`;
        
        const titleText = strat.is_builtin ? `Strategy ${index + 1}` : strat.name;

        html += `
            <button class="strat-tab-btn ${isActive ? "active" : ""}" data-strategy="${strat.strategy_id}">
                <span class="tab-title">${titleText} ${tagHtml}</span>
                <span class="tab-sub">${strat.name} (${strat.universe})</span>
            </button>
        `;
    });

    strategyTabsBar.innerHTML = html;

    // Reattach click events
    strategyTabsBar.querySelectorAll(".strat-tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            strategyTabsBar.querySelectorAll(".strat-tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            activeScannerStrategyId = btn.dataset.strategy;
            updateScannerInfoStrip(activeScannerStrategyId);
        });
    });
}

function updateScannerInfoStrip(stratId) {
    const editBtn = document.getElementById("btnEditCurrentStrategy");
    const resetBtn = document.getElementById("btnResetCurrentStrategy");
    const deleteBtn = document.getElementById("btnDeleteCurrentStrategy");
    const customBadge = document.getElementById("stratCustomBadge");
    const modifiedBadge = document.getElementById("stratModifiedBadge");

    if (stratId === "ALL") {
        if (currentStratName) currentStratName.textContent = `All Active Setups (${registeredStrategies.length})`;
        if (currentStratDesc) currentStratDesc.textContent = "Scanning the market across all active built-in and user-customized strategies simultaneously.";
        if (currentStratUniverse) currentStratUniverse.textContent = "Universe: All Configured";
        if (editBtn) editBtn.style.display = "none";
        if (resetBtn) resetBtn.style.display = "none";
        if (deleteBtn) deleteBtn.style.display = "none";
        if (customBadge) customBadge.style.display = "none";
        if (modifiedBadge) modifiedBadge.style.display = "none";
        return;
    }

    const strat = registeredStrategies.find(s => s.strategy_id === stratId);
    if (strat) {
        if (currentStratName) currentStratName.textContent = strat.name;
        if (currentStratDesc) currentStratDesc.textContent = strat.purpose || strat.description;
        if (currentStratUniverse) currentStratUniverse.textContent = `Universe: ${strat.universe}`;

        if (editBtn) editBtn.style.display = "inline-flex";
        if (customBadge) customBadge.style.display = strat.is_builtin ? "none" : "inline-block";
        if (modifiedBadge) modifiedBadge.style.display = strat.is_customized ? "inline-block" : "none";

        if (resetBtn) resetBtn.style.display = (strat.is_builtin && strat.is_customized) ? "inline-flex" : "none";
        if (deleteBtn) deleteBtn.style.display = (!strat.is_builtin) ? "inline-flex" : "none";
    }
}

// ─── Strategy Modal & Builder Functions ────────────────────────────────────

function openStrategyModal(strategyId = null) {
    const modal = document.getElementById("strategyModal");
    if (!modal) return;

    const modalTitle = document.getElementById("strategyModalTitle");
    const modalPretitle = document.getElementById("strategyModalPretitle");
    const modalStrategyId = document.getElementById("modalStrategyId");
    const inputName = document.getElementById("inputStrategyName");
    const selectUniverse = document.getElementById("selectStrategyUniverse");
    const inputDesc = document.getElementById("inputStrategyDesc");
    const btnSaveText = document.getElementById("btnSaveStrategyText");
    const container = document.getElementById("conditionsListContainer");

    if (container) container.innerHTML = "";

    if (strategyId) {
        const strat = registeredStrategies.find(s => s.strategy_id === strategyId);
        if (!strat) return;

        if (modalPretitle) modalPretitle.textContent = strat.is_builtin ? "CUSTOMIZE BUILT-IN SCANNER" : "EDIT CUSTOM SCANNER";
        if (modalTitle) modalTitle.textContent = `Customize: ${strat.name}`;
        if (modalStrategyId) modalStrategyId.value = strat.strategy_id;
        if (inputName) inputName.value = strat.name;
        if (selectUniverse) selectUniverse.value = strat.universe || "NIFTY 500";
        if (inputDesc) inputDesc.value = strat.purpose || strat.description || "";
        if (btnSaveText) btnSaveText.textContent = "Save Changes & Update Scanner";

        // Populate existing conditions
        (strat.conditions || []).forEach(c => addConditionRow(c));
    } else {
        if (modalPretitle) modalPretitle.textContent = "CREATE SCANNER";
        if (modalTitle) modalTitle.textContent = "Create Custom Technical Scanner";
        if (modalStrategyId) modalStrategyId.value = "";
        if (inputName) inputName.value = "";
        if (selectUniverse) selectUniverse.value = "NIFTY 500";
        if (inputDesc) inputDesc.value = "";
        if (btnSaveText) btnSaveText.textContent = "Save & Activate Scanner";

        // Default with 2 standard condition rows
        addConditionRow({ timeframe: "DAILY", indicator: "RSI", period: 14, operator: ">", value: 55.0, shift: 0 });
        addConditionRow({ timeframe: "DAILY", indicator: "CLOSE", period: 1, operator: ">", value: 100.0, shift: 0 });
    }

    modal.style.display = "flex";
}

function closeStrategyModal() {
    const modal = document.getElementById("strategyModal");
    if (modal) modal.style.display = "none";
}

function addConditionRow(c = null) {
    const container = document.getElementById("conditionsListContainer");
    if (!container) return;

    const row = document.createElement("div");
    row.className = "condition-row-card";

    const tf = c ? c.timeframe : "DAILY";
    const ind = c ? (c.indicator || "RSI").toUpperCase() : "RSI";
    const per = c ? (c.period || 14) : 14;
    const op = c ? (c.operator || ">").toLowerCase() : ">";
    const val = c ? c.value : 60.0;
    const valHigh = c && c.value_high !== null && c.value_high !== undefined ? c.value_high : 70.0;
    const shift = c ? (c.shift || 0) : 0;

    const isBetween = op === "between";

    row.innerHTML = `
        <select class="cond-select cond-tf">
            <option value="DAILY" ${tf === "DAILY" ? "selected" : ""}>Daily</option>
            <option value="WEEKLY" ${tf === "WEEKLY" ? "selected" : ""}>Weekly</option>
            <option value="MONTHLY" ${tf === "MONTHLY" ? "selected" : ""}>Monthly</option>
        </select>
        <select class="cond-select cond-ind" onchange="onCondIndicatorChange(this)">
            <option value="RSI" ${ind === "RSI" ? "selected" : ""}>RSI (Wilder)</option>
            <option value="SMA" ${ind === "SMA" ? "selected" : ""}>SMA</option>
            <option value="EMA" ${ind === "EMA" ? "selected" : ""}>EMA</option>
            <option value="CLOSE" ${ind === "CLOSE" ? "selected" : ""}>Close Price</option>
            <option value="VOLUME" ${ind === "VOLUME" ? "selected" : ""}>Volume</option>
            <option value="RVOL" ${ind === "RVOL" ? "selected" : ""}>RVOL (Rel Vol)</option>
            <option value="ATH_PCT" ${ind === "ATH_PCT" || ind === "52W_HIGH_PCT" ? "selected" : ""}>52W High %</option>
        </select>
        <input type="number" class="cond-input cond-per" value="${per}" min="1" max="500" title="Period / Window">
        <select class="cond-select cond-op" onchange="onCondOperatorChange(this)">
            <option value=">" ${op === ">" ? "selected" : ""}>&gt; (Greater)</option>
            <option value="<" ${op === "<" ? "selected" : ""}>&lt; (Less)</option>
            <option value=">=" ${op === ">=" ? "selected" : ""}>&gt;= (GTE)</option>
            <option value="<=" ${op === "<=" ? "selected" : ""}>&lt;= (LTE)</option>
            <option value="between" ${op === "between" ? "selected" : ""}>Between</option>
            <option value="cross_above" ${op === "cross_above" ? "selected" : ""}>Cross Above</option>
            <option value="cross_below" ${op === "cross_below" ? "selected" : ""}>Cross Below</option>
        </select>
        <div class="cond-val-wrap">
            <input type="number" step="any" class="cond-input cond-val" value="${val}" placeholder="Value">
            <span class="cond-val-sep" style="${isBetween ? "" : "display:none;"}">to</span>
            <input type="number" step="any" class="cond-input cond-val-high" value="${valHigh}" placeholder="High" style="${isBetween ? "" : "display:none;"}">
        </div>
        <select class="cond-select cond-shift">
            <option value="0" ${shift === 0 ? "selected" : ""}>Current</option>
            <option value="1" ${shift === 1 ? "selected" : ""}>Previous</option>
        </select>
        <button type="button" class="btn-remove-cond" onclick="this.closest('.condition-row-card').remove()" title="Remove rule">✕</button>
    `;

    container.appendChild(row);
}

function onCondIndicatorChange(sel) {
    const row = sel.closest(".condition-row-card");
    if (!row) return;
    const perInput = row.querySelector(".cond-per");
    const valInput = row.querySelector(".cond-val");
    const ind = sel.value;

    if (ind === "RSI") {
        if (perInput) perInput.value = "14";
        if (valInput) valInput.value = "60";
    } else if (ind === "SMA" || ind === "EMA") {
        if (perInput) perInput.value = "20";
        if (valInput) valInput.value = "100";
    } else if (ind === "RVOL") {
        if (perInput) perInput.value = "20";
        if (valInput) valInput.value = "1.5";
    } else if (ind === "ATH_PCT") {
        if (perInput) perInput.value = "252";
        if (valInput) valInput.value = "95";
    } else if (ind === "CLOSE" || ind === "VOLUME") {
        if (perInput) perInput.value = "1";
    }
}

function onCondOperatorChange(sel) {
    const row = sel.closest(".condition-row-card");
    if (!row) return;
    const isBetween = sel.value === "between";
    const sep = row.querySelector(".cond-val-sep");
    const highInput = row.querySelector(".cond-val-high");
    if (sep) sep.style.display = isBetween ? "inline" : "none";
    if (highInput) highInput.style.display = isBetween ? "inline-block" : "none";
}

function applyStrategyTemplate(templateKey) {
    const container = document.getElementById("conditionsListContainer");
    if (!container) return;
    container.innerHTML = "";

    const nameInput = document.getElementById("inputStrategyName");
    const descInput = document.getElementById("inputStrategyDesc");

    if (templateKey === "RSI_MOMENTUM") {
        if (nameInput) nameInput.value = "Strong MTF RSI Momentum";
        if (descInput) descInput.value = "Multi-timeframe momentum alignment: Monthly RSI > 60, Weekly RSI > 60, and Daily RSI > 58.";
        addConditionRow({ timeframe: "MONTHLY", indicator: "RSI", period: 14, operator: ">", value: 60.0 });
        addConditionRow({ timeframe: "WEEKLY", indicator: "RSI", period: 14, operator: ">", value: 60.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "RSI", period: 14, operator: ">", value: 58.0 });
    } else if (templateKey === "EMA_PULLBACK") {
        if (nameInput) nameInput.value = "20 EMA Trend Pullback";
        if (descInput) descInput.value = "Higher-timeframe bullish trend where price has pulled back near the Daily 20 EMA.";
        addConditionRow({ timeframe: "WEEKLY", indicator: "RSI", period: 14, operator: ">", value: 58.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "CLOSE", period: 1, operator: ">", value: 50.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "RSI", period: 14, operator: "<", value: 48.0 });
    } else if (templateKey === "ATH_BREAKOUT") {
        if (nameInput) nameInput.value = "52-Week High Breakout";
        if (descInput) descInput.value = "Stocks within 3% of their 52-week High with strong Weekly RSI and volume expansion.";
        addConditionRow({ timeframe: "WEEKLY", indicator: "RSI", period: 14, operator: ">", value: 60.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "ATH_PCT", period: 252, operator: ">=", value: 97.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "RVOL", period: 20, operator: ">=", value: 1.2 });
    } else if (templateKey === "RSI_OVERSOLD") {
        if (nameInput) nameInput.value = "Daily RSI Oversold Reversal";
        if (descInput) descInput.value = "Stocks rebounding from oversold readings while maintaining monthly structural support.";
        addConditionRow({ timeframe: "MONTHLY", indicator: "RSI", period: 14, operator: ">=", value: 40.0 });
        addConditionRow({ timeframe: "DAILY", indicator: "RSI", period: 14, operator: "between", value: 30.0, value_high: 42.0 });
    }
}

async function saveStrategyFromModal() {
    const stratId = document.getElementById("modalStrategyId").value.trim();
    const name = document.getElementById("inputStrategyName").value.trim();
    const universe = document.getElementById("selectStrategyUniverse").value.trim();
    const description = document.getElementById("inputStrategyDesc").value.trim();

    if (!name) {
        showToast("Please enter a name for the scanner.", "warning");
        return;
    }

    const container = document.getElementById("conditionsListContainer");
    const rows = container ? container.querySelectorAll(".condition-row-card") : [];
    if (rows.length === 0) {
        showToast("Please add at least one condition rule.", "warning");
        return;
    }

    const conditions = [];
    rows.forEach(r => {
        const tf = r.querySelector(".cond-tf").value;
        const ind = r.querySelector(".cond-ind").value;
        const per = parseInt(r.querySelector(".cond-per").value, 10) || 14;
        const op = r.querySelector(".cond-op").value;
        const val = parseFloat(r.querySelector(".cond-val").value);
        const highVal = op === "between" ? parseFloat(r.querySelector(".cond-val-high").value) : null;
        const shift = parseInt(r.querySelector(".cond-shift").value, 10) || 0;

        if (isNaN(val)) return;

        conditions.push({
            timeframe: tf,
            indicator: ind,
            period: per,
            operator: op,
            value: val,
            value_high: highVal,
            shift: shift,
        });
    });

    if (conditions.length === 0) {
        showToast("Please specify valid condition threshold values.", "warning");
        return;
    }

    const payload = {
        name: name,
        universe: universe,
        description: description,
        purpose: description,
        conditions: conditions,
    };

    try {
        let res;
        if (stratId) {
            // Update existing
            res = await fetch(`/api/strategies/${encodeURIComponent(stratId)}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        } else {
            // Create new
            res = await fetch("/api/strategies", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        }

        if (!res.ok) {
            const errJson = await res.json();
            throw new Error(errJson.detail || "Server rejected strategy configuration");
        }

        const data = await res.json();
        showToast(data.message || "✓ Scanner saved successfully!", "success");
        closeStrategyModal();

        // Refresh strategies and switch to the newly saved strategy
        await fetchStrategiesList();
        if (data.strategy && data.strategy.strategy_id) {
            activeScannerStrategyId = data.strategy.strategy_id;
            renderStrategyTabs();
            updateScannerInfoStrip(activeScannerStrategyId);
        }
    } catch (err) {
        console.error("Save strategy failed:", err);
        showToast(`Failed to save scanner: ${err.message}`, "error");
    }
}

async function handleResetStrategy(strategyId) {
    if (!confirm("Are you sure you want to reset this strategy back to its default rules?")) return;

    try {
        const res = await fetch(`/api/strategies/${encodeURIComponent(strategyId)}/reset`, { method: "POST" });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to reset");
        }
        const data = await res.json();
        showToast(data.message || "✓ Strategy restored to default rules", "success");
        await fetchStrategiesList();
    } catch (e) {
        showToast(`Reset error: ${e.message}`, "error");
    }
}

async function handleDeleteStrategy(strategyId) {
    if (!confirm("Are you sure you want to delete this custom scanner? This cannot be undone.")) return;

    try {
        const res = await fetch(`/api/strategies/${encodeURIComponent(strategyId)}`, { method: "DELETE" });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to delete");
        }
        const data = await res.json();
        showToast(data.message || "✓ Custom scanner deleted", "info");
        activeScannerStrategyId = "ALL";
        await fetchStrategiesList();
    } catch (e) {
        showToast(`Delete error: ${e.message}`, "error");
    }
}

async function runMarketScanner() {
    if (!runScannerBtn) return;
    runScannerBtn.disabled = true;
    if (scanBtnText) scanBtnText.textContent = "Scanning Universe...";

    if (candidatesGrid) {
        candidatesGrid.style.display = "grid";
        candidatesGrid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--text-secondary);">
                <div class="spinner" style="margin: 0 auto 12px auto;"></div>
                <div style="font-weight: 700; color: #F1F5F9;">Running Multi-Timeframe Strategy Scanner...</div>
                <div style="font-size: 0.82rem; color: var(--text-muted); margin-top: 4px;">Evaluating equity universe with zero look-ahead bias</div>
            </div>
        `;
    }
    if (scannerEmptyState) scannerEmptyState.style.display = "none";

    try {
        const params = new URLSearchParams({ strategy_id: activeScannerStrategyId });
        const res = await fetch(`/api/scan?${params.toString()}`);
        if (!res.ok) throw new Error(`Scan request failed with HTTP ${res.status}`);
        const data = await res.json();

        renderScannerCandidates(data);
    } catch (err) {
        console.error("Scanner failed:", err);
        if (candidatesGrid) {
            candidatesGrid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: #FB7185; background: rgba(251, 113, 133, 0.1); border-radius: var(--radius-md); border: 1px solid rgba(251, 113, 133, 0.3);">
                    Failed to run scanner: ${err.message}. Please try again.
                </div>
            `;
        }
    } finally {
        runScannerBtn.disabled = false;
        if (scanBtnText) scanBtnText.textContent = "Scan Setups";
    }
}

function renderScannerCandidates(data) {
    if (!candidatesGrid) return;

    let candidates = [];
    if (data.strategy_id === "ALL") {
        const byStrat = data.results_by_strategy || {};
        for (const [sId, sRes] of Object.entries(byStrat)) {
            if (Array.isArray(sRes)) {
                candidates.push(...sRes);
            } else if (sRes.candidates) {
                candidates.push(...sRes.candidates);
            }
        }
    } else {
        candidates = data.candidates || [];
    }

    if (candidates.length === 0) {
        candidatesGrid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px; background: rgba(0,0,0,0.2); border-radius: var(--radius-md); border: 1px dashed rgba(255,255,255,0.12);">
                <div style="font-size: 2rem; margin-bottom: 8px;">🛡️</div>
                <div style="font-size: 1.1rem; font-weight: 700; color: #FCD34D;">No Stocks Currently Satisfy Entry Criteria</div>
                <div style="font-size: 0.86rem; color: var(--text-muted); max-width: 500px; margin: 8px auto 0 auto; line-height: 1.5;">
                    <strong>"No trades is much better than loss trades."</strong> None of the scanned stocks currently meet the strict multi-timeframe conditions. Check back after market hours.
                </div>
            </div>
        `;
        return;
    }

    candidatesGrid.innerHTML = candidates.map(c => {
        const ind = c.indicators || {};
        const dailyRsi = ind.daily_rsi_14 !== undefined && ind.daily_rsi_14 !== null ? Number(ind.daily_rsi_14).toFixed(1) : "--";
        const weeklyRsi = ind.weekly_rsi_14 !== undefined && ind.weekly_rsi_14 !== null ? Number(ind.weekly_rsi_14).toFixed(1) : "--";
        const monthlyRsi = ind.monthly_rsi_14 !== undefined && ind.monthly_rsi_14 !== null ? Number(ind.monthly_rsi_14).toFixed(1) : "--";
        const prevWeeklyRsi = ind.prev_weekly_rsi_14 !== undefined && ind.prev_weekly_rsi_14 !== null ? Number(ind.prev_weekly_rsi_14).toFixed(1) : null;

        const conditionsHtml = (c.conditions || []).map(cond => `
            <div class="evidence-row">
                <span class="evidence-check">${cond.passed ? "✓" : "✗"}</span>
                <span>${cond.condition_desc || cond.condition} (Actual: <strong>${cond.actual !== undefined ? cond.actual : cond.actual_value}</strong>)</span>
            </div>
        `).join("");

        const stratDisplay = c.strategy_name || c.strategy_id;

        return `
            <div class="candidate-card" data-ticker="${c.symbol}">
                <div class="candidate-card-header">
                    <div>
                        <div class="candidate-ticker">${c.symbol.replace(".NS", "")}</div>
                        <div class="candidate-company" title="${c.company_name}">${c.company_name}</div>
                    </div>
                    <div class="candidate-badge-col">
                        <span class="candidate-strat-badge">${c.universe}</span>
                        <span class="candidate-sector-pill">${c.sector}</span>
                    </div>
                </div>

                <div style="font-size: 0.74rem; font-weight: 700; color: #34D399; display: flex; align-items: center; gap: 4px;">
                    <span>⚡</span> <span>${stratDisplay}</span>
                </div>

                <div class="candidate-mtf-pills">
                    <div class="mtf-pill">
                        <span class="mtf-pill-lbl">Daily RSI</span>
                        <span class="mtf-pill-val highlight-amber">${dailyRsi}</span>
                    </div>
                    <div class="mtf-pill">
                        <span class="mtf-pill-lbl">Weekly RSI</span>
                        <span class="mtf-pill-val highlight-green">${weeklyRsi}${prevWeeklyRsi ? `<span style="font-size: 0.7em; color: #94A3B8;"> (was ${prevWeeklyRsi})</span>` : ""}</span>
                    </div>
                    <div class="mtf-pill">
                        <span class="mtf-pill-lbl">Monthly RSI</span>
                        <span class="mtf-pill-val highlight-blue">${monthlyRsi}</span>
                    </div>
                </div>

                <div class="candidate-evidence-list">
                    ${conditionsHtml}
                </div>

                <div class="candidate-card-footer" style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button class="btn-inspect-candidate" style="flex: 1; min-width: 130px;" onclick="selectCandidateStock('${c.symbol}', 'analysis')">
                        📊 Analyze Stock →
                    </button>
                    <button class="btn-inspect-candidate" style="flex: 1; min-width: 130px; background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); color: #60A5FA;" onclick="selectCandidateStock('${c.symbol}', 'planner')">
                        🎯 Plan Trade & Sizing →
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

function selectCandidateStock(ticker, targetTab = "analysis") {
    currentTicker = ticker;
    
    // Unlock and select in stockSelect
    if (stockSelect) {
        stockSelect.disabled = false;
        let optExists = false;
        for (let i = 0; i < stockSelect.options.length; i++) {
            if (stockSelect.options[i].value === ticker) {
                stockSelect.selectedIndex = i;
                optExists = true;
                break;
            }
        }
        if (!optExists) {
            const opt = document.createElement("option");
            opt.value = ticker;
            opt.textContent = `${ticker.replace(".NS", "")} (Selected Stock)`;
            opt.selected = true;
            stockSelect.appendChild(opt);
        }
    }

    // Sync in plannerStockSelect
    const plannerStockSelect = document.getElementById("plannerStockSelect");
    if (plannerStockSelect) {
        let optExists = false;
        for (let i = 0; i < plannerStockSelect.options.length; i++) {
            if (plannerStockSelect.options[i].value === ticker) {
                plannerStockSelect.selectedIndex = i;
                optExists = true;
                break;
            }
        }
        if (!optExists) {
            const opt = document.createElement("option");
            opt.value = ticker;
            opt.textContent = `${ticker.replace(".NS", "")} (Selected Stock)`;
            opt.selected = true;
            plannerStockSelect.appendChild(opt);
        }
    }

    // Set stepper to Step 4
    setStep(4, ticker.replace(".NS", ""));
    if (step3SelectedVal) step3SelectedVal.textContent = ticker.replace(".NS", "");

    // Hide guided flow, show workspace
    if (guidedFlowState) guidedFlowState.style.display = "none";
    if (stockWorkspace) {
        stockWorkspace.style.display = "flex";
    }

    loadStockData(ticker);

    if (targetTab === "planner") {
        switchTab("tabViewPlanner");
    } else {
        switchTab("tabViewAnalysis");
        if (stockWorkspace) {
            stockWorkspace.scrollIntoView({ behavior: "smooth" });
        }
    }
}

// Expose to window for inline onclick handlers
window.selectCandidateStock = selectCandidateStock;

// Check stock against all 4 strategies and render MTF Gauges & Verdict
async function fetchStockStrategyCheck(ticker) {
    if (!ticker) return;

    try {
        const res = await fetch(`/api/stock-strategy-check?ticker=${encodeURIComponent(ticker)}`);
        if (!res.ok) return;
        const data = await res.json();

        const ind = data.indicators || {};
        const dRsi = ind.daily_rsi_14 !== undefined && ind.daily_rsi_14 !== null ? Number(ind.daily_rsi_14) : null;
        const wRsi = ind.weekly_rsi_14 !== undefined && ind.weekly_rsi_14 !== null ? Number(ind.weekly_rsi_14) : null;
        const mRsi = ind.monthly_rsi_14 !== undefined && ind.monthly_rsi_14 !== null ? Number(ind.monthly_rsi_14) : null;

        // Daily Gauge
        if (dailyRsiVal) dailyRsiVal.textContent = dRsi !== null ? dRsi.toFixed(1) : "--";
        if (dailyGaugeFill && dRsi !== null) {
            dailyGaugeFill.style.width = `${Math.min(Math.max(dRsi, 0), 100)}%`;
        }
        if (dailyRegime && dRsi !== null) {
            if (dRsi >= 58 && dRsi <= 63) {
                dailyRegime.textContent = "Momentum (58-63)";
                dailyRegime.className = "gauge-regime regime-bullish";
            } else if (dRsi >= 39 && dRsi <= 45) {
                dailyRegime.textContent = "Pullback (39-45)";
                dailyRegime.className = "gauge-regime regime-pullback";
            } else if (dRsi > 63) {
                dailyRegime.textContent = "Strong Bullish (>63)";
                dailyRegime.className = "gauge-regime regime-bullish";
            } else if (dRsi < 39) {
                dailyRegime.textContent = "Deep Oversold (<39)";
                dailyRegime.className = "gauge-regime";
            } else {
                dailyRegime.textContent = "Neutral Zone";
                dailyRegime.className = "gauge-regime";
            }
        }

        // Weekly Gauge
        if (weeklyRsiVal) weeklyRsiVal.textContent = wRsi !== null ? wRsi.toFixed(1) : "--";
        if (weeklyGaugeFill && wRsi !== null) {
            weeklyGaugeFill.style.width = `${Math.min(Math.max(wRsi, 0), 100)}%`;
        }
        if (weeklyRegime && wRsi !== null) {
            if (wRsi > 60) {
                weeklyRegime.textContent = "Bullish Regime (>60)";
                weeklyRegime.className = "gauge-regime regime-bullish";
            } else {
                weeklyRegime.textContent = "Sub-60 Regime";
                weeklyRegime.className = "gauge-regime";
            }
        }

        // Monthly Gauge
        if (monthlyRsiVal) monthlyRsiVal.textContent = mRsi !== null ? mRsi.toFixed(1) : "--";
        if (monthlyGaugeFill && mRsi !== null) {
            monthlyGaugeFill.style.width = `${Math.min(Math.max(mRsi, 0), 100)}%`;
        }
        if (monthlyRegime && mRsi !== null) {
            if (mRsi > 60) {
                monthlyRegime.textContent = "Strong HTF (>60)";
                monthlyRegime.className = "gauge-regime regime-bullish";
            } else if (mRsi >= 40 && mRsi <= 43) {
                monthlyRegime.textContent = "Zone (40-43)";
                monthlyRegime.className = "gauge-regime regime-pullback";
            } else {
                monthlyRegime.textContent = "Neutral Trend";
                monthlyRegime.className = "gauge-regime";
            }
        }

        // Verdict Badge
        if (mtfSignalVerdict) {
            if (data.has_setup) {
                mtfSignalVerdict.className = "signal-verdict verdict-match";
                const matchNames = (data.matches || []).map(m => m.name).join(", ");
                mtfSignalVerdict.innerHTML = `<span>⚡</span> <span>VERIFIED SETUP: ${matchNames}</span>`;
            } else {
                mtfSignalVerdict.className = "signal-verdict verdict-none";
                mtfSignalVerdict.innerHTML = `<span>🛡️</span> <span>NO ACTIVE STRATEGY SETUP (Discipline: No trades > Loss trades)</span>`;
            }
        }

        // Checklist of all 4 strategies
        if (strategyCheckDetails && data.evaluations) {
            const evals = data.evaluations;
            const stratCardsHtml = Object.entries(evals).map(([sId, evalObj]) => {
                const passed = evalObj.passed;
                const conditions = evalObj.conditions || [];
                const condHtml = conditions.map(c => `
                    <div style="font-size: 0.76rem; color: ${c.passed ? '#34D399' : '#94A3B8'}; display: flex; align-items: center; gap: 6px;">
                        <span>${c.passed ? '✓' : '✗'}</span>
                        <span>${c.condition_desc} (Actual: <strong>${c.actual !== undefined ? c.actual : c.actual_value}</strong>)</span>
                    </div>
                `).join("");

                return `
                    <div class="strat-check-row ${passed ? 'is-matched' : ''}">
                        <div class="strat-check-meta">
                            <div class="strat-check-title">${evalObj.strategy_name} (${evalObj.universe})</div>
                            <div class="strat-check-purpose">${evalObj.passed ? '✓ Entry criteria satisfied! Proceed to position sizing.' : 'Does not satisfy entry conditions.'}</div>
                            <div style="margin-top: 6px; display: flex; flex-direction: column; gap: 3px;">
                                ${condHtml}
                            </div>
                        </div>
                        <div>
                            <span class="strat-status-pill ${passed ? 'pass' : 'fail'}">
                                ${passed ? '✓ PASSED' : 'NOT MET'}
                            </span>
                        </div>
                    </div>
                `;
            }).join("");

            strategyCheckDetails.innerHTML = stratCardsHtml;
        }

    } catch (err) {
        console.warn("Could not check stock strategy status:", err);
    }
}

// ==========================================================================
// Modular Tab Navigation & Universe Live Sync Hub
// ==========================================================================

function initTabNavigation() {
    const tabButtons = document.querySelectorAll(".nav-tab-btn");
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            if (targetTab) {
                switchTab(targetTab);
            }
        });
    });

    const btnSyncActiveStock = document.getElementById("btnSyncActiveStock");
    if (btnSyncActiveStock) {
        btnSyncActiveStock.addEventListener("click", () => {
            if (currentTicker) {
                handleRefreshStock(currentTicker);
            } else {
                showToast("Please select a stock first to sync live data.", "warning");
            }
        });
    }

    const btnSyncTopStocks = document.getElementById("btnSyncTopStocks");
    if (btnSyncTopStocks) {
        btnSyncTopStocks.addEventListener("click", syncTopLeaders);
    }

    const btnRefreshStats = document.getElementById("btnRefreshStats");
    if (btnRefreshStats) {
        btnRefreshStats.addEventListener("click", () => {
            loadMarketStats();
            showToast("Market stats and cache health refreshed", "info");
        });
    }

    const quickRefreshLink = document.getElementById("quickRefreshLink");
    if (quickRefreshLink) {
        quickRefreshLink.addEventListener("click", () => {
            if (currentTicker) handleRefreshStock(currentTicker);
        });
    }

    const plannerSyncBtn = document.getElementById("plannerSyncBtn");
    if (plannerSyncBtn) {
        plannerSyncBtn.addEventListener("click", () => {
            if (currentTicker) handleRefreshStock(currentTicker);
        });
    }

    const plannerStockSelect = document.getElementById("plannerStockSelect");
    if (plannerStockSelect) {
        plannerStockSelect.addEventListener("change", (e) => {
            const sym = e.target.value;
            if (sym) {
                selectCandidateStock(sym, "planner");
            }
        });
    }
}

function switchTab(tabId) {
    const tabButtons = document.querySelectorAll(".nav-tab-btn");
    tabButtons.forEach(btn => {
        if (btn.getAttribute("data-tab") === tabId) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    const panes = document.querySelectorAll(".app-tab-pane");
    panes.forEach(pane => {
        if (pane.id === tabId) {
            pane.classList.add("active");
            pane.style.display = "block";
        } else {
            pane.classList.remove("active");
            pane.style.display = "none";
        }
    });

    if (tabId === "tabViewPlanner") {
        const syncLbl = document.getElementById("plannerTickerBadge");
        if (syncLbl && currentTicker) {
            syncLbl.textContent = currentTicker.replace(".NS", "");
        }
        if (currentTicker) {
            fetchStockStrategyCheck(currentTicker);
            fetchTradeSetup(currentTicker);
        }
    }

    if (tabId === "tabViewUniverse") {
        loadMarketStats();
    }
}

// Toast notification helper
function showToast(message, type = "info") {
    const toast = document.getElementById("toastNotification");
    if (!toast) return;

    const iconMap = {
        success: "✓",
        error: "✕",
        warning: "⚠️",
        info: "ℹ️"
    };

    const icon = iconMap[type] || "ℹ️";
    toast.className = `toast-notification toast-${type} show`;
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${message}</span>
    `;

    if (window._toastTimeout) clearTimeout(window._toastTimeout);
    window._toastTimeout = setTimeout(() => {
        toast.className = "toast-notification";
    }, 4500);
}

// Console logger for Universe Tab
function appendSyncLog(message, type = "info") {
    const consoleBody = document.getElementById("syncLogBody");
    if (!consoleBody) return;
    const timeStr = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = `console-line ${type}`;
    line.textContent = `[${timeStr}] ${message}`;
    consoleBody.appendChild(line);
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// Live refresh stock handler: fetches latest candles from Yahoo Finance/NSE
async function handleRefreshStock(ticker) {
    if (!ticker) {
        showToast("Please select a stock first to refresh data.", "warning");
        return;
    }

    const cleanSym = ticker.replace(".NS", "");
    const refreshBtn = document.getElementById("refreshBtn");
    const plannerSyncBtn = document.getElementById("plannerSyncBtn");
    const quickRefreshLink = document.getElementById("quickRefreshLink");
    const btnSyncActiveStock = document.getElementById("btnSyncActiveStock");

    const originalRefreshHtml = refreshBtn ? refreshBtn.innerHTML : "";
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = `<span>⏳</span> Syncing ${cleanSym}...`;
    }
    if (plannerSyncBtn) {
        plannerSyncBtn.disabled = true;
        plannerSyncBtn.textContent = "⏳ Syncing...";
    }
    if (quickRefreshLink) {
        quickRefreshLink.disabled = true;
        quickRefreshLink.textContent = "⏳ Syncing...";
    }
    if (btnSyncActiveStock) {
        btnSyncActiveStock.disabled = true;
    }

    showToast(`Pulling latest trading candles for ${cleanSym} from Yahoo Finance / NSE...`, "info");
    appendSyncLog(`Requesting live candles for ${ticker} from Yahoo Finance...`, "info");

    try {
        await loadStockData(ticker, true);
        const latestDate = allRecords.length > 0 ? allRecords[0].Date : "Today";
        showToast(`✓ ${cleanSym} updated with latest market candles (${latestDate})`, "success");
        appendSyncLog(`✓ ${ticker} refreshed successfully! Latest candle: ${latestDate} (${allRecords.length} records).`, "success");
        loadMarketStats();
    } catch (err) {
        console.error("Refresh failed:", err);
        showToast(`Failed to refresh data for ${cleanSym}: ${err.message}`, "error");
        appendSyncLog(`✕ Failed to refresh ${ticker}: ${err.message}`, "error");
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = originalRefreshHtml || `<span>🔄</span> Refresh Data`;
        }
        if (plannerSyncBtn) {
            plannerSyncBtn.disabled = false;
            plannerSyncBtn.textContent = "🔄 Sync";
        }
        if (quickRefreshLink) {
            quickRefreshLink.disabled = false;
            quickRefreshLink.textContent = "🔄 Sync Latest";
        }
        if (btnSyncActiveStock) {
            btnSyncActiveStock.disabled = false;
        }
    }
}

// Loads market stats and sector breakdown in Universe Tab
async function loadMarketStats() {
    try {
        const res = await fetch("/api/market-stats");
        if (!res.ok) return;
        const data = await res.json();

        const statsLatestDate = document.getElementById("statsLatestDate");
        if (statsLatestDate) {
            statsLatestDate.textContent = data.newest_cached_date || "Live Feed";
        }

        const statCachedTickers = document.getElementById("statCachedTickers");
        if (statCachedTickers) {
            statCachedTickers.textContent = `${data.cached_tickers_count} Tickers Cached`;
        }

        const universeSectorsGrid = document.getElementById("universeSectorsGrid");
        if (universeSectorsGrid && data.sector_breakdown) {
            universeSectorsGrid.innerHTML = Object.entries(data.sector_breakdown).map(([sec, count]) => `
                <div class="sector-card" onclick="selectSectorFromUniverse('${sec.replace(/'/g, "\\'")}')">
                    <span class="sector-card-name">${sec}</span>
                    <span class="sector-card-count">${count} Stocks →</span>
                </div>
            `).join("");
        }
    } catch (err) {
        console.warn("Could not load market stats:", err);
    }
}

function selectSectorFromUniverse(secName) {
    switchTab("tabViewAnalysis");
    onSelectTier("ALL");
    setTimeout(() => {
        if (sectorSelect) {
            sectorSelect.value = secName;
            onSelectSector(secName);
        }
    }, 200);
}

// Batch sync top 10 NIFTY Leaders
async function syncTopLeaders() {
    const btn = document.getElementById("btnSyncTopStocks");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="btn-icon">⏳</span> Syncing Top 10...`;
    }

    const topLeaders = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
        "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "ITC.NS",
        "LT.NS", "HINDUNILVR.NS"
    ];

    showToast(`Starting live synchronization for ${topLeaders.length} NIFTY leaders...`, "info");
    appendSyncLog(`Initiating batch sync for ${topLeaders.length} top index constituents...`, "info");

    let count = 0;
    for (const sym of topLeaders) {
        try {
            appendSyncLog(`Syncing ${sym}...`, "info");
            const res = await fetch(`/api/sync-stock?ticker=${encodeURIComponent(sym)}`);
            if (res.ok) {
                const resData = await res.json();
                count++;
                appendSyncLog(`✓ ${sym} updated up to ${resData.latest_date} (Close: ₹${resData.latest_close})`, "success");
            }
        } catch (e) {
            appendSyncLog(`✕ Could not sync ${sym}: ${e.message}`, "error");
        }
    }

    showToast(`✓ Batch sync completed! ${count}/${topLeaders.length} stocks updated.`, "success");
    appendSyncLog(`Batch sync finished: ${count}/${topLeaders.length} stocks up to date.`, "success");
    loadMarketStats();

    if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<span class="btn-icon">⚡</span> Sync Top 10 NIFTY Leaders`;
    }

    if (currentTicker && topLeaders.includes(currentTicker)) {
        loadStockData(currentTicker);
    }
}

// Expose helpers globally
window.switchTab = switchTab;
window.handleRefreshStock = handleRefreshStock;
window.selectSectorFromUniverse = selectSectorFromUniverse;
window.syncTopLeaders = syncTopLeaders;
window.showToast = showToast;
window.openStrategyModal = openStrategyModal;
window.closeStrategyModal = closeStrategyModal;
window.addConditionRow = addConditionRow;
window.onCondIndicatorChange = onCondIndicatorChange;
window.onCondOperatorChange = onCondOperatorChange;
window.applyStrategyTemplate = applyStrategyTemplate;
window.saveStrategyFromModal = saveStrategyFromModal;
window.handleResetStrategy = handleResetStrategy;
window.handleDeleteStrategy = handleDeleteStrategy;

document.addEventListener("DOMContentLoaded", init);


