const DATA_BASE_URL = "./data";

const state = {
    selectedDate: null,
    availableDates: [],
    signals: [],
    selectedRate: "all",
    selectedSignals: new Set(),
    activeSignal: null,
    searchText: "",
    rows: []
};

const elements = {
    // dateFilter: document.querySelector("#dateFilter"),
    dateFilterButton: document.querySelector("#dateFilterButton"),
    dateFilterMenu: document.querySelector("#dateFilterMenu"),
    searchInput: document.querySelector("#searchInput"),
    rateFilter: document.querySelector("#rateFilter"),
    reloadButton: document.querySelector("#reloadButton"),
    selectAllButton: document.querySelector("#selectAllButton"),
    clearAllButton: document.querySelector("#clearAllButton"),
    signalCheckboxes: document.querySelector("#signalCheckboxes"),
    selectedSignalCount: document.querySelector("#selectedSignalCount"),
    signalTabs: document.querySelector("#signalTabs"),
    resultSummary: document.querySelector("#resultSummary"),
    coinList: document.querySelector("#coinList"),
    emptyState: document.querySelector("#emptyState"),
    loadingIndicator: document.querySelector("#loadingIndicator"),
    errorBox: document.querySelector("#errorBox")
};

function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = String(value);
    return element.innerHTML;
}

function getSignalLabel(signal) {
    return signal === "OPPOSITE_SIGNAL_EXIT"
        ? "OPPOSITE"
        : signal.replaceAll("_", " ");
}

function getSignalSortValue(signal) {
    if (signal === "OPPOSITE_SIGNAL_EXIT") {
        return -1;
    }

    const match = signal.match(/^TP_(\d+(?:\.\d+)?)%$/);

    if (match) {
        return Number(match[1]);
    }

    return Number.MAX_SAFE_INTEGER;
}

function sortSignals(signals) {
    return [...signals].sort((a, b) => {
        const valueA = getSignalSortValue(a);
        const valueB = getSignalSortValue(b);

        if (valueA !== valueB) {
            return valueA - valueB;
        }

        return a.localeCompare(b);
    });
}

function formatDateLabel(date) {
    const [year, month, day] = date.split("-");

    return `${year}년 ${Number(month)}월 ${Number(day)}일 주차`;
}

function setLoading(isLoading) {
    elements.loadingIndicator.classList.toggle("d-none", !isLoading);
    elements.loadingIndicator.classList.toggle("d-flex", isLoading);
    elements.reloadButton.disabled = isLoading;
    // elements.dateFilter.disabled = isLoading;
    elements.dateFilterButton.disabled = isLoading;
}

function showError(message) {
    elements.errorBox.textContent = message;
    elements.errorBox.classList.remove("d-none");
}

function clearError() {
    elements.errorBox.textContent = "";
    elements.errorBox.classList.add("d-none");
}

async function fetchJson(url) {
    const response = await fetch(url, {
        method: "GET",
        headers: {
            accept: "application/json"
        },
        cache: "no-store"
    });

    if (!response.ok) {
        throw new Error(`데이터 요청 실패 (${response.status})`);
    }

    return response.json();
}

async function loadManifest() {
    const manifest = await fetchJson(
        `${DATA_BASE_URL}/manifest.json?t=${Date.now()}`
    );

    if (!Array.isArray(manifest.dates)) {
        throw new Error("manifest.json 형식이 예상과 다릅니다.");
    }

    state.availableDates = [
        ...new Set(
            manifest.dates.map((date) => String(date))
        )
    ]
        .sort((a, b) => b.localeCompare(a))
        .slice(0, 7);

    if (state.availableDates.length === 0) {
        throw new Error("조회 가능한 주차 데이터가 없습니다.");
    }

    const latest = String(manifest.latest ?? "");

    state.selectedDate = state.availableDates.includes(latest)
        ? latest
        : state.availableDates[0];
}

async function loadSnapshot(date) {
    if (!date) {
        return;
    }

    clearError();
    setLoading(true);

    try {
        const snapshot = await fetchJson(
            `${DATA_BASE_URL}/snapshots/${encodeURIComponent(date)}.json?t=${Date.now()}`
        );

        if (!Array.isArray(snapshot.rows)) {
            throw new Error(`${date} 스냅샷 형식이 예상과 다릅니다.`);
        }

        state.rows = snapshot.rows.map((row) => ({
            signal: String(row.signal),
            datetime: row.datetime ?? "",
            rate: Number(row.rate),
            symbols: Array.isArray(row.symbols)
                ? row.symbols.map((symbol) => String(symbol))
                : []
        }));

        state.signals = sortSignals(
            new Set(
                state.rows.map((row) => row.signal)
            )
        );

        state.selectedSignals = new Set(state.signals);

        if (!state.signals.includes(state.activeSignal)) {
            state.activeSignal = state.signals[0] ?? null;
        }

        render();
    } catch (error) {
        console.error(error);

        state.rows = [];
        state.signals = [];
        state.selectedSignals.clear();
        state.activeSignal = null;

        render();

        showError(error.message);
    } finally {
        setLoading(false);
    }
}

async function initializeData() {
    clearError();
    setLoading(true);

    try {
        await loadManifest();
        renderDateFilter();

        await loadSnapshot(state.selectedDate);
    } catch (error) {
        console.error(error);

        state.availableDates = [];
        state.selectedDate = null;
        state.rows = [];
        state.signals = [];
        state.selectedSignals.clear();
        state.activeSignal = null;

        render();

        showError(error.message);
    } finally {
        setLoading(false);
    }
}

// function renderDateFilter() {
//     elements.dateFilter.innerHTML = state.availableDates
//         .map((date) => `
//             <option
//                 value="${escapeHtml(date)}"
//                 ${date === state.selectedDate ? "selected" : ""}
//             >
//                 ${escapeHtml(formatDateLabel(date))}
//             </option>
//         `)
//         .join("");
// }
function renderDateFilter() {
    elements.dateFilterButton.textContent = state.selectedDate
        ? formatDateLabel(state.selectedDate)
        : "주차 선택";

    elements.dateFilterMenu.innerHTML = state.availableDates
        .map((date) => `
            <li>
                <button
                        type="button"
                        class="dropdown-item ${
                            date === state.selectedDate
                                ? "active"
                                : ""
                        }"
                        data-date="${escapeHtml(date)}"
                >
                    ${escapeHtml(formatDateLabel(date))}
                </button>
            </li>
        `)
        .join("");
}

function renderSignalCheckboxes() {
    elements.signalCheckboxes.innerHTML = state.signals
        .map((signal, index) => {
            const checked = state.selectedSignals.has(signal)
                ? "checked"
                : "";

            const id = `signal-checkbox-${index}`;

            return `
                <div class="signal-checkbox-item">
                    <div class="form-check">
                        <input
                            class="form-check-input"
                            type="checkbox"
                            value="${escapeHtml(signal)}"
                            id="${id}"
                            ${checked}
                        >

                        <label
                            class="form-check-label"
                            for="${id}"
                            title="${escapeHtml(signal)}"
                        >
                            ${escapeHtml(getSignalLabel(signal))}
                        </label>
                    </div>
                </div>
            `;
        })
        .join("");

    elements.selectedSignalCount.textContent =
        `${state.selectedSignals.size} / ${state.signals.length}개 선택됨`;

    elements.signalCheckboxes
        .querySelectorAll('input[type="checkbox"]')
        .forEach((checkbox) => {
            checkbox.addEventListener("change", (event) => {
                const signal = event.target.value;

                if (event.target.checked) {
                    state.selectedSignals.add(signal);
                } else {
                    state.selectedSignals.delete(signal);
                }

                render();
            });
        });
}

function getFilteredSignalMap() {
    const normalizedSearch = state.searchText
        .trim()
        .toUpperCase();

    const map = new Map();

    for (const signal of state.signals) {
        if (!state.selectedSignals.has(signal)) {
            continue;
        }

        const matchingRows = state.rows.filter((row) => {
            const rateMatches =
                state.selectedRate === "all" ||
                String(row.rate) === state.selectedRate;

            return row.signal === signal && rateMatches;
        });

        const coinMap = new Map();

        for (const row of matchingRows) {
            for (const symbol of row.symbols) {
                const symbolMatches =
                    symbol.toUpperCase().includes(normalizedSearch);

                const signalMatches =
                    signal.toUpperCase().includes(normalizedSearch);

                if (
                    normalizedSearch &&
                    !symbolMatches &&
                    !signalMatches
                ) {
                    continue;
                }

                if (!coinMap.has(symbol)) {
                    coinMap.set(symbol, new Set());
                }

                coinMap.get(symbol).add(row.rate);
            }
        }

        const coins = [...coinMap.entries()]
            .map(([symbol, rates]) => ({
                symbol,
                rates: [...rates].sort((a, b) => b - a)
            }))
            .sort((a, b) => a.symbol.localeCompare(b.symbol));

        if (coins.length > 0) {
            map.set(signal, coins);
        }
    }

    return map;
}

function renderRateFilter() {
    elements.rateFilter
        .querySelectorAll("button")
        .forEach((button) => {
            const isActive =
                button.dataset.rate === state.selectedRate;

            button.classList.toggle("btn-primary", isActive);
            button.classList.toggle("btn-outline-primary", !isActive);
        });
}

function renderTabs(signalMap) {
    const visibleSignals = [...signalMap.keys()];

    if (!visibleSignals.includes(state.activeSignal)) {
        state.activeSignal = visibleSignals[0] ?? null;
    }

    elements.signalTabs.innerHTML = visibleSignals
        .map((signal) => {
            const isActive = signal === state.activeSignal;
            const count = signalMap.get(signal).length;

            return `
                <li class="nav-item" role="presentation">
                    <button
                        type="button"
                        class="nav-link ${isActive ? "active" : ""}"
                        data-signal="${escapeHtml(signal)}"
                        title="${escapeHtml(signal)}"
                    >
                        ${escapeHtml(getSignalLabel(signal))}
                        <span class="badge text-bg-light ms-1">
                            ${count}
                        </span>
                    </button>
                </li>
            `;
        })
        .join("");

    elements.signalTabs
        .querySelectorAll("button")
        .forEach((button) => {
            button.addEventListener("click", () => {
                state.activeSignal = button.dataset.signal;
                renderResultsOnly();
            });
        });
}

function renderCoins(signalMap) {
    const coins =
        state.activeSignal &&
        signalMap.has(state.activeSignal)
            ? signalMap.get(state.activeSignal)
            : [];

    elements.coinList.innerHTML = coins
        .map((coin) => {
            const badges = coin.rates
                .map((rate) => {
                    const badgeClass =
                        rate === 100
                            ? "text-bg-primary"
                            : "text-bg-secondary";

                    return `
                        <span class="badge ${badgeClass}">
                            ${rate}
                        </span>
                    `;
                })
                .join("");

            return `
                <article class="coin-card">
                    <span
                        class="coin-card-symbol"
                        title="${escapeHtml(coin.symbol)}"
                    >
                        ${escapeHtml(coin.symbol)}
                    </span>

                    <span class="coin-card-badges">
                        ${badges}
                    </span>
                </article>
            `;
        })
        .join("");

    const hasCoins = coins.length > 0;

    elements.emptyState.classList.toggle("d-none", hasCoins);
    elements.coinList.classList.toggle("d-none", !hasCoins);

    const visibleTabCount = signalMap.size;

    const totalUniqueSymbols =
        new Set(
            [...signalMap.values()]
                .flat()
                .map((coin) => coin.symbol)
        ).size;

    const dateText = state.selectedDate
        ? `${state.selectedDate} 기준 · `
        : "";

    elements.resultSummary.textContent =
        `${dateText}${visibleTabCount}개 시그널 탭 · ${totalUniqueSymbols}개 코인 (중복 제외)`;
}

function renderResultsOnly() {
    const signalMap = getFilteredSignalMap();

    renderTabs(signalMap);
    renderCoins(signalMap);
}

function render() {
    renderDateFilter();
    renderRateFilter();
    renderSignalCheckboxes();
    renderResultsOnly();
}

// elements.dateFilter.addEventListener(
//     "change",
//     (event) => {
//         state.selectedDate = event.target.value;
//         loadSnapshot(state.selectedDate);
//     }
// );
elements.dateFilterMenu.addEventListener(
    "click",
    (event) => {
        const button = event.target.closest("button[data-date]");

        if (!button) {
            return;
        }

        state.selectedDate = button.dataset.date;
        loadSnapshot(state.selectedDate);
    }
);

elements.searchInput.addEventListener(
    "input",
    (event) => {
        state.searchText = event.target.value;
        renderResultsOnly();
    }
);

elements.rateFilter.addEventListener(
    "click",
    (event) => {
        const button = event.target.closest("button[data-rate]");

        if (!button) {
            return;
        }

        state.selectedRate = button.dataset.rate;

        renderRateFilter();
        renderResultsOnly();
    }
);

elements.selectAllButton.addEventListener(
    "click",
    () => {
        state.selectedSignals = new Set(state.signals);
        render();
    }
);

elements.clearAllButton.addEventListener(
    "click",
    () => {
        state.selectedSignals.clear();
        render();
    }
);

elements.reloadButton.addEventListener(
    "click",
    () => {
        loadSnapshot(state.selectedDate);
    }
);

render();
initializeData();