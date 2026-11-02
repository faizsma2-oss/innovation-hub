
    const authView = document.getElementById("authView");
    const dashboardView = document.getElementById("dashboardView");

    const signInTab = document.getElementById("signInTab");
    const signUpTab = document.getElementById("signUpTab");

    const signInSection = document.getElementById("signInSection");
    const signUpSection = document.getElementById("signUpSection");

    const signInForm = document.getElementById("signInForm");
    const signUpForm = document.getElementById("signUpForm");

    const signInButton = document.getElementById("signInButton");
    const signUpButton = document.getElementById("signUpButton");

    const signInMessage = document.getElementById("signInMessage");
    const signUpMessage = document.getElementById("signUpMessage");

    const logoutButton = document.getElementById("logoutButton");
    const telegramConnectButton =
      document.getElementById("telegramConnectButton");
    let dashboardUserName = "Mr. Naveed";
    const latestOverviewState = {
      reports: null,
      reportData: null,
      telegramConnected: false,
      memberImport: null,
      dashboard: null,
    };
    const overviewWatchlistState = {
      category: "needs_uid",
    };
    const rebateInsightsState = {
      data: null,
      selected: "combined",
      hiddenTrendSeries: [],
      loading: false,
    };
    const brokerReportsState = {
      data: null,
      broker: "combined",
      dataset: "member_rows",
      status: "all",
    };
    const matchedRecordsState = {
      broker: "all",
      status: "matched",
      tradeWindow: "all",
      sort: "priority",
      search: "",
      rows: [],
      visibleRows: [],
      loading: false,
    };
    let tradingRecordAssignment = null;
    const telegramMembersPageState = {
      data: null,
      search: "",
      broker: "all",
      status: "all",
      autoExtractAttempted: false,
      loading: false,
    };

    const dashboardPageCopy = {
      overview: {
        title: () => "﷽",
        description: "A little corner of love and dua for my Mahad jaan.",
      },
      uploads: {
        title: () => "Uploads",
        description: "Upload Telegram member CSVs and all broker report files from one dedicated page.",
      },
      telegram: {
        title: () => "Telegram",
        description: "Scan replies, approve UID matches and manually message exact selected recipients. Nothing sends automatically.",
      },
      "rebate-insights": {
        title: () => "Rebate Insights",
        description: "Broker rebates, trading volume, concentration and member performance from the latest imported reports.",
      },
      "matched-records": {
        title: () => "Trading Records",
        description: "Telegram members joined to Vantage and PU Prime UIDs, account activity, balances and rebate signals.",
      },
      "telegram-members": {
        title: () => "Telegram Members",
        description: "Manage every Telegram member and all linked trading UIDs in one place.",
      },
    };

    function showDashboardPage(page) {
      const requested = ["vantage", "puprime", "brokers"].includes(page) ? "matched-records" : page;
      const selected = dashboardPageCopy[requested] ? requested : "overview";
      if (window.location.hash !== `#${selected}`) {
        window.history.replaceState(null, "", `#${selected}`);
      }
      dashboardView.dataset.activePage = selected;
      dashboardView.classList.toggle("telegram-mode", selected === "telegram");
      document.querySelectorAll(".dashboard-nav-button").forEach((button) => {
        button.classList.toggle("active", button.dataset.dashboardPage === selected);
      });
      document.getElementById("topTelegramButton").classList.toggle("active", selected === "telegram");
      document.querySelectorAll("[data-content-page]").forEach((section) => {
        section.classList.toggle("dashboard-page-hidden", section.dataset.contentPage !== selected);
      });
      document.querySelectorAll("[data-feature-page]").forEach((card) => {
        card.classList.toggle("dashboard-page-hidden", card.dataset.featurePage !== selected);
      });
      const connectionGrid = document.getElementById("connectionGrid");
      connectionGrid.classList.toggle(
        "dashboard-page-hidden",
        !["telegram", "uploads"].includes(selected)
      );
      connectionGrid.classList.toggle("telegram-layout", selected === "telegram");
      connectionGrid.classList.remove("broker-layout");
      connectionGrid.classList.toggle("uploads-layout", selected === "uploads");
      document.querySelectorAll("[data-page-action]").forEach((action) => {
        const actionPage = action.dataset.pageAction;
        const visible = actionPage === selected;
        action.classList.toggle("dashboard-page-hidden", !visible);
      });
      const welcomeHeading = document.getElementById("welcomeHeading");
      welcomeHeading.textContent = dashboardPageCopy[selected].title();
      welcomeHeading.classList.toggle("bismillah-title", selected === "overview");
      document.getElementById("welcomeDescription").textContent = dashboardPageCopy[selected].description;
      if (selected === "rebate-insights") loadRebateInsights();
      if (selected === "matched-records") loadMatchedRecordsPage();
      if (selected === "telegram-members") loadTelegramMembersPage({ autoExtract: true });
      if (selected === "telegram") loadTelegramHealth();
      if (selected === "overview") {
        renderHelpfulOverview();
        loadRebateInsights();
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function showTelegramSubpage(subpage) {
      const allowed = ["overview", "links", "prompt", "activity"];
      const selected = allowed.includes(subpage) ? subpage : "overview";
      document.querySelectorAll("[data-telegram-subpage-button]").forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.telegramSubpageButton === selected
        );
      });
      document.querySelectorAll("[data-telegram-subpage]").forEach((section) => {
        section.classList.toggle(
          "telegram-subpage-hidden",
          section.dataset.telegramSubpage !== selected
        );
      });
      if (selected === "overview") loadTelegramWorkspace();
      if (selected === "activity") {
        loadReplyDirectory();
        loadReplyMatches();
        loadOutreachHistory();
      }
      if (selected === "links") loadTelegramAccountLinks();
    }

    document.querySelectorAll("[data-telegram-subpage-button]").forEach((button) => {
      button.addEventListener("click", () => {
        showTelegramSubpage(button.dataset.telegramSubpageButton);
      });
    });

    document.querySelectorAll(".dashboard-nav-button").forEach((button) => {
      button.addEventListener("click", () => showDashboardPage(button.dataset.dashboardPage));
    });

    document.getElementById("topUploadButton").addEventListener("click", () => {
      showDashboardPage("uploads");
    });

    document.getElementById("topTelegramButton").addEventListener("click", () => {
      showDashboardPage("telegram");
    });

    function setMessage(element, text, type = "") {
      element.textContent = text;
      element.className = `message ${type}`.trim();
    }

    function showSignIn() {
      signInTab.classList.add("active");
      signUpTab.classList.remove("active");
      signInSection.classList.remove("hidden");
      signUpSection.classList.add("hidden");
      setMessage(signInMessage, "");
      setMessage(signUpMessage, "");
    }

    function showSignUp() {
      signUpTab.classList.add("active");
      signInTab.classList.remove("active");
      signUpSection.classList.remove("hidden");
      signInSection.classList.add("hidden");
      setMessage(signInMessage, "");
      setMessage(signUpMessage, "");
    }

    let telegramMembershipSyncTimer = null;

    function stopTelegramMembershipSync() {
      if (!telegramMembershipSyncTimer) return;
      clearInterval(telegramMembershipSyncTimer);
      telegramMembershipSyncTimer = null;
    }

    function startTelegramMembershipSync() {
      stopTelegramMembershipSync();
      telegramMembershipSyncTimer = setInterval(() => {
        loadTelegramMemberLinks({ force: true }).catch((error) => {
          console.error("Could not synchronize Telegram membership:", error);
        });
      }, 5 * 60 * 1000);
    }

    function showDashboard(user) {
      authView.classList.add("hidden");
      dashboardView.classList.remove("hidden");

      const name = user.display_name || user.email.split("@")[0];
      dashboardUserName = "Mr. Naveed";
      showDashboardPage(window.location.hash.slice(1) || "overview");
      loadConnections();
      loadTelegramHealth();
      loadDashboard();
      loadTelegramMemberLinks().catch((error) => {
        console.error("Could not load Telegram member links:", error);
      });
      loadOutreachTemplates();
      loadTelegramWorkspace();
      loadReplyMatches();
      startTelegramMembershipSync();
    }

    function showAuthentication() {
      stopTelegramMembershipSync();
      dashboardView.classList.add("hidden");
      authView.classList.remove("hidden");
      showSignIn();
    }

    async function requestJson(url, options = {}) {
      const response = await fetch(url, {
        credentials: "include",
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });

      let body = {};

      try {
        body = await response.json();
      } catch {
        body = {};
      }

      if (!response.ok) {
        throw new Error(
          body.detail || `Request failed with status ${response.status}`
        );
      }

      return body;
    }

    signInTab.addEventListener("click", showSignIn);
    signUpTab.addEventListener("click", showSignUp);

    signUpForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      signUpButton.disabled = true;
      signUpButton.textContent = "Creating account...";
      setMessage(signUpMessage, "");

      const payload = {
        display_name:
          document.getElementById("registerName").value.trim(),
        email:
          document.getElementById("registerEmail").value.trim(),
        password:
          document.getElementById("registerPassword").value,
      };

      try {
        await requestJson("/api/auth/register", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        signUpForm.reset();

        setMessage(
          signUpMessage,
          "Check your inbox! We've sent you a verification email. Please verify your email before signing in.. Email verification is still being configured. Ask the administrator to verify this test account before signing in.",
          "success"
        );
      } catch (error) {
        setMessage(signUpMessage, error.message, "error");
      } finally {
        signUpButton.disabled = false;
        signUpButton.textContent = "Create account";
      }
    });

    signInForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      signInButton.disabled = true;
      signInButton.textContent = "Signing in...";
      setMessage(signInMessage, "");

      const payload = {
        email:
          document.getElementById("loginEmail").value.trim(),
        password:
          document.getElementById("loginPassword").value,
      };

      try {
        const user = await requestJson("/api/auth/login", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        signInForm.reset();
        showDashboard(user);
      } catch (error) {
        setMessage(signInMessage, error.message, "error");
      } finally {
        signInButton.disabled = false;
        signInButton.textContent = "Sign in";
      }
    });

    logoutButton.addEventListener("click", async () => {
      try {
        await requestJson("/api/auth/logout", {
          method: "POST",
          body: JSON.stringify({}),
        });
      } catch (error) {
        console.error(error);
      } finally {
        showAuthentication();
      }
    });

    const telegramDialog =
  document.getElementById("telegramDialog");

const telegramDialogClose =
  document.getElementById("telegramDialogClose");

const telegramPhoneStep =
  document.getElementById("telegramPhoneStep");

const telegramCodeStep =
  document.getElementById("telegramCodeStep");

const telegramPasswordStep =
  document.getElementById("telegramPasswordStep");

const telegramPhoneInput =
  document.getElementById("telegramPhoneInput");

const telegramCodeInput =
  document.getElementById("telegramCodeInput");

const telegramPasswordInput =
  document.getElementById("telegramPasswordInput");

const telegramStartButton =
  document.getElementById("telegramStartButton");

const telegramCodeButton =
  document.getElementById("telegramCodeButton");

const telegramPasswordButton =
  document.getElementById("telegramPasswordButton");

const telegramDialogMessage =
  document.getElementById("telegramDialogMessage");

const telegramAccountStatus =
  document.getElementById("telegramAccountStatus");

const telegramDisconnectButton =
  document.getElementById("telegramDisconnectButton");


async function telegramRequest(path, body) {
  return requestJson(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}


const telegramRemoteActionIds = [
  "previewRecipientsButton",
  "selectAllRecipientsButton",
  "initializeTrackingButton",
  "checkTelegramSetupButton",
  "connectAndScanRepliesButton",
  "scanTelegramAccountLinksButton",
  "scanTelegramMembersButton",
];
let telegramHealthRequest = null;
let telegramAuthorizationVerified = false;


function applyTelegramConnectionState(status, message = "", options = {}) {
  const authorized = status === "connected" && options.verified === true;
  telegramAuthorizationVerified = authorized;
  latestOverviewState.telegramConnected = authorized;
  updateConnectionStatus("telegramStatus", status);
  telegramConnectButton.querySelector("span").textContent = authorized
    ? "Reconnect"
    : "Connect";
  telegramDisconnectButton.disabled = ["not_connected", "disconnected"].includes(status);
  telegramRemoteActionIds.forEach((id) => {
    document.getElementById(id).disabled = !authorized;
  });
  if (!authorized) {
    resetSendConfirmation();
    document.getElementById("sendOutreachButton").disabled = true;
  }
  if (message) telegramAccountStatus.textContent = message;
  renderTelegramWorkspace();
  renderHelpfulOverview();
}


async function loadTelegramHealth() {
  if (telegramHealthRequest) return telegramHealthRequest;
  telegramAuthorizationVerified = false;
  latestOverviewState.telegramConnected = false;
  telegramAccountStatus.textContent = "Checking Telegram authorization…";
  telegramRemoteActionIds.forEach((id) => {
    document.getElementById(id).disabled = true;
  });
  telegramHealthRequest = requestJson("/api/connections/telegram/health", { method: "GET" })
    .then((result) => {
      applyTelegramConnectionState(result.status, result.message, { verified: true });
      return result;
    })
    .catch((error) => {
      applyTelegramConnectionState("error", error.message);
      return { status: "error", authorized: false, message: error.message };
    })
    .finally(() => {
      telegramHealthRequest = null;
    });
  return telegramHealthRequest;
}


function refreshTelegramHealthForAuthorizationError(error) {
  if (/reconnect telegram|session has expired|authorized telegram session/i.test(error.message)) {
    loadTelegramHealth();
  }
}


function showTelegramStep(step) {
  telegramPhoneStep.hidden = step !== "phone";
  telegramCodeStep.hidden = step !== "code";
  telegramPasswordStep.hidden = step !== "password";
}


function resetTelegramDialog() {
  telegramPhoneInput.value = "";
  telegramCodeInput.value = "";
  telegramPasswordInput.value = "";
  telegramDialogMessage.textContent = "";
  showTelegramStep("phone");
}


telegramConnectButton.disabled = false;

telegramConnectButton.addEventListener("click", () => {
  resetTelegramDialog();
  telegramDialog.showModal();
});


telegramDialogClose.addEventListener("click", () => {
  telegramDialog.close();
});


telegramStartButton.addEventListener("click", async () => {
  const phoneNumber = telegramPhoneInput.value.trim();

  if (!phoneNumber.startsWith("+")) {
    telegramDialogMessage.textContent =
      "Include the country code, for example +971501234567.";
    return;
  }

  telegramStartButton.disabled = true;
  telegramDialogMessage.textContent = "Requesting Telegram code...";

  try {
    const result = await telegramRequest(
      "/api/connections/telegram/start",
      {
        phone_number: phoneNumber,
      }
    );

    telegramDialogMessage.textContent = result.message;
    applyTelegramConnectionState("pending", result.message);
    showTelegramStep("code");
    telegramCodeInput.focus();
  } catch (error) {
    telegramDialogMessage.textContent = error.message;
  } finally {
    telegramStartButton.disabled = false;
  }
});


telegramCodeButton.addEventListener("click", async () => {
  const code = telegramCodeInput.value.trim();

  if (!code) {
    telegramDialogMessage.textContent =
      "Enter the newest code sent by Telegram.";
    return;
  }

  telegramCodeButton.disabled = true;
  telegramDialogMessage.textContent = "Verifying code...";

  try {
    const result = await telegramRequest(
      "/api/connections/telegram/verify-code",
      {
        code,
      }
    );

    if (result.requires_password) {
      telegramDialogMessage.textContent = result.message;
      applyTelegramConnectionState("pending_password", result.message);
      showTelegramStep("password");
      telegramPasswordInput.focus();
      return;
    }

    telegramDialogMessage.textContent =
      "Telegram connected successfully.";

    await loadConnections();
    await loadTelegramHealth();

    setTimeout(() => {
      telegramDialog.close();
    }, 1200);
  } catch (error) {
    telegramDialogMessage.textContent = error.message;
  } finally {
    telegramCodeButton.disabled = false;
  }
});


telegramPasswordButton.addEventListener(
  "click",
  async () => {
    const password = telegramPasswordInput.value;

    if (!password) {
      telegramDialogMessage.textContent =
        "Enter your Telegram two-step-verification password.";
      return;
    }

    telegramPasswordButton.disabled = true;
    telegramDialogMessage.textContent =
      "Completing Telegram connection...";

    try {
      const result = await telegramRequest(
        "/api/connections/telegram/verify-password",
        {
          password,
        }
      );

      telegramPasswordInput.value = "";
      telegramDialogMessage.textContent = result.message;

      await loadConnections();
      await loadTelegramHealth();

      setTimeout(() => {
        telegramDialog.close();
      }, 1200);
    } catch (error) {
      telegramPasswordInput.value = "";
      telegramDialogMessage.textContent = error.message;
    } finally {
      telegramPasswordButton.disabled = false;
    }
  }
);

for (const [input, button] of [
  [telegramPhoneInput, telegramStartButton],
  [telegramCodeInput, telegramCodeButton],
  [telegramPasswordInput, telegramPasswordButton],
]) {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      button.click();
    }
  });
}

telegramDisconnectButton.addEventListener("click", async () => {
  if (!window.confirm("Disconnect Telegram from MahadSpace? No messages will be sent.")) return;
  telegramDisconnectButton.disabled = true;
  telegramAccountStatus.textContent = "Disconnecting Telegram…";
  try {
    const result = await requestJson("/api/connections/telegram", { method: "DELETE" });
    telegramDiagnostics = null;
    applyTelegramConnectionState(result.status, result.message);
    renderRecipientPreview([]);
    document.getElementById("outreachStatus").textContent = result.message;
    await loadTelegramWorkspace();
  } catch (error) {
    telegramAccountStatus.textContent = error.message;
  } finally {
    await loadConnections();
  }
});

async function loadConnections() {
  try {
    const connections = await requestJson("/api/connections", {
      method: "GET",
    });

    applyTelegramConnectionState(connections.telegram.status);

    const reports = await requestJson("/api/reports/status", { method: "GET" });
    latestOverviewState.reports = reports;
    updateConnectionStatus("vantageIbAccountReportStatus", reports.vantage.ib_account_report_status);
    updateConnectionStatus("vantageRebateStatus", reports.vantage.datasets.rebates.status);
    updateConnectionStatus("puprimeIbAccountReportStatus", reports.puprime.ib_account_report_status);
    updateConnectionStatus("puprimeRebateStatus", reports.puprime.datasets.rebates.status);
    for (const broker of ["vantage", "puprime"]) {
      const brokerReport = reports[broker];
      const ibAccountReportPresent = ["accounts", "funds", "opened_accounts"].some(
        (dataset) => brokerReport.datasets[dataset]?.status === "manual_report"
      );
      document.getElementById(`${queueKey(broker, "ib_account_report")}RemoveData`).disabled = !ibAccountReportPresent;
      document.getElementById(`${queueKey(broker, "rebate")}RemoveData`).disabled =
        brokerReport.datasets.rebates?.status !== "manual_report";
    }
    const memberImport = await requestJson("/api/telegram/members/import", { method: "GET" });
    latestOverviewState.memberImport = memberImport;
    const memberImportStatus = document.getElementById("telegramMemberImportStatus");
    const memberImportRemove = document.getElementById("telegramMemberRemove");
    memberImportStatus.textContent = memberImport.present
      ? `${memberImport.member_count} members · ${memberImport.filename}`
      : "No member CSV imported";
    memberImportStatus.classList.toggle("connected", memberImport.present);
    memberImportRemove.disabled = !memberImport.present;
    renderHelpfulOverview();
  } catch (error) {
    console.error("Could not load connections:", error);
  }
}


function updateConnectionStatus(elementId, status) {
  const element = document.getElementById(elementId);

  const labels = {
    not_connected: "Not connected",
    pending: "Connection pending",
    connected: "Connected",
    configured: "Configured — ready to sync",
    manual_report: "Manual report imported",
    not_imported: "No report imported",
    error: "Connection error",
    expired: "Connection expired",
    revoked: "Connection revoked",
    disconnected: "Disconnected",
  };

  element.textContent = labels[status] || status;
  element.classList.toggle("connected", status === "connected" || status === "manual_report");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value || 0));
}

const gridStates = {};

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function dataCellClass(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "active") return "status-active";
  if (normalized === "inactive") return "status-inactive";
  return "";
}

function renderDataGrid(targetId, rows, emptyText = "No rows imported yet.", options = {}) {
  const target = document.getElementById(targetId);
  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    gridStates[targetId] = { rows: [], filtered: [], columns: [] };
    return;
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const previous = gridStates[targetId] || {};
  const state = {
    rows,
    columns,
    query: previous.query || "",
    filters: previous.filters || {},
    sortColumn: previous.sortColumn || "",
    sortDirection: previous.sortDirection || "asc",
    showAll: previous.showAll || false,
    filtered: [],
  };
  gridStates[targetId] = state;

  const draw = (restoreFocus = null) => {
    const keyColumnNames = new Set([
      "telegram member", "uids", "uid owner", "match status",
      "broker", "user id", "uid", "account", "account id", "account_id",
      "name", "client name", "client_name", "balance", "account equity",
      "equity", "last trade date", "last_trade_date", "last deposit date",
    "last_deposit_date", "calculated status", "status", "account count",
      "account ids", "total balance", "total equity", "broker report name",
      "fund rows", "opened account rows", "rebate rows", "total rebate",
      "account types", "campaigns", "instruments",
    ]);
    let visibleColumns = state.showAll
      ? state.columns
      : state.columns.filter((column) =>
          keyColumnNames.has(column.toLowerCase().replaceAll("_", " "))
          || keyColumnNames.has(column.toLowerCase())
        );
    if (!visibleColumns.length || state.columns.length <= 10) {
      visibleColumns = state.columns;
    }
    const query = state.query.toLowerCase();
    let filtered = state.rows.filter((row) => {
      const globalMatch = !query || state.columns.some((column) =>
        String(row[column] ?? "").toLowerCase().includes(query)
      );
      const columnMatch = state.columns.every((column) => {
        const filter = String(state.filters[column] || "").toLowerCase();
        return !filter || String(row[column] ?? "").toLowerCase().includes(filter);
      });
      return globalMatch && columnMatch;
    });
    if (state.sortColumn) {
      const column = state.sortColumn;
      const direction = state.sortDirection === "asc" ? 1 : -1;
      filtered = [...filtered].sort((a, b) => {
        const av = a[column] ?? "";
        const bv = b[column] ?? "";
        const an = Number(av);
        const bn = Number(bv);
        if (String(av).trim() !== "" && String(bv).trim() !== "" && Number.isFinite(an) && Number.isFinite(bn)) {
          return (an - bn) * direction;
        }
        return String(av).localeCompare(String(bv), undefined, { numeric: true }) * direction;
      });
    }
    state.filtered = filtered;
    const headerTitles = visibleColumns.map((column, index) => {
      const arrow = state.sortColumn === column ? (state.sortDirection === "asc" ? " ↑" : " ↓") : "";
      return `<th><button class="sort-button" type="button" data-sort-index="${index}">${escapeHtml(column)}${arrow}</button></th>`;
    }).join("");
    const headerFilters = options.compact ? "" : visibleColumns.map((column, index) => {
      return `<th><input class="column-filter" data-filter-index="${index}" value="${escapeHtml(state.filters[column] || "")}" placeholder="Filter ${escapeHtml(column)}…"></th>`;
    }).join("");
    const body = filtered.map((row) => `<tr>${visibleColumns.map((column) =>
      `<td class="${dataCellClass(row[column])}">${escapeHtml(row[column] ?? "—")}</td>`
    ).join("")}</tr>`).join("");
    target.innerHTML = `
      <div class="grid-toolbar">
        <input class="global-filter" value="${escapeHtml(state.query)}" placeholder="Search this view…">
        <span class="grid-count">${filtered.length} of ${state.rows.length} rows</span>
        ${visibleColumns.length < state.columns.length || state.showAll ? `<button class="toggle-columns" type="button">${state.showAll ? "Key columns" : `All ${state.columns.length} columns`}</button>` : ""}
        ${options.compact ? "" : '<button class="clear-grid" type="button">Clear filters</button>'}
        <button class="export-grid" type="button">Export filtered CSV</button>
      </div>
      <div class="table-wrap"><table>
        <thead><tr>${headerTitles}</tr>${headerFilters ? `<tr>${headerFilters}</tr>` : ""}</thead>
        <tbody>${body || `<tr><td colspan="${visibleColumns.length}">No matching rows.</td></tr>`}</tbody>
      </table></div>`;

    target.querySelector(".global-filter").addEventListener("input", (event) => {
      const input = event.currentTarget;
      state.query = input.value;
      draw({
        type: "global",
        start: input.selectionStart ?? input.value.length,
        end: input.selectionEnd ?? input.value.length,
      });
    });
    target.querySelectorAll("[data-filter-index]").forEach((input) => {
      input.addEventListener("input", (event) => {
        const currentInput = event.currentTarget;
        const filterIndex = currentInput.dataset.filterIndex;
        const column = visibleColumns[Number(filterIndex)];
        state.filters[column] = currentInput.value;
        draw({
          type: "column",
          filterIndex,
          start: currentInput.selectionStart ?? currentInput.value.length,
          end: currentInput.selectionEnd ?? currentInput.value.length,
        });
      });
    });
    target.querySelectorAll("[data-sort-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const column = visibleColumns[Number(button.dataset.sortIndex)];
        if (state.sortColumn === column) {
          state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
        } else {
          state.sortColumn = column;
          state.sortDirection = "asc";
        }
        draw();
      });
    });
    const clearGridButton = target.querySelector(".clear-grid");
    if (clearGridButton) {
      clearGridButton.addEventListener("click", () => {
        state.query = "";
        state.filters = {};
        state.sortColumn = "";
        draw();
      });
    }
    const toggleColumnsButton = target.querySelector(".toggle-columns");
    if (toggleColumnsButton) {
      toggleColumnsButton.addEventListener("click", () => {
        state.showAll = !state.showAll;
        draw();
      });
    }
    target.querySelector(".export-grid").addEventListener("click", () => {
      const csv = [
        state.columns.map(csvCell).join(","),
        ...state.filtered.map((row) => state.columns.map((column) => csvCell(row[column])).join(",")),
      ].join("\n");
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      link.download = `${targetId}_filtered.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    });

    if (restoreFocus) {
      const replacement = restoreFocus.type === "global"
        ? target.querySelector(".global-filter")
        : target.querySelector(`[data-filter-index="${restoreFocus.filterIndex}"]`);
      if (replacement) {
        replacement.focus({ preventScroll: true });
        replacement.setSelectionRange(
          Math.min(restoreFocus.start, replacement.value.length),
          Math.min(restoreFocus.end, replacement.value.length)
        );
      }
    }
  };
  draw();
}

function field(row, ...names) {
  for (const name of names) {
    if (row[name] !== undefined && row[name] !== null) return row[name];
  }
  return "";
}

const brokerDatasetMeta = {
  member_rows: {
    title: "Members",
    noun: "members",
    empty: "No members are available for this selection.",
  },
  account_rows: {
    title: "Account details",
    noun: "accounts",
    empty: "No account details are available for this selection.",
  },
  funds: {
    title: "Fund transactions",
    noun: "records",
    empty: "No fund transactions are available for this selection.",
  },
  opened_accounts: {
    title: "Opened accounts",
    noun: "accounts",
    empty: "No opened-account records are available for this selection.",
  },
  rebates: {
    title: "Rebate report rows",
    noun: "rows",
    empty: "No rebate report rows are available for this selection.",
  },
};

function brokerRowStatus(row) {
  return String(field(row, "Calculated Status", "Status", "status") || "").toLowerCase();
}

function sortBrokerRows(rows, dataset) {
  return [...rows].sort((a, b) => {
    if (["member_rows", "account_rows"].includes(dataset)) {
      const statusDifference = (brokerRowStatus(a) === "active" ? 0 : 1)
        - (brokerRowStatus(b) === "active" ? 0 : 1);
      if (statusDifference) return statusDifference;
    }
    if (dataset === "rebates") {
      const aDate = Date.parse(field(a, "Date", "Day", "Transaction Date") || "") || 0;
      const bDate = Date.parse(field(b, "Date", "Day", "Transaction Date") || "") || 0;
      if (aDate !== bDate) return bDate - aDate;
    }
    const aName = String(field(a, "Name", "Client Name", "client_name") || "");
    const bName = String(field(b, "Name", "Client Name", "client_name") || "");
    const nameDifference = aName.localeCompare(bName, undefined, { numeric: true });
    if (nameDifference) return nameDifference;
    const aIdentifier = String(field(a, "User ID", "uid", "Account", "Account ID", "account_id") || "");
    const bIdentifier = String(field(b, "User ID", "uid", "Account", "Account ID", "account_id") || "");
    return aIdentifier.localeCompare(bIdentifier, undefined, { numeric: true });
  });
}

function renderBrokerReports() {
  const reports = brokerReportsState.data;
  if (!reports) return;
  const data = reports[brokerReportsState.broker] || reports.combined || {};
  const members = data.member_rows || [];
  const active = members.filter((row) => brokerRowStatus(row) === "active").length;
  const inactive = members.length - active;

  document.getElementById("brokerSummaryMembers").textContent = members.length.toLocaleString();
  document.getElementById("brokerSummaryActive").textContent = active.toLocaleString();
  document.getElementById("brokerSummaryInactive").textContent = inactive.toLocaleString();
  document.getElementById("brokerSummaryAccounts").textContent = (data.account_rows || []).length.toLocaleString();
  const totalBalance = members.reduce(
    (sum, row) => sum + Number(field(row, "Total Balance", "balance") || 0),
    0
  );
  document.getElementById("brokerSummaryBalance").textContent = formatCompactMoney(totalBalance);
  document.getElementById("brokerSummaryRebates").textContent = (data.rebates || []).length.toLocaleString();

  const dataset = brokerReportsState.dataset;
  const meta = brokerDatasetMeta[dataset];
  const supportsStatus = ["member_rows", "account_rows"].includes(dataset);
  document.getElementById("brokerReportStatusField").classList.toggle("hidden", !supportsStatus);

  let rows = data[dataset] || [];
  if (supportsStatus && brokerReportsState.status !== "all") {
    rows = rows.filter((row) => brokerRowStatus(row) === brokerReportsState.status);
  }
  rows = sortBrokerRows(rows, dataset);

  const brokerLabels = {
    combined: "All brokers",
    vantage: "Vantage",
    puprime: "PU Prime",
  };
  document.getElementById("brokerReportScope").textContent = brokerLabels[brokerReportsState.broker];
  document.getElementById("brokerReportTitle").textContent = meta.title;
  document.getElementById("brokerReportCount").textContent = `${rows.length.toLocaleString()} ${meta.noun}`;
  renderDataGrid("brokerReportTable", rows, meta.empty, { compact: true });
}

function updateBrokerReportSelection(control) {
  brokerReportsState[control === "brokerReportBroker" ? "broker" : control === "brokerReportDataset" ? "dataset" : "status"] =
    document.getElementById(control).value;
  delete gridStates.brokerReportTable;
  renderBrokerReports();
}

document.getElementById("brokerReportBroker").addEventListener("change", () => updateBrokerReportSelection("brokerReportBroker"));
document.getElementById("brokerReportDataset").addEventListener("change", () => updateBrokerReportSelection("brokerReportDataset"));
document.getElementById("brokerReportStatus").addEventListener("change", () => updateBrokerReportSelection("brokerReportStatus"));

async function loadReportData() {
  const reports = await requestJson("/api/reports/data", { method: "GET" });
  brokerReportsState.data = reports;
  latestOverviewState.reportData = reports;
  renderBrokerReports();
  if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
  renderHelpfulOverview();
}

function headerToken(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function rowField(row, aliases) {
  const byToken = Object.fromEntries(
    Object.entries(row || {}).map(([key, value]) => [headerToken(key), value])
  );
  for (const alias of aliases) {
    const token = headerToken(alias);
    if (byToken[token] !== undefined && byToken[token] !== null) return byToken[token];
  }
  return "";
}

function numericRowField(row, aliases) {
  const value = rowField(row, aliases);
  if (value === null || value === undefined || String(value).trim() === "") return 0;
  const cleaned = String(value).replaceAll(",", "").replace("$", "").replace("USD", "").trim();
  const bracketed = cleaned.startsWith("(") && cleaned.endsWith(")");
  const number = Number(bracketed ? `-${cleaned.slice(1, -1)}` : cleaned);
  return Number.isFinite(number) ? number : 0;
}

function normalizedUid(value) {
  return String(value || "").trim().replace(/\s+/g, "");
}

function normalizedBroker(value) {
  const compact = String(value || "").trim().toLowerCase().replace(/[\s_-]/g, "");
  if (compact === "vantage") return "Vantage";
  if (compact === "puprime" || compact === "pu") return "PU Prime";
  return "";
}

function brokerKey(broker, uid) {
  const cleanBroker = normalizedBroker(broker);
  const cleanUid = normalizedUid(uid);
  return cleanBroker && cleanUid ? `${cleanBroker}::${cleanUid}` : "";
}

function maxDateValue(values) {
  const dates = values
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .sort();
  return dates.length ? dates[dates.length - 1] : "";
}

function joinUnique(values) {
  return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .join(", ");
}

function pushIndexedRow(index, row, dataset) {
  const uid = normalizedUid(rowField(row, [
    "User ID", "uid", "user_id", "client uid", "client_uid", "client id", "customer_id",
  ]));
  const broker = normalizedBroker(rowField(row, ["Broker", "broker"]));
  const key = brokerKey(broker, uid);
  if (!key) return;
  const bucket = index[dataset].get(key) || [];
  bucket.push(row);
  index[dataset].set(key, bucket);
}

function buildBrokerRecordIndex(reports) {
  const index = {
    accountRows: new Map(),
    parsedAccounts: new Map(),
    funds: new Map(),
    openedAccounts: new Map(),
    rebates: new Map(),
  };
  const combined = reports?.combined || {};
  for (const row of combined.account_rows || []) pushIndexedRow(index, row, "accountRows");
  for (const row of combined.accounts || []) pushIndexedRow(index, row, "parsedAccounts");
  for (const row of combined.funds || []) pushIndexedRow(index, row, "funds");
  for (const row of combined.opened_accounts || []) pushIndexedRow(index, row, "openedAccounts");
  for (const row of combined.rebates || []) pushIndexedRow(index, row, "rebates");
  return index;
}

function matchedMemberLabel(member) {
  const username = member.username ? `@${String(member.username).replace(/^@/, "")}` : "";
  return [
    member.display_name || "Unknown",
    username,
    member.telegram_id ? `ID ${member.telegram_id}` : "",
  ].filter(Boolean).join(" · ");
}

function accountRowsForKey(index, key) {
  const rawRows = index.accountRows.get(key) || [];
  return rawRows.length ? rawRows : (index.parsedAccounts.get(key) || []);
}

function brokerUidRecord(member, link, index, override = {}) {
  const broker = normalizedBroker(override.broker || link?.broker || canonicalTelegramLinkBroker(link || {}));
  const uid = normalizedUid(override.uid || link?.uid);
  const key = brokerKey(broker, uid);
  const accountRows = key ? accountRowsForKey(index, key) : [];
  const parsedRows = key ? (index.parsedAccounts.get(key) || []) : [];
  const fundRows = key ? (index.funds.get(key) || []) : [];
  const openedRows = key ? (index.openedAccounts.get(key) || []) : [];
  const rebateRows = key ? (index.rebates.get(key) || []) : [];
  const accountSourceRows = accountRows.length ? accountRows : parsedRows;
  const anyReportRows = accountRows.length || parsedRows.length || fundRows.length || openedRows.length || rebateRows.length;
  const knownFromHistory = Boolean(
    !anyReportRows
    && link
    && (link.known_from_history || (link.present_in_reports && !link.present_in_current_reports))
  );
  const reportNames = joinUnique([
    ...(link?.report_names || []),
    ...accountSourceRows.map((row) => rowField(row, ["Name", "Client Name", "client_name", "Full Name"])),
    ...rebateRows.map((row) => rowField(row, ["Name", "Client Name"])),
  ]);
  const linkedCurrentAccountIds = Array.isArray(link?.current_account_ids)
    ? link.current_account_ids
    : link?.present_in_current_reports ? (link?.account_ids || []) : [];
  const accountIds = joinUnique([
    ...linkedCurrentAccountIds,
    ...accountSourceRows.map((row) => rowField(row, ["Account", "Account ID", "account_id", "Login", "login_id"])),
    ...openedRows.map((row) => rowField(row, ["Account", "Account ID", "account_id", "Login"])),
    ...rebateRows.map((row) => rowField(row, ["Account", "Account ID", "Login"])),
  ]);
  const statusValues = accountSourceRows.map((row) =>
    String(rowField(row, ["Calculated Status", "Status", "status"]) || "").toLowerCase()
  );
  const accountStatus = statusValues.includes("active")
    ? "Active"
    : statusValues.includes("inactive") ? "Inactive" : knownFromHistory ? "Not in latest report" : "";
  const balanceRows = accountSourceRows.length ? accountSourceRows : [{ "Total Balance": link?.total_balance || 0 }];
  const totalBalance = balanceRows.reduce((sum, row) => sum + numericRowField(row, [
    "Total Balance", "Balance", "Available Balance", "balance", "account_balance",
  ]), 0);
  const totalEquity = accountSourceRows.reduce((sum, row) => sum + numericRowField(row, [
    "Total Equity", "Account Equity", "Equity", "equity", "current_equity",
  ]), 0);
  const deposits = fundRows.reduce((sum, row) => sum + numericRowField(row, ["Deposits", "Deposit", "Total Deposits"]), 0);
  const withdrawals = fundRows.reduce((sum, row) => sum + numericRowField(row, ["Withdraw", "Withdrawals", "Withdrawal"]), 0);
  const netDeposits = fundRows.reduce((sum, row) => sum + numericRowField(row, ["Net Deposits", "Net Deposit", "Net"]), 0);
  const detailRebateRows = rebateRows.filter((row) => rowField(row, ["Rebate(USD)", "Rebate USD", "Rebate"]));
  const rebateSourceRows = detailRebateRows.length ? detailRebateRows : rebateRows;
  const totalRebate = rebateSourceRows.reduce((sum, row) => sum + numericRowField(row, [
    "Rebate(USD)", "Rebate USD", "Rebate", "Total RebateUSD", "Total Rebate",
  ]), 0);
  const notional = rebateSourceRows.reduce((sum, row) => sum + numericRowField(row, [
    "Notional ValueUSD", "Notional Value", "Notional",
  ]), 0);
  const lots = rebateSourceRows.reduce((sum, row) => sum + numericRowField(row, [
    "Total Volume", "Total Lots", "Lots", "Volume",
  ]), 0);
  const accountDetails = new Map();
  const ensureAccountDetail = (row, source, indexValue) => {
    const accountId = normalizedUid(rowField(row, ["Account", "Account ID", "account_id", "Login", "login_id"]));
    const detailKey = accountId || `${uid}:${source}:${indexValue}`;
    const statusValue = String(rowField(row, ["Calculated Status", "Status", "status"]) || "").toLowerCase();
    const existing = accountDetails.get(detailKey) || {
      "Account Number": accountId,
      UID: uid,
      Broker: broker,
      Sources: [],
      "Client Name": "",
      Balance: 0,
      Equity: 0,
      "Last Trade Date": "",
      "Last Deposit Date": "",
      Status: "Unknown",
      "Total Rebate": 0,
      "Total Lots": 0,
      "Notional Value": 0,
      "Latest Rebate Date": "",
      "Account Types": [],
      Campaigns: [],
      Instruments: [],
    };
    if (!existing.Sources.includes(source)) existing.Sources.push(source);
    existing["Client Name"] = existing["Client Name"] || String(rowField(row, ["Name", "Client Name", "client_name", "Full Name"]) || "");
    if (source === "IB account") {
      existing.Balance = numericRowField(row, ["Balance", "Total Balance", "Available Balance", "balance"]);
      existing.Equity = numericRowField(row, ["Account Equity", "Equity", "Total Equity", "equity"]);
      existing["Last Trade Date"] = String(rowField(row, ["Last Trade Date", "last_trade_date", "Last Activity"]) || "");
      existing["Last Deposit Date"] = String(rowField(row, ["Last Deposit Date", "last_deposit_date", "Deposit Date"]) || "");
      existing.Status = statusValue === "active" ? "Active" : statusValue === "inactive" ? "Inactive" : "Unknown";
    } else if (source === "Opened account" && !existing.Balance) {
      existing.Balance = numericRowField(row, ["Available Balance", "Balance", "balance"]);
    }
    if (source === "Rebate") {
      existing["Total Rebate"] += numericRowField(row, ["Rebate(USD)", "Rebate USD", "Rebate", "Total RebateUSD", "Total Rebate"]);
      existing["Total Lots"] += numericRowField(row, ["Total Volume", "Total Lots", "Lots", "Volume"]);
      existing["Notional Value"] += numericRowField(row, ["Notional ValueUSD", "Notional Value", "Notional"]);
      existing["Latest Rebate Date"] = maxDateValue([
        existing["Latest Rebate Date"],
        rowField(row, ["Date", "Day", "Transaction Date"]),
      ]);
      const appendUnique = (fieldName, value) => {
        const cleanValue = String(value || "").trim();
        if (cleanValue && !existing[fieldName].includes(cleanValue)) existing[fieldName].push(cleanValue);
      };
      appendUnique("Account Types", rowField(row, ["Account Type", "Type"]));
      appendUnique("Campaigns", rowField(row, ["Campaign source", "Campaign", "Source"]));
      appendUnique("Instruments", rowField(row, ["Instrument", "Symbol"]));
    }
    accountDetails.set(detailKey, existing);
  };
  accountSourceRows.forEach((row, rowIndex) => ensureAccountDetail(row, "IB account", rowIndex));
  openedRows.forEach((row, rowIndex) => ensureAccountDetail(row, "Opened account", rowIndex));
  rebateRows.forEach((row, rowIndex) => ensureAccountDetail(row, "Rebate", rowIndex));
  const accountDetailRows = [...accountDetails.values()].sort((a, b) => {
    const statusDifference = ({ Active: 0, Inactive: 1, Unknown: 2 }[a.Status] ?? 3)
      - ({ Active: 0, Inactive: 1, Unknown: 2 }[b.Status] ?? 3);
    return statusDifference || String(a["Account Number"]).localeCompare(String(b["Account Number"]), undefined, { numeric: true });
  });
  const telegramName = override.telegramMember || (member ? matchedMemberLabel(member) : "No Telegram member");
  const matchStatus = override.matchStatus || (
    anyReportRows ? "Matched" : knownFromHistory ? "Known from report history" : "UID missing in report data"
  );
  return {
    "Telegram Member": telegramName,
    "UIDs": uid,
    "Broker": broker || "Broker needed",
    "Match Status": matchStatus,
    "Broker Report Name": reportNames || "Not in report data",
    "Account IDs": accountIds,
    "Account Count": accountIds
      ? accountIds.split(", ").length
      : Number(link?.current_account_count || accountSourceRows.length || 0),
    "Account Details": accountDetailRows,
    "Account Status": accountStatus || "Unknown",
    "Total Balance": Number(totalBalance.toFixed(2)),
    "Total Equity": Number(totalEquity.toFixed(2)),
    "Last Deposit Date": maxDateValue(accountSourceRows.map((row) => rowField(row, ["Last Deposit Date", "last_deposit_date", "Deposit Date"]))),
    "Last Trade Date": maxDateValue(accountSourceRows.map((row) => rowField(row, ["Last Trade Date", "last_trade_date", "Last Activity"]))),
    "Broker Account Rows": accountRows.length,
    "Fund Rows": fundRows.length,
    "Deposits": Number(deposits.toFixed(2)),
    "Withdrawals": Number(withdrawals.toFixed(2)),
    "Net Deposits": Number(netDeposits.toFixed(2)),
    "Opened Account Rows": openedRows.length,
    "Rebate Rows": rebateRows.length,
    "Total Rebate": Number(totalRebate.toFixed(2)),
    "Notional Value": Number(notional.toFixed(2)),
    "Total Lots": Number(lots.toFixed(2)),
    "Latest Rebate Date": maxDateValue(rebateRows.map((row) => rowField(row, ["Date", "Day", "Transaction Date"]))),
    "Account Types": joinUnique(rebateRows.map((row) => rowField(row, ["Account Type", "Type"]))),
    "Campaigns": joinUnique(rebateRows.map((row) => rowField(row, ["Campaign source", "Campaign", "Source"]))),
    "Instruments": joinUnique(rebateRows.map((row) => rowField(row, ["Instrument", "Symbol"]))),
    "Telegram Username": member?.username ? `@${String(member.username).replace(/^@/, "")}` : "",
    "Telegram ID": member?.telegram_id || "",
    "Telegram Groups": (member?.groups || []).map((group) => group === "vip" ? "VIP" : "Discussion").join(" + "),
    "Current Match Status": member?.current_match_status || (
      anyReportRows ? "matched" : knownFromHistory ? "historical_only" : "uid_not_in_reports"
    ),
  };
}

function buildMatchedUidRecords() {
  const reports = brokerReportsState.data;
  const directory = telegramMemberDirectory();
  const index = buildBrokerRecordIndex(reports);
  const rows = [];
  const linkedKeys = new Set();
  for (const member of directory.members || []) {
    for (const link of member.links || []) {
      const broker = normalizedBroker(link.broker || canonicalTelegramLinkBroker(link));
      const uid = normalizedUid(link.uid);
      const key = brokerKey(broker, uid);
      if (key) linkedKeys.add(key);
      rows.push(brokerUidRecord(member, link, index));
    }
  }
  const reportKeys = new Set([
    ...index.accountRows.keys(),
    ...index.parsedAccounts.keys(),
  ]);
  for (const key of reportKeys) {
    if (linkedKeys.has(key)) continue;
    const [broker, uid] = key.split("::");
    rows.push(brokerUidRecord(null, { uid, broker }, index, {
      uid,
      broker,
      telegramMember: "No Telegram member",
      matchStatus: "No Telegram link",
    }));
  }
  return rows;
}

function splitTradingValues(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function combineMemberTradingRecords(member, records) {
  const statuses = new Set(records.map((row) => row["Match Status"]));
  const backendActivity = String(member?.activity_status || "").toLowerCase();
  const accountStatus = backendActivity === "active"
    ? "Active"
    : backendActivity === "inactive"
      ? "Inactive"
      : records.some((row) => row["Account Status"] === "Active")
        ? "Active"
        : records.some((row) => row["Account Status"] === "Inactive")
          ? "Inactive"
          : records.some((row) => row["Account Status"] === "Not in latest report")
            ? "Not in latest report"
            : "Unknown";
  const matchStatus = statuses.has("UID missing in report data")
    ? "UID missing in report data"
    : statuses.has("Matched")
      ? "Matched"
      : statuses.has("Known from report history")
        ? "Known from report history"
        : "No Telegram link";
  const brokers = [...new Set(records.map((row) => normalizedBroker(row.Broker)).filter(Boolean))];
  const accountIds = [...new Set(records.flatMap((row) => splitTradingValues(row["Account IDs"])))];
  const accountDetailMap = new Map();
  for (const detail of records.flatMap((row) => row["Account Details"] || [])) {
    const key = [detail.Broker, detail.UID, detail["Account Number"]].join("::");
    accountDetailMap.set(key, detail);
  }
  const accountDetails = [...accountDetailMap.values()].sort((a, b) => {
    const statusDifference = ({ Active: 0, Inactive: 1, Unknown: 2 }[a.Status] ?? 3)
      - ({ Active: 0, Inactive: 1, Unknown: 2 }[b.Status] ?? 3);
    return statusDifference || String(a["Account Number"]).localeCompare(String(b["Account Number"]), undefined, { numeric: true });
  });
  const sum = (fieldName) => records.reduce((total, row) => total + Number(row[fieldName] || 0), 0);
  const first = records[0] || {};
  return {
    ...first,
    "Telegram Member": member ? (member.display_name || "Unknown") : first["Telegram Member"],
    "UIDs": joinUnique(records.map((row) => row.UIDs)),
    "UID Details": records,
    "Linked UID Count": records.length,
    "Broker": brokers.join(" + ") || first.Broker || "Broker needed",
    "Brokers": brokers,
    "Match Status": matchStatus,
    "Broker Report Name": joinUnique(records.map((row) => row["Broker Report Name"])),
    "Account IDs": accountIds.join(", "),
    "Account Count": accountDetails.length || accountIds.length || sum("Account Count"),
    "Account Details": accountDetails,
    "Active Account Count": Number(member?.active_account_count ?? accountDetails.filter((detail) => detail.Status === "Active").length),
    "Inactive Account Count": Number(member?.inactive_account_count ?? accountDetails.filter((detail) => detail.Status === "Inactive").length),
    "Account Status": accountStatus,
    "Total Balance": Number(sum("Total Balance").toFixed(2)),
    "Total Equity": Number(sum("Total Equity").toFixed(2)),
    "Last Deposit Date": maxDateValue(records.map((row) => row["Last Deposit Date"])),
    "Last Trade Date": maxDateValue(records.map((row) => row["Last Trade Date"])),
    "Broker Account Rows": sum("Broker Account Rows"),
    "Fund Rows": sum("Fund Rows"),
    "Deposits": Number(sum("Deposits").toFixed(2)),
    "Withdrawals": Number(sum("Withdrawals").toFixed(2)),
    "Net Deposits": Number(sum("Net Deposits").toFixed(2)),
    "Opened Account Rows": sum("Opened Account Rows"),
    "Rebate Rows": sum("Rebate Rows"),
    "Total Rebate": Number(sum("Total Rebate").toFixed(2)),
    "Notional Value": Number(sum("Notional Value").toFixed(2)),
    "Total Lots": Number(sum("Total Lots").toFixed(2)),
    "Latest Rebate Date": maxDateValue(records.map((row) => row["Latest Rebate Date"])),
    "Account Types": joinUnique(records.map((row) => row["Account Types"])),
    "Campaigns": joinUnique(records.map((row) => row.Campaigns)),
    "Instruments": joinUnique(records.map((row) => row.Instruments)),
    "Current Match Status": member?.current_match_status || (
      matchStatus === "Matched"
        ? "matched"
        : matchStatus === "Known from report history" ? "historical_only" : "uid_not_in_reports"
    ),
  };
}

function unlinkedMemberTradingRecord(member) {
  return {
    "Telegram Member": member.display_name || member.username || `Telegram ID ${member.telegram_id}`,
    "UIDs": "",
    "UID Details": [],
    "Linked UID Count": 0,
    "Broker": "Broker needed",
    "Brokers": [],
    "Match Status": "No UID linked",
    "Broker Report Name": "No UID linked",
    "Account IDs": "",
    "Account Count": 0,
    "Account Details": [],
    "Active Account Count": 0,
    "Inactive Account Count": 0,
    "Account Status": "Unknown",
    "Total Balance": 0,
    "Total Equity": 0,
    "Last Deposit Date": "",
    "Last Trade Date": "",
    "Broker Account Rows": 0,
    "Fund Rows": 0,
    "Deposits": 0,
    "Withdrawals": 0,
    "Net Deposits": 0,
    "Opened Account Rows": 0,
    "Rebate Rows": 0,
    "Total Rebate": 0,
    "Notional Value": 0,
    "Total Lots": 0,
    "Latest Rebate Date": "",
    "Account Types": "",
    "Campaigns": "",
    "Instruments": "",
    "Telegram Username": member.username ? `@${String(member.username).replace(/^@/, "")}` : "",
    "Telegram ID": member.telegram_id || "",
    "Telegram Groups": (member.groups || []).map((group) => group === "vip" ? "VIP" : "Discussion").join(" + "),
    "Current Match Status": member.current_match_status || "no_uid",
  };
}

function buildMatchedRecordsRows() {
  const directory = telegramMemberDirectory();
  const membersById = new Map((directory.members || []).map((member) => [String(member.telegram_id), member]));
  const grouped = new Map();
  const unassigned = [];
  for (const row of buildMatchedUidRecords()) {
    const telegramId = String(row["Telegram ID"] || "");
    if (!telegramId) {
      unassigned.push({ ...row, "UID Details": [row], "Brokers": [normalizedBroker(row.Broker)].filter(Boolean) });
      continue;
    }
    const memberRows = grouped.get(telegramId) || [];
    memberRows.push(row);
    grouped.set(telegramId, memberRows);
  }
  const rows = [
    ...[...grouped.entries()].map(([telegramId, records]) =>
      combineMemberTradingRecords(membersById.get(telegramId), records)
    ),
    ...(directory.members || [])
      .filter((member) => !grouped.has(String(member.telegram_id)))
      .map(unlinkedMemberTradingRecord),
    ...unassigned,
  ];
  return rows.sort((a, b) => {
    const statusOrder = {
      "Matched": 0,
      "No UID linked": 1,
      "UID missing in report data": 2,
      "Known from report history": 3,
      "No Telegram link": 4,
    };
    const statusDiff = (statusOrder[a["Match Status"]] ?? 3) - (statusOrder[b["Match Status"]] ?? 3);
    if (statusDiff) return statusDiff;
    const accountOrder = {"Active": 0, "Inactive": 1, "Unknown": 2};
    const accountDiff = (accountOrder[a["Account Status"]] ?? 3) - (accountOrder[b["Account Status"]] ?? 3);
    if (accountDiff) return accountDiff;
    const memberDiff = String(a["Telegram Member"]).localeCompare(String(b["Telegram Member"]), undefined, { numeric: true });
    if (memberDiff) return memberDiff;
    const brokerDiff = String(a.Broker).localeCompare(String(b.Broker));
    if (brokerDiff) return brokerDiff;
    return String(a.UIDs).localeCompare(String(b.UIDs), undefined, { numeric: true });
  });
}

function tradingRowDetails(row) {
  return Array.isArray(row["UID Details"]) && row["UID Details"].length
    ? row["UID Details"]
    : [row];
}

function tradingRowHasMatchStatus(row, status) {
  return tradingRowDetails(row).some((detail) => detail["Match Status"] === status);
}

function tradingRowNeedsCurrentMatch(row) {
  return Boolean(row["Telegram ID"]) && row["Current Match Status"] !== "matched";
}

function tradingRecordTradeAge(value) {
  const cleanValue = String(value || "").slice(0, 10);
  if (!cleanValue) return null;
  const parsed = new Date(`${cleanValue}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.floor((today.getTime() - parsed.getTime()) / 86400000);
}

function tradingRecordMatchesTradeWindow(row, tradeWindow) {
  if (tradeWindow === "all") return true;
  const age = tradingRecordTradeAge(row["Last Trade Date"]);
  if (tradeWindow === "none") return age === null;
  if (age === null || age < 0) return false;
  if (tradeWindow === "7") return age <= 7;
  if (tradeWindow === "30") return age <= 30;
  if (tradeWindow === "31_90") return age >= 31 && age <= 90;
  if (tradeWindow === "over_90") return age > 90;
  return true;
}

function sortTradingRecords(rows, sort) {
  const sorted = [...rows];
  const textCompare = (left, right) => String(left || "").localeCompare(
    String(right || ""),
    undefined,
    { numeric: true, sensitivity: "base" }
  );
  const numberCompare = (field) => (left, right) =>
    Number(right[field] || 0) - Number(left[field] || 0);
  const comparators = {
    member_asc: (left, right) => textCompare(left["Telegram Member"], right["Telegram Member"]),
    trade_desc: (left, right) => textCompare(right["Last Trade Date"], left["Last Trade Date"]),
    balance_desc: numberCompare("Total Balance"),
    equity_desc: numberCompare("Total Equity"),
    rebate_desc: numberCompare("Total Rebate"),
    accounts_desc: numberCompare("Account Count"),
  };
  return comparators[sort] ? sorted.sort(comparators[sort]) : sorted;
}

function renderMatchedRecordsPage() {
  if (!brokerReportsState.data || !telegramMembersPageState.data) return;
  const allRows = buildMatchedRecordsRows();
  matchedRecordsState.rows = allRows;
  const brokerFilter = matchedRecordsState.broker;
  const statusFilter = matchedRecordsState.status;
  const tradeWindow = matchedRecordsState.tradeWindow;
  const query = matchedRecordsState.search.trim().toLowerCase();
  const rows = sortTradingRecords(allRows.filter((row) => {
    const brokerMatches = brokerFilter === "all" || (row.Brokers || [row.Broker]).includes(brokerFilter);
    const statusMatches = statusFilter === "all"
      || (statusFilter === "matched" && tradingRowHasMatchStatus(row, "Matched"))
      || (statusFilter === "needs_match" && tradingRowNeedsCurrentMatch(row))
      || (statusFilter === "active" && row["Account Status"] === "Active")
      || (statusFilter === "inactive" && row["Account Status"] === "Inactive")
      || (statusFilter === "historical" && tradingRowHasMatchStatus(row, "Known from report history"))
      || (statusFilter === "no_telegram" && tradingRowHasMatchStatus(row, "No Telegram link"))
      || (statusFilter === "missing_report" && tradingRowHasMatchStatus(row, "UID missing in report data"));
    const haystack = Object.values(row).join(" ").toLowerCase();
    return brokerMatches
      && statusMatches
      && tradingRecordMatchesTradeWindow(row, tradeWindow)
      && (!query || haystack.includes(query));
  }), matchedRecordsState.sort);
  matchedRecordsState.visibleRows = rows;
  const directory = telegramMemberDirectory();
  const directoryMemberCount = Number(directory.summary?.members);
  const totalTelegramMembers = Number.isFinite(directoryMemberCount)
    ? directoryMemberCount
    : (directory.members || []).length;
  const scopeRows = allRows.filter((row) =>
    brokerFilter === "all" || (row.Brokers || [row.Broker]).includes(brokerFilter)
  );
  const matchedRows = scopeRows.filter((row) => tradingRowHasMatchStatus(row, "Matched"));
  const activeRows = matchedRows.filter((row) => row["Account Status"] === "Active");
  const needsReviewCount = scopeRows.filter((row) =>
    tradingRowNeedsCurrentMatch(row)
    || tradingRowHasMatchStatus(row, "UID missing in report data")
    || tradingRowHasMatchStatus(row, "No Telegram link")
  ).length;
  const totalBalance = matchedRows.reduce((sum, row) => sum + Number(row["Total Balance"] || 0), 0);
  const totalRebate = matchedRows.reduce((sum, row) => sum + Number(row["Total Rebate"] || 0), 0);
  const summaryMatchedCount = Number(directory.summary?.matched_members);
  const matchedMemberCount = Number.isFinite(summaryMatchedCount)
    ? summaryMatchedCount
    : allRows.filter((row) => row["Current Match Status"] === "matched").length;
  const summaryNeedsMatchCount = Number(directory.summary?.members_needing_current_match);
  const needsMatchCount = Number.isFinite(summaryNeedsMatchCount)
    ? summaryNeedsMatchCount
    : allRows.filter(tradingRowNeedsCurrentMatch).length;
  document.getElementById("matchedRecordsSummaryMembers").textContent = totalTelegramMembers.toLocaleString();
  document.getElementById("matchedRecordsSummaryMatched").textContent =
    matchedMemberCount.toLocaleString();
  const resolveButton = document.getElementById("matchedRecordsResolveMembersButton");
  resolveButton.textContent = `Resolve ${needsMatchCount.toLocaleString()}`;
  resolveButton.hidden = needsMatchCount === 0;
  document.getElementById("matchedRecordsSummaryActive").textContent =
    activeRows.length.toLocaleString();
  document.getElementById("matchedRecordsSummaryBalance").textContent =
    formatCompactMoney(totalBalance);
  document.getElementById("matchedRecordsSummaryRebate").textContent =
    formatCompactMoney(totalRebate);
  document.getElementById("matchedRecordsShownCount").textContent =
    `${rows.length.toLocaleString()} of ${allRows.length.toLocaleString()} rows`;
  const brokerLabel = brokerFilter === "all" ? "All brokers" : brokerFilter;
  document.getElementById("matchedRecordsScope").textContent =
    `${brokerLabel} · ${needsReviewCount.toLocaleString()} record(s) need review`;
  document.getElementById("matchedRecordsStatus").textContent = rows.length
    ? "Each Telegram member is shown once with all linked Vantage and PU Prime UIDs and accounts."
    : "No records match this filter.";
  renderMatchedRecordsResolver(statusFilter, rows);
  renderTradingRecordsTable(rows);
}

function statusPill(value) {
  const text = String(value || "Unknown");
  const lower = text.toLowerCase();
  const tone = lower === "matched" || lower === "active"
    ? "good"
    : lower.includes("missing") || lower.includes("no telegram") || lower.includes("no uid")
      ? "bad"
      : lower === "inactive" || lower.includes("history") || lower.includes("latest report")
        ? "warn"
        : "";
  return `<span class="trading-status ${tone}">${escapeHtml(text)}</span>`;
}

function tradingRecordActions(row) {
  const uid = escapeHtml(row.UIDs || "");
  const broker = escapeHtml(row.Broker || "");
  const telegramId = escapeHtml(row["Telegram ID"] || "");
  if (row["Current Match Status"] === "no_uid") {
    return `<div class="trading-record-actions"><button class="trading-record-action primary" type="button" data-trading-record-action="edit" data-telegram-id="${telegramId}">Link UID</button></div>`;
  }
  if (row["Current Match Status"] === "historical_only") {
    return `<div class="trading-record-actions">
      <button class="trading-record-action primary" type="button" data-trading-record-action="edit" data-telegram-id="${telegramId}">Review UID</button>
      <button class="trading-record-action" type="button" data-trading-record-action="upload">Upload latest reports</button>
    </div>`;
  }
  if (row["Current Match Status"] === "uid_not_in_reports") {
    return `<div class="trading-record-actions">
      <button class="trading-record-action primary" type="button" data-trading-record-action="edit" data-telegram-id="${telegramId}">Correct UID</button>
      <button class="trading-record-action" type="button" data-trading-record-action="upload">Upload latest reports</button>
    </div>`;
  }
  if (row["Match Status"] === "No Telegram link") {
    return `<div class="trading-record-actions"><button class="trading-record-action primary" type="button" data-trading-record-action="assign" data-uid="${uid}" data-broker="${broker}">Assign member</button></div>`;
  }
  if (row["Match Status"] === "UID missing in report data") {
    return `<div class="trading-record-actions">
      <button class="trading-record-action primary" type="button" data-trading-record-action="edit" data-telegram-id="${telegramId}">Edit UID</button>
      <button class="trading-record-action" type="button" data-trading-record-action="upload" data-broker="${broker}">Upload report</button>
    </div>`;
  }
  if (row["Account Status"] === "Inactive" && telegramId) {
    return `<div class="trading-record-actions"><button class="trading-record-action" type="button" data-trading-record-action="review-member" data-telegram-id="${telegramId}">Review member</button></div>`;
  }
  return "";
}

function renderMatchedRecordsResolver(status, rows) {
  const resolver = document.getElementById("matchedRecordsResolver");
  const noUidCount = rows.filter((row) => row["Current Match Status"] === "no_uid").length;
  const historicalOnlyCount = rows.filter((row) => row["Current Match Status"] === "historical_only").length;
  const unverifiedCount = rows.filter((row) => row["Current Match Status"] === "uid_not_in_reports").length;
  const configurations = {
    needs_match: {
      title: `${rows.length.toLocaleString()} Telegram member(s) need a current broker match`,
      detail: `${noUidCount.toLocaleString()} need a UID, ${historicalOnlyCount.toLocaleString()} have UIDs found only in older reports, and ${unverifiedCount.toLocaleString()} have UIDs not found in any report. Resolve the UID rows or upload the latest broker files, then refresh.`,
      actions: rows.length
        ? '<button class="primary" type="button" data-record-resolver-action="resolve-first">Resolve first member</button><button type="button" data-record-resolver-action="upload-all">Upload latest reports</button><button type="button" data-record-resolver-action="refresh">Check again</button>'
        : "",
    },
    missing_report: {
      title: `${rows.length.toLocaleString()} saved UID(s) have never been verified`,
      detail: "These values are absent from both current and historical reports. Upload the correct file or use Edit UID to correct the value.",
      actions: '<button class="primary" type="button" data-record-resolver-action="upload-all">Upload latest reports</button><button type="button" data-record-resolver-action="refresh">Check again</button>',
    },
    no_telegram: {
      title: `${rows.length.toLocaleString()} broker UID(s) need a Telegram name`,
      detail: "Assign each UID directly from its row. The broker and UID are filled in automatically.",
      actions: rows.length ? '<button class="primary" type="button" data-record-resolver-action="assign-first">Assign first UID</button>' : "",
    },
    inactive: {
      title: `${rows.length.toLocaleString()} Telegram member(s) are inactive`,
      detail: "Every linked account is inactive because it has both less than $50 equity and no trade within 30 days.",
      actions: '<button class="primary" type="button" data-record-resolver-action="review-first">Review first member</button><button type="button" data-record-resolver-action="upload-all">Upload latest report</button>',
    },
  };
  const configuration = configurations[status];
  resolver.classList.toggle("hidden", !configuration);
  if (!configuration) return;
  document.getElementById("matchedRecordsResolverTitle").textContent = configuration.title;
  document.getElementById("matchedRecordsResolverDetail").textContent = configuration.detail;
  document.getElementById("matchedRecordsResolverActions").innerHTML = configuration.actions;
}

function renderTradingRecordsTable(rows) {
  const target = document.getElementById("matchedRecordsTable");
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">No trading records match this view.</div>';
    return;
  }
  const body = rows.map((row, rowIndex) => {
    const member = row["Telegram Member"] || "No Telegram member";
    const username = row["Telegram Username"] || "";
    const telegramMeta = [username, row["Telegram ID"] ? `ID ${row["Telegram ID"]}` : "", row["Telegram Groups"]]
      .filter(Boolean)
      .join(" · ");
    const uidHtml = tradingRowDetails(row).map((detail) => {
      const uidMeta = [detail.Broker, detail["Account IDs"] ? `Accounts ${detail["Account IDs"]}` : ""]
        .filter(Boolean)
        .join(" · ");
      return `<div class="trading-member-uid">
        <strong>UID ${escapeHtml(detail.UIDs || "—")}</strong>
        <small>${escapeHtml(uidMeta || "Broker needed")}</small>
        <small>${escapeHtml(detail["Match Status"] || "Unknown")}</small>
      </div>`;
    }).join("");
    const accountStructureMeta = [
      Number(row["Linked UID Count"] || 0) ? `${Number(row["Linked UID Count"])} linked UID(s)` : "",
      Number(row["Account Count"] || 0) ? `${Number(row["Account Count"])} account(s)` : "",
    ].filter(Boolean).join(" · ");
    const accountActivityMeta = [
      Number(row["Active Account Count"] || 0) ? `${Number(row["Active Account Count"])} active` : "",
      Number(row["Inactive Account Count"] || 0) ? `${Number(row["Inactive Account Count"])} inactive` : "",
    ].filter(Boolean).join(" · ");
    const reviewMeta = [
      Number(row["Broker Account Rows"] || 0) ? `${row["Broker Account Rows"]} account row(s)` : "",
      Number(row["Fund Rows"] || 0) ? `${row["Fund Rows"]} fund row(s)` : "",
      Number(row["Rebate Rows"] || 0) ? `${row["Rebate Rows"]} rebate row(s)` : "",
    ].filter(Boolean).join(" · ");
    const reviewCopy = reviewMeta || (
      row["Match Status"] === "Known from report history"
        ? "Verified earlier · no current financial data"
        : "Ready"
    );
    const accountDetails = row["Account Details"] || [];
    const detailRowId = `trading-account-details-${rowIndex}`;
    const detailList = (value) => (Array.isArray(value) ? value : [value]).filter(Boolean).join(", ");
    const accountDetailHtml = accountDetails.length
      ? `<div class="trading-account-detail-grid">${accountDetails.map((detail) => `<article class="trading-account-detail-card">
          <div class="trading-account-detail-heading">
            <div><strong>Account ${escapeHtml(detail["Account Number"] || "not provided")}</strong><small>${escapeHtml(detail["Client Name"] || "No client name")}</small></div>
            ${statusPill(detail.Status || "Unknown")}
          </div>
          <div class="trading-account-detail-values">
            <div><span>Broker / UID</span><strong>${escapeHtml(detail.Broker || "Broker needed")}</strong><small>UID ${escapeHtml(detail.UID || "—")}</small></div>
            <div><span>Balance / Equity</span><strong>${escapeHtml(money(detail.Balance || 0))}</strong><small>Equity ${escapeHtml(money(detail.Equity || 0))}</small></div>
            <div><span>Last Trade</span><strong>${escapeHtml(detail["Last Trade Date"] || "No trade date")}</strong><small>${escapeHtml(detail["Last Deposit Date"] ? `Deposit ${detail["Last Deposit Date"]}` : "No deposit date")}</small></div>
            <div><span>Rebate / Volume</span><strong>${escapeHtml(money(detail["Total Rebate"] || 0))}</strong><small>${escapeHtml(Number(detail["Total Lots"] || 0).toLocaleString())} lots</small></div>
            <div><span>Notional</span><strong>${escapeHtml(formatCompactMoney(detail["Notional Value"] || 0))}</strong><small>${escapeHtml(detail["Latest Rebate Date"] ? `Latest rebate ${detail["Latest Rebate Date"]}` : "No rebate date")}</small></div>
            <div><span>Account Type</span><strong>${escapeHtml(detailList(detail["Account Types"]) || "Not provided")}</strong><small>${escapeHtml(detailList(detail.Campaigns) || "No campaign")}</small></div>
            <div class="wide"><span>Instruments</span><strong>${escapeHtml(detailList(detail.Instruments) || "No instrument data")}</strong></div>
            <div class="wide"><span>Report Sources</span><strong>${escapeHtml(detailList(detail.Sources) || "Saved UID")}</strong></div>
          </div>
        </article>`).join("")}</div>`
      : '<div class="empty-state">No individual account records are available for this member.</div>';
    const expandButton = accountDetails.length
      ? `<button class="trading-account-toggle" type="button" aria-expanded="false" aria-controls="${detailRowId}" data-trading-account-toggle="${detailRowId}" data-account-count="${accountDetails.length}">Show all ${accountDetails.length.toLocaleString()} account(s)</button>`
      : "";
    return `<tr>
      <td><strong>${escapeHtml(member)}</strong><small>${escapeHtml(telegramMeta || "Telegram link needed")}</small><div class="trading-member-uids">${uidHtml}</div>${expandButton}</td>
      <td>${statusPill(row["Account Status"])}<small>${escapeHtml(accountStructureMeta || "No current account data")}</small><small>${escapeHtml(accountActivityMeta)}</small></td>
      <td><strong>${escapeHtml(money(row["Total Balance"] || 0))}</strong><small>Equity ${escapeHtml(money(row["Total Equity"] || 0))}</small><small>Net deposits ${escapeHtml(money(row["Net Deposits"] || 0))}</small></td>
      <td><strong>${escapeHtml(row["Last Trade Date"] || "No trade date")}</strong><small>Deposit ${escapeHtml(row["Last Deposit Date"] || "—")}</small></td>
      <td><strong>${escapeHtml(money(row["Total Rebate"] || 0))}</strong><small>${escapeHtml(Number(row["Total Lots"] || 0).toLocaleString())} lots · ${escapeHtml(formatCompactMoney(row["Notional Value"] || 0))} notional</small>${statusPill(row["Match Status"])}<small>${escapeHtml(reviewCopy)}</small>${tradingRecordActions(row)}</td>
    </tr>
    <tr id="${detailRowId}" class="trading-account-detail-row" hidden><td colspan="5">${accountDetailHtml}</td></tr>`;
  }).join("");
  target.innerHTML = `<table class="trading-records-table">
    <colgroup><col style="width:32%"><col style="width:15%"><col style="width:17%"><col style="width:16%"><col style="width:20%"></colgroup>
    <thead><tr>
      <th>Telegram Member / Accounts</th>
      <th>Member Activity</th>
      <th>Balance / Equity</th>
      <th>Latest Activity</th>
      <th>Trading / Review</th>
    </tr></thead>
    <tbody>${body}</tbody>
    </table>`;
  target.querySelectorAll("[data-trading-record-action]").forEach((button) => {
    button.addEventListener("click", () => runTradingRecordAction(button));
  });
  target.querySelectorAll("[data-trading-account-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const detailRow = document.getElementById(button.dataset.tradingAccountToggle);
      if (!detailRow) return;
      const expanding = detailRow.hidden;
      detailRow.hidden = !expanding;
      button.setAttribute("aria-expanded", String(expanding));
      button.textContent = expanding
        ? "Hide accounts"
        : `Show all ${Number(button.dataset.accountCount || 0).toLocaleString()} account(s)`;
    });
  });
}

function openBrokerReportUploader(broker = "") {
  showDashboardPage("uploads");
  const brokerKey = normalizedBroker(broker) === "Vantage"
    ? "vantage"
    : normalizedBroker(broker) === "PU Prime" ? "puprime" : "";
  document.getElementById("dashboardMessage").textContent = brokerKey
    ? `Choose the latest ${normalizedBroker(broker)} IB account or rebate report.`
    : "Choose the latest Vantage and PU Prime files that contain the missing UIDs.";
  if (brokerKey) document.getElementById(`${brokerKey}IbAccountReportButton`).click();
}

function openTelegramMemberEditor(telegramId) {
  const cleanId = String(telegramId || "");
  telegramMembersPageState.search = cleanId;
  telegramMembersPageState.broker = "all";
  telegramMembersPageState.status = "all";
  document.getElementById("telegramMembersSearch").value = cleanId;
  document.getElementById("telegramMembersBrokerFilter").value = "all";
  document.getElementById("telegramMembersStatusFilter").value = "all";
  showDashboardPage("telegram-members");
  const focusMember = () => {
    const member = (telegramMemberDirectory().members || []).find(
      (row) => String(row.telegram_id) === cleanId
    );
    if (!member) return false;
    renderManualTelegramMemberOptions();
    document.getElementById("telegramMemberManualName").value = member.telegram_id;
    document.getElementById("telegramMemberManualUid").value = "";
    setTelegramMembersStatus(`Selected ${member.display_name || member.telegram_id}. Enter a UID to link another account.`);
    document.getElementById("telegramMemberBulkHeading").scrollIntoView({ behavior: "smooth", block: "start" });
    document.getElementById("telegramMemberManualUid").focus();
    return true;
  };
  if (!focusMember()) {
    loadTelegramMemberLinks({ force: true }).then(focusMember).catch((error) => {
      setTelegramMembersStatus(error.message);
    });
  }
}

function tradingRecordRow(uid, broker, matchStatus = "") {
  return matchedRecordsState.rows.find((row) =>
    normalizedUid(row.UIDs) === normalizedUid(uid)
    && normalizedBroker(row.Broker) === normalizedBroker(broker)
    && (!matchStatus || row["Match Status"] === matchStatus)
  );
}

function openTradingRecordAssignment(uid, broker) {
  const row = tradingRecordRow(uid, broker, "No Telegram link");
  if (!row) {
    document.getElementById("matchedRecordsStatus").textContent = "This UID has already been assigned or is no longer in the current report.";
    return;
  }
  tradingRecordAssignment = row;
  document.getElementById("tradingRecordMemberSearch").value = "";
  document.getElementById("tradingRecordAssignStatus").textContent = "Choose the matching Telegram member.";
  document.getElementById("tradingRecordAssignContext").textContent =
    `UID ${row.UIDs} · ${row.Broker}${row["Broker Report Name"] && row["Broker Report Name"] !== "Not in report data" ? ` · ${row["Broker Report Name"]}` : ""}`;
  renderTradingRecordMemberResults();
  document.getElementById("tradingRecordAssignDialog").showModal();
  document.getElementById("tradingRecordMemberSearch").focus();
}

function renderTradingRecordMemberResults() {
  const target = document.getElementById("tradingRecordMemberResults");
  const query = document.getElementById("tradingRecordMemberSearch").value.trim().toLowerCase();
  const members = (telegramMemberDirectory().members || []).filter((member) => {
    const haystack = [member.display_name, member.username, member.telegram_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return !query || haystack.includes(query);
  });
  if (!members.length) {
    target.innerHTML = '<div class="empty-state">No Telegram members match this search.</div>';
    return;
  }
  target.innerHTML = members.map((member) => {
    const username = member.username ? `@${String(member.username).replace(/^@/, "")}` : "No username";
    const groups = (member.groups || []).map((group) => group === "vip" ? "VIP" : "Discussion").join(" + ") || "Manual member";
    const linkCount = (member.links || []).length;
    return `<div class="telegram-account-option">
      <div><strong>${escapeHtml(member.display_name || "Unknown")}</strong><small>${escapeHtml(username)} · ID ${escapeHtml(member.telegram_id)}</small><small>${escapeHtml(groups)} · ${linkCount.toLocaleString()} current UID(s)</small></div>
      <button class="assign-trading-record-member" type="button" data-telegram-id="${escapeHtml(member.telegram_id)}">Assign</button>
    </div>`;
  }).join("");
  target.querySelectorAll(".assign-trading-record-member").forEach((button) => {
    button.addEventListener("click", () => assignTradingRecordToMember(button.dataset.telegramId));
  });
}

async function assignTradingRecordToMember(telegramId) {
  const row = tradingRecordAssignment;
  const status = document.getElementById("tradingRecordAssignStatus");
  const member = (telegramMemberDirectory().members || []).find(
    (candidate) => String(candidate.telegram_id) === String(telegramId)
  );
  if (!row || !member) return;
  document.querySelectorAll(".assign-trading-record-member").forEach((button) => { button.disabled = true; });
  status.textContent = `Assigning UID ${row.UIDs} to ${member.display_name || member.telegram_id}…`;
  try {
    await linkTelegramMemberUid(member.telegram_id, row.UIDs, status, row.Broker);
    const remaining = matchedRecordsState.visibleRows.find(
      (candidate) => candidate["Match Status"] === "No Telegram link"
    );
    if (!remaining) {
      document.getElementById("tradingRecordAssignDialog").close();
      document.getElementById("matchedRecordsStatus").textContent = `UID ${row.UIDs} assigned. No unassigned UID remains in this view.`;
      return;
    }
    tradingRecordAssignment = remaining;
    document.getElementById("tradingRecordAssignContext").textContent =
      `Next: UID ${remaining.UIDs} · ${remaining.Broker}${remaining["Broker Report Name"] && remaining["Broker Report Name"] !== "Not in report data" ? ` · ${remaining["Broker Report Name"]}` : ""}`;
    document.getElementById("tradingRecordMemberSearch").value = "";
    status.textContent = `UID ${row.UIDs} assigned. Choose a member for the next UID.`;
    renderTradingRecordMemberResults();
  } catch (error) {
    status.textContent = error.message;
    renderTradingRecordMemberResults();
  }
}

function runTradingRecordAction(button) {
  const action = button.dataset.tradingRecordAction;
  if (action === "assign") openTradingRecordAssignment(button.dataset.uid, button.dataset.broker);
  if (action === "edit" || action === "review-member") openTelegramMemberEditor(button.dataset.telegramId);
  if (action === "upload") openBrokerReportUploader(button.dataset.broker);
}

function runMatchedRecordResolverAction(action) {
  if (action === "upload-all") {
    openBrokerReportUploader();
    return;
  }
  if (action === "refresh") {
    loadMatchedRecordsPage({ force: true });
    return;
  }
  const first = matchedRecordsState.visibleRows[0];
  if (!first) return;
  if (action === "assign-first") openTradingRecordAssignment(first.UIDs, first.Broker);
  if (action === "review-first") openTelegramMemberEditor(first["Telegram ID"]);
  if (action === "resolve-first") {
    const nextMember = matchedRecordsState.visibleRows.find(
      (row) => row["Current Match Status"] === "no_uid"
    ) || first;
    openTelegramMemberEditor(nextMember["Telegram ID"]);
  }
}

document.getElementById("matchedRecordsResolver").addEventListener("click", (event) => {
  const button = event.target.closest("[data-record-resolver-action]");
  if (button) runMatchedRecordResolverAction(button.dataset.recordResolverAction);
});
document.getElementById("tradingRecordAssignDialogClose").addEventListener("click", () => {
  document.getElementById("tradingRecordAssignDialog").close();
});
document.getElementById("tradingRecordMemberSearch").addEventListener("input", renderTradingRecordMemberResults);

async function loadTelegramMemberLinks(options = {}) {
  if (telegramMembersPageState.data && !options.force) {
    renderHelpfulOverview();
    return telegramMembersPageState.data;
  }
  const result = await requestJson("/api/telegram/account-links", { method: "GET" });
  telegramMembersPageState.data = result;
  telegramAccountLinkData = result;
  if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
  if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
  if (dashboardView.dataset.activePage === "telegram") renderTelegramAccountLinks();
  renderHelpfulOverview();
  return result;
}

async function loadMatchedRecordsPage(options = {}) {
  if (matchedRecordsState.loading) return;
  matchedRecordsState.loading = true;
  document.getElementById("matchedRecordsStatus").textContent = "Loading trading data and Telegram UID links…";
  try {
    const requests = [];
    if (!brokerReportsState.data || options.force) {
      requests.push(requestJson("/api/reports/data", { method: "GET" }).then((result) => {
        brokerReportsState.data = result;
        latestOverviewState.reportData = result;
      }));
    }
    if (!telegramMembersPageState.data || options.force) {
      requests.push(loadTelegramMemberLinks(options));
    }
    await Promise.all(requests);
    renderMatchedRecordsPage();
    renderHelpfulOverview();
  } catch (error) {
    document.getElementById("matchedRecordsStatus").textContent = error.message;
  } finally {
    matchedRecordsState.loading = false;
  }
}

function telegramMemberDirectory() {
  return telegramMembersPageState.data?.member_directory || {
    members: [],
    summary: {},
  };
}

function telegramLinkBrokers(link) {
  return [...new Set([
    link.broker,
    ...(link.brokers || []),
  ].filter(Boolean))];
}

function canonicalTelegramLinkBroker(link) {
  if (link.broker === "Vantage" || link.broker === "PU Prime") return link.broker;
  const brokers = telegramLinkBrokers(link);
  return brokers.length === 1 ? brokers[0] : "";
}

function setTelegramMembersStatus(message) {
  document.getElementById("telegramMembersPageStatus").textContent = message;
}

function telegramMemberGroupsLabel(member) {
  return (member.groups || [])
    .map((group) => group === "vip" ? "VIP" : "Discussion")
    .join(" + ") || "Manual";
}

function telegramMembersCsvRows() {
  const directory = telegramMemberDirectory();
  const rows = [];
  for (const member of directory.members || []) {
    const username = member.username ? `@${String(member.username).replace(/^@/, "")}` : "";
    const base = {
      "Telegram Member": member.display_name || "",
      "Telegram Username": username,
      "Telegram ID": member.telegram_id || "",
      Groups: telegramMemberGroupsLabel(member),
      Source: member.source || "",
      "Member Activity": member.activity_status || "unknown",
      "Member Account Count": member.account_count || 0,
      "Member Combined Equity": member.total_equity || 0,
      "Member Last Trade Date": member.last_trade_date || "",
      "Active Accounts": member.active_account_count || 0,
      "Inactive Accounts": member.inactive_account_count || 0,
    };
    const links = member.links || [];
    if (!links.length) {
      rows.push({
        ...base,
        UID: "",
        Broker: "",
        "Report Names": "",
        "Account Count": "",
        "Total Balance": "",
        Verification: "No UID linked",
        "Present In Latest Reports": "No",
        "Known From Report History": "No",
      });
      continue;
    }
    for (const link of links) {
      rows.push({
        ...base,
        UID: link.uid || "",
        Broker: canonicalTelegramLinkBroker(link) || telegramLinkBrokers(link).join(" + "),
	        "Report Names": (link.report_names || []).join(", "),
	        "Account Count": link.account_count ?? "",
	        "Total Balance": link.total_balance ?? "",
	        "Total Equity": link.total_equity ?? "",
	        "Account Activity": link.activity_status || "unknown",
	        "Last Trade Date": link.last_trade_date || "",
	        "Total Rebate": link.total_rebate ?? "",
	        "Report Sources": (link.report_sources || []).join(", "),
	        Verification: link.present_in_current_reports
	          ? "Current report"
	          : link.known_from_history ? "Report history" : "Unverified",
	        "Present In Latest Reports": link.present_in_current_reports ? "Yes" : "No",
	        "Known From Report History": link.known_from_history ? "Yes" : "No",
	      });
    }
  }
  return rows;
}

function tradingRecordsCsvRows(rows) {
  return rows.map((row) => {
    const {
      "UID Details": uidDetails,
      "Account Details": accountDetails,
      Brokers: brokers,
      ...exportRow
    } = row;
    return {
      ...exportRow,
      UIDs: tradingRowDetails(row)
        .map((detail) => `${detail.UIDs || ""} (${detail.Broker || "Broker needed"})`)
        .join(" | "),
      Brokers: (brokers || []).join(" + "),
      "Individual Accounts": (accountDetails || []).map((detail) => [
        detail["Account Number"] || "No account number",
        detail.Broker || "Broker needed",
        `UID ${detail.UID || ""}`,
        `Balance ${Number(detail.Balance || 0).toFixed(2)}`,
        `Equity ${Number(detail.Equity || 0).toFixed(2)}`,
        `Last trade ${detail["Last Trade Date"] || "none"}`,
        `Last deposit ${detail["Last Deposit Date"] || "none"}`,
        detail.Status || "Unknown",
        `Rebate ${Number(detail["Total Rebate"] || 0).toFixed(2)}`,
        `Lots ${Number(detail["Total Lots"] || 0)}`,
        `Notional ${Number(detail["Notional Value"] || 0).toFixed(2)}`,
        `Account type ${(detail["Account Types"] || []).join(", ") || "none"}`,
        `Campaign ${(detail.Campaigns || []).join(", ") || "none"}`,
        `Instruments ${(detail.Instruments || []).join(", ") || "none"}`,
        `Sources ${(detail.Sources || []).join(", ") || "Saved UID"}`,
      ].join(" · ")).join(" | "),
    };
  });
}

function renderManualTelegramMemberOptions() {
  const members = [...(telegramMemberDirectory().members || [])].sort((a, b) =>
    String(a.display_name || a.username || "").localeCompare(
      String(b.display_name || b.username || ""),
      undefined,
      { numeric: true }
    )
  );
  for (const selectId of ["telegramMemberManualName", "telegramManualMemberName"]) {
    const select = document.getElementById(selectId);
    if (!select) continue;
    const selected = select.value;
    select.innerHTML = '<option value="">Select member</option>' + members.map((member) => {
      const username = member.username ? ` (@${String(member.username).replace(/^@/, "")})` : "";
      return `<option value="${escapeHtml(member.telegram_id)}">${escapeHtml((member.display_name || "Unknown") + username)}</option>`;
    }).join("");
    if (members.some((member) => String(member.telegram_id) === selected)) select.value = selected;
  }
  renderTelegramMemberRemovalOptions();
}

function renderTelegramMemberRemovalOptions() {
  const select = document.getElementById("telegramMemberRemovalName");
  if (!select) return;
  const members = [...(telegramMemberDirectory().members || [])].sort((a, b) =>
    String(a.display_name || a.username || "").localeCompare(
      String(b.display_name || b.username || ""),
      undefined,
      { numeric: true }
    )
  );
  const selected = select.value;
  select.innerHTML = '<option value="">Select member</option>' + members.map((member) => {
    const username = member.username ? ` (@${String(member.username).replace(/^@/, "")})` : "";
    return `<option value="${escapeHtml(member.telegram_id)}">${escapeHtml((member.display_name || "Unknown") + username)}</option>`;
  }).join("");
  if (members.some((member) => String(member.telegram_id) === selected)) select.value = selected;
  syncTelegramMemberRemovalGroups({ resetSelections: true, announce: false });
}

function syncTelegramMemberRemovalGroups(options = {}) {
  const select = document.getElementById("telegramMemberRemovalName");
  const member = (telegramMemberDirectory().members || []).find(
    (row) => String(row.telegram_id) === String(select.value)
  );
  const groups = new Set(member?.groups || []);
  for (const [group, inputId] of [
    ["discussion", "telegramMemberRemovalDiscussion"],
    ["vip", "telegramMemberRemovalVip"],
  ]) {
    const input = document.getElementById(inputId);
    const available = groups.has(group);
    input.disabled = !available;
    if (!available || options.resetSelections) input.checked = available;
  }
  document.getElementById("telegramMemberRemovalSubmit").disabled = !member;
  if (options.announce !== false) {
    document.getElementById("telegramMemberRemovalStatus").textContent = member
      ? `${member.display_name || member.telegram_id} is currently in ${telegramMemberGroupsLabel(member)}.`
      : "Select a member and the Telegram group(s).";
  }
}

async function linkTelegramMemberUid(telegramId, uid, statusElement, broker = "") {
  statusElement.textContent = `Linking UID ${uid}…`;
  const result = await requestJson("/api/telegram/account-links/manual", {
    method: "POST",
    // The broker is sent when it is known (a report row), so a UID used at both brokers links to the right one.
    body: JSON.stringify({ telegram_id: telegramId, uid, ...(broker ? { broker } : {}) }),
  });
  telegramMembersPageState.data = result;
  telegramAccountLinkData = result;
  renderTelegramMembersPage();
  if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
  if (dashboardView.dataset.activePage === "telegram") renderTelegramAccountLinks();
  renderHelpfulOverview();
  await Promise.allSettled([loadDashboard(), loadTelegramWorkspace()]);
  statusElement.textContent = `UID ${uid} linked.`;
  setTelegramMembersStatus(`UID ${uid} linked. Add another UID to the same member at any time.`);
  return result;
}

function renderTelegramMembersPage() {
  const directory = telegramMemberDirectory();
  renderManualTelegramMemberOptions();
  const summary = directory.summary || {};
  document.getElementById("telegramMembersSummaryMembers").textContent =
    Number(summary.members || 0).toLocaleString();
  document.getElementById("telegramMembersSummaryActive").textContent =
    Number(summary.active_members || 0).toLocaleString();
  document.getElementById("telegramMembersSummaryInactive").textContent =
    Number(summary.inactive_members || 0).toLocaleString();
  document.getElementById("telegramMembersSummaryLinked").textContent =
    Number(summary.linked_members || 0).toLocaleString();
  document.getElementById("telegramMembersSummaryUids").textContent =
    Number(summary.uid_links || 0).toLocaleString();

  const query = telegramMembersPageState.search.trim().toLowerCase();
  const brokerFilter = telegramMembersPageState.broker;
  const statusFilter = telegramMembersPageState.status;
  const rows = (directory.members || []).filter((member) => {
    const links = member.links || [];
    const linked = Boolean(links.length);
    const matchesStatus = statusFilter === "all"
      || (statusFilter === "active" && member.activity_status === "active")
      || (statusFilter === "inactive" && member.activity_status === "inactive")
      || (statusFilter === "unknown" && member.activity_status === "unknown")
      || (statusFilter === "linked" && linked)
      || (statusFilter === "unlinked" && !linked)
      || (statusFilter === "current" && links.some((link) => link.present_in_current_reports))
      || (statusFilter === "historical" && links.some((link) => link.known_from_history))
      || (statusFilter === "unverified" && links.some((link) => !link.present_in_reports));
    const matchesBroker = brokerFilter === "all"
      || links.some((link) => telegramLinkBrokers(link).includes(brokerFilter));
    const haystack = [
      member.display_name,
      member.username,
      member.telegram_id,
      member.source,
      member.activity_status,
      ...(member.groups || []),
      ...links.flatMap((link) => [
        link.uid,
        link.broker,
        ...(link.brokers || []),
        ...(link.report_names || []),
      ]),
    ].join(" ").toLowerCase();
    return matchesStatus && matchesBroker && (!query || haystack.includes(query));
  });

  document.getElementById("telegramMembersShownCount").textContent =
    `${rows.length.toLocaleString()} shown`;
  const target = document.getElementById("telegramMembersPageList");
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">No Telegram members match this view.</div>';
    return;
  }

  target.innerHTML = rows.map((member) => {
    const username = member.username ? `@${String(member.username).replace(/^@/, "")}` : "No username";
    const groups = telegramMemberGroupsLabel(member);
    const links = member.links || [];
    const linkHtml = links.length ? links.map((link) => {
	      const brokerCopy = telegramLinkBrokers(link).join(" + ") || "Broker needed";
	      const reportNames = (link.report_names || []).join(", ");
	      const accountReportCopy = link.present_in_account_reports
	        ? `${Number(link.account_count || 0).toLocaleString()} account(s) · ${money(link.total_equity || 0)} equity`
	        : "";
	      const rebateReportCopy = link.present_in_rebate_reports
	        ? `${money(link.total_rebate || 0)} rebate`
	        : "";
	      const reportCopy = link.present_in_current_reports
	        ? [accountReportCopy, rebateReportCopy].filter(Boolean).join(" · ") || "Found in latest reports"
	        : link.known_from_history
	          ? "Verified from an earlier broker report · not in latest report"
	          : "Unverified · not found in any uploaded report";
      return `<div class="telegram-member-link">
        <div>
          <strong>UID ${escapeHtml(link.uid || "")}</strong>
          <small>${escapeHtml(brokerCopy)}</small>
          <small>${escapeHtml(reportNames || reportCopy)}</small>
          ${reportNames ? `<small>${escapeHtml(reportCopy)}</small>` : ""}
        </div>
        <button class="telegram-member-link-remove" type="button" data-telegram-id="${escapeHtml(member.telegram_id)}" data-uid="${escapeHtml(link.uid || "")}" data-broker="${escapeHtml(link.broker || "")}">Remove</button>
      </div>`;
    }).join("") : '<span class="telegram-link-status unmatched">UID needed</span>';
    return `<div class="telegram-member-row">
      <div class="telegram-member-identity">
        <strong>${escapeHtml(member.display_name || "Unknown")}</strong>
        <small>${escapeHtml(username)} · ID ${escapeHtml(member.telegram_id)}</small>
        <small>${escapeHtml(groups)}</small>
        <small>${statusPill(member.activity_status || "Unknown")} · ${Number(member.account_count || 0).toLocaleString()} coupled account(s) · ${Number(member.active_account_count || 0).toLocaleString()} active · ${Number(member.inactive_account_count || 0).toLocaleString()} inactive</small>
        <button class="telegram-member-remove-groups" type="button" data-remove-telegram-member="${escapeHtml(member.telegram_id)}">Remove from groups</button>
      </div>
      <div class="telegram-member-links">${linkHtml}</div>
      <form class="telegram-member-row-form" data-telegram-id="${escapeHtml(member.telegram_id)}">
        <input name="uid" type="text" inputmode="numeric" autocomplete="off" maxlength="40" placeholder="UID" aria-label="New UID for ${escapeHtml(member.display_name || member.telegram_id)}">
        <button class="primary" type="submit">Add UID</button>
        <small aria-live="polite"></small>
      </form>
    </div>`;
  }).join("");

  target.querySelectorAll(".telegram-member-row-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const feedback = form.querySelector("small");
      const button = form.querySelector('button[type="submit"]');
      const member = rows.find((row) => String(row.telegram_id) === String(form.dataset.telegramId));
      const uid = form.elements.uid.value.trim();
      if (!member || !uid) {
        feedback.textContent = "Enter a UID.";
        return;
      }
      button.disabled = true;
      try {
        await linkTelegramMemberUid(member.telegram_id, uid, feedback);
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });

  target.querySelectorAll(".telegram-member-link-remove").forEach((button) => {
    button.addEventListener("click", () => removeTelegramMemberUidLink(
      button.dataset.telegramId,
      button.dataset.uid,
      button.dataset.broker
    ));
  });
  target.querySelectorAll("[data-remove-telegram-member]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("telegramMemberRemovalName").value = button.dataset.removeTelegramMember;
      syncTelegramMemberRemovalGroups({ resetSelections: true });
      document.getElementById("telegramMemberRemovalPanel").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

async function removeTelegramMemberFromGroups(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const telegramId = form.elements.telegram_id.value;
  const member = (telegramMemberDirectory().members || []).find(
    (row) => String(row.telegram_id) === String(telegramId)
  );
  const groups = [...form.querySelectorAll('input[name="groups"]:checked:not(:disabled)')]
    .map((input) => input.value);
  const groupLabels = groups.map((group) => group === "vip" ? "VIP" : "Discussion");
  const status = document.getElementById("telegramMemberRemovalStatus");
  const submit = document.getElementById("telegramMemberRemovalSubmit");
  if (!member || !groups.length) {
    status.textContent = "Select a current member and at least one group.";
    return;
  }
  const displayName = member.display_name || member.username || member.telegram_id;
  if (!window.confirm(`Remove ${displayName} from ${groupLabels.join(" + ")}? This changes Telegram membership immediately.`)) return;

  submit.disabled = true;
  status.textContent = `Removing ${displayName} from ${groupLabels.join(" + ")}…`;
  try {
    const result = await requestJson("/api/telegram/account-links/remove-member", {
      method: "POST",
      body: JSON.stringify({ telegram_id: telegramId, groups, confirmation_text: "REMOVE" }),
    });
    telegramMembersPageState.data = result;
    telegramAccountLinkData = result;
    renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    const removal = result.member_removal || {};
    const removedLabels = (removal.removed_groups || groups).map((group) => group === "vip" ? "VIP" : "Discussion");
    const failedLabels = (removal.failed_groups || []).map((row) => row.group === "vip" ? "VIP" : "Discussion");
    status.textContent = `${displayName} removed from ${removedLabels.join(" + ")}.` +
      (failedLabels.length ? ` Could not remove from ${failedLabels.join(" + ")}; check administrator permissions.` : "");
    setTelegramMembersStatus(status.textContent);
    await Promise.allSettled([loadDashboard(), loadTelegramWorkspace(), loadReplyDirectory()]);
  } catch (error) {
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    submit.disabled = false;
    syncTelegramMemberRemovalGroups({ announce: false });
  }
}

async function loadTelegramMembersPage(options = {}) {
  if (telegramMembersPageState.loading) return;
  telegramMembersPageState.loading = true;
  setTelegramMembersStatus("Loading Telegram member links…");
  try {
    const result = await requestJson("/api/telegram/account-links", { method: "GET" });
    telegramMembersPageState.data = result;
    telegramAccountLinkData = result;
    renderTelegramMembersPage();
    renderHelpfulOverview();
    const repairs = result.automatic_repairs || [];
    const removedMembers = Number(result.membership_changes?.removed || 0);
    setTelegramMembersStatus(removedMembers
      ? `${removedMembers.toLocaleString()} member(s) who left both Telegram groups were removed from the website directory.`
      : repairs.length
      ? `${repairs.length} saved account number or broker value(s) were corrected automatically from report evidence.`
      : result.needs_scan
        ? "Preparing to extract members from the connected Telegram groups."
        : `Last scanned ${formatOverviewDateTime(result.last_scanned_at)}.`);
    if (options.autoExtract) {
      await autoExtractTelegramMembersFromGroups();
    }
  } catch (error) {
    setTelegramMembersStatus(error.message);
  } finally {
    telegramMembersPageState.loading = false;
  }
}

async function autoExtractTelegramMembersFromGroups() {
  if (telegramMembersPageState.autoExtractAttempted) return;
  telegramMembersPageState.autoExtractAttempted = true;
  setTelegramMembersStatus("Checking Telegram before extracting group members…");
  const health = await loadTelegramHealth();
  if (!health.authorized) {
    setTelegramMembersStatus("Connect Telegram to extract member names from the linked groups.");
    return;
  }
  await scanTelegramMembersPage({ automatic: true });
}

async function scanTelegramMembersPage(options = {}) {
  const button = document.getElementById("scanTelegramMembersButton");
  if (!telegramAuthorizationVerified) {
    const health = await loadTelegramHealth();
    if (!health.authorized) {
      setTelegramMembersStatus("Reconnect Telegram before extracting members from groups.");
      if (!options.automatic) telegramConnectButton.click();
      return;
    }
  }
  button.disabled = true;
  setTelegramMembersStatus("Extracting member names from connected Telegram groups…");
  try {
    const result = await requestJson("/api/telegram/account-links/scan", { method: "POST" });
    telegramMembersPageState.data = result;
    telegramAccountLinkData = result;
    renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    const summary = result.member_directory?.summary || {};
    const changes = result.membership_changes || {};
    const warning = (result.warnings || [])[0];
    setTelegramMembersStatus(
      `Extracted ${Number(summary.members || 0).toLocaleString()} Telegram member name(s) from the connected groups. ${Number(summary.uid_links || 0).toLocaleString()} UID link(s) saved.` +
      (Number(changes.removed || 0) ? ` Removed ${Number(changes.removed).toLocaleString()} member(s) who left both groups.` : "") +
      (warning ? ` ${warning}` : "")
    );
    await loadDashboard();
  } catch (error) {
    setTelegramMembersStatus(error.message);
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    button.disabled = false;
  }
}

async function removeTelegramMemberUidLink(telegramId, uid, broker = "") {
  if (!window.confirm(`Remove UID ${uid}${broker ? ` from ${broker}` : ""}?`)) return;
  setTelegramMembersStatus(`Removing UID ${uid}…`);
  try {
    const result = await requestJson("/api/telegram/account-links/unlink", {
      method: "POST",
      body: JSON.stringify({ telegram_id: telegramId, uid, broker }),
    });
    telegramMembersPageState.data = result;
    telegramAccountLinkData = result;
    renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    await Promise.allSettled([loadDashboard(), loadTelegramWorkspace(), loadReplyDirectory()]);
    setTelegramMembersStatus(`UID ${uid} removed.`);
  } catch (error) {
    setTelegramMembersStatus(error.message);
  }
}

document.getElementById("telegramMemberBulkForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.getElementById("telegramMemberBulkSave");
  const telegramId = form.elements.telegram_id.value.trim();
  const uid = form.elements.uid.value.trim();
  if (!telegramId || !uid) {
    setTelegramMembersStatus("Select a Telegram member and enter a UID.");
    return;
  }
  button.disabled = true;
  try {
    await linkTelegramMemberUid(telegramId, uid, document.getElementById("telegramMembersPageStatus"));
    form.elements.uid.value = "";
    form.elements.uid.focus();
  } catch (error) {
    setTelegramMembersStatus(error.message);
  } finally {
    button.disabled = false;
  }
});
document.getElementById("telegramMemberRemovalName").addEventListener("change", () => {
  syncTelegramMemberRemovalGroups({ resetSelections: true });
});
document.getElementById("telegramMemberRemovalForm").addEventListener("submit", removeTelegramMemberFromGroups);

document.getElementById("telegramMembersSearch").addEventListener("input", (event) => {
  telegramMembersPageState.search = event.target.value;
  renderTelegramMembersPage();
});
document.getElementById("telegramMembersBrokerFilter").addEventListener("change", (event) => {
  telegramMembersPageState.broker = event.target.value;
  renderTelegramMembersPage();
});
document.getElementById("telegramMembersStatusFilter").addEventListener("change", (event) => {
  telegramMembersPageState.status = event.target.value;
  renderTelegramMembersPage();
});
document.getElementById("refreshTelegramMembersButton").addEventListener("click", () => {
  telegramMembersPageState.autoExtractAttempted = false;
  loadTelegramMembersPage({ autoExtract: true });
});
document.getElementById("scanTelegramMembersButton").addEventListener("click", () => {
  telegramMembersPageState.autoExtractAttempted = false;
  scanTelegramMembersPage({ automatic: false });
});
document.getElementById("exportTelegramMembersButton").addEventListener("click", () => {
  const rows = telegramMembersCsvRows();
  if (!rows.length) {
    setTelegramMembersStatus("No Telegram members are loaded to export.");
    return;
  }
  downloadTelegramCsv("telegram-members.csv", rows);
  setTelegramMembersStatus(`Exported ${rows.length.toLocaleString()} Telegram member CSV row(s).`);
});
document.getElementById("matchedRecordsBrokerFilter").addEventListener("change", (event) => {
  matchedRecordsState.broker = event.target.value;
  renderMatchedRecordsPage();
});
document.getElementById("matchedRecordsSearch").addEventListener("input", (event) => {
  matchedRecordsState.search = event.target.value;
  renderMatchedRecordsPage();
});
document.getElementById("matchedRecordsStatusFilter").addEventListener("change", (event) => {
  matchedRecordsState.status = event.target.value;
  renderMatchedRecordsPage();
});
document.getElementById("matchedRecordsTradeFilter").addEventListener("change", (event) => {
  matchedRecordsState.tradeWindow = event.target.value;
  renderMatchedRecordsPage();
});
document.getElementById("matchedRecordsSort").addEventListener("change", (event) => {
  matchedRecordsState.sort = event.target.value;
  renderMatchedRecordsPage();
});
document.getElementById("matchedRecordsRefreshButton").addEventListener("click", () => {
  loadMatchedRecordsPage({ force: true });
});
document.getElementById("matchedRecordsResolveMembersButton").addEventListener("click", () => {
  matchedRecordsState.broker = "all";
  matchedRecordsState.status = "needs_match";
  matchedRecordsState.tradeWindow = "all";
  matchedRecordsState.sort = "priority";
  matchedRecordsState.search = "";
  document.getElementById("matchedRecordsBrokerFilter").value = "all";
  document.getElementById("matchedRecordsStatusFilter").value = "needs_match";
  document.getElementById("matchedRecordsTradeFilter").value = "all";
  document.getElementById("matchedRecordsSort").value = "priority";
  document.getElementById("matchedRecordsSearch").value = "";
  renderMatchedRecordsPage();
  document.getElementById("matchedRecordsResolver").scrollIntoView({ behavior: "smooth", block: "center" });
});
document.getElementById("matchedRecordsResetButton").addEventListener("click", () => {
  matchedRecordsState.broker = "all";
  matchedRecordsState.status = "all";
  matchedRecordsState.tradeWindow = "all";
  matchedRecordsState.sort = "priority";
  matchedRecordsState.search = "";
  document.getElementById("matchedRecordsBrokerFilter").value = "all";
  document.getElementById("matchedRecordsStatusFilter").value = "all";
  document.getElementById("matchedRecordsTradeFilter").value = "all";
  document.getElementById("matchedRecordsSort").value = "priority";
  document.getElementById("matchedRecordsSearch").value = "";
  renderMatchedRecordsPage();
});
document.getElementById("exportMatchedRecordsButton").addEventListener("click", () => {
  const rows = tradingRecordsCsvRows(matchedRecordsState.visibleRows);
  if (!rows.length) {
    document.getElementById("matchedRecordsStatus").textContent = "No trading records are loaded to export.";
    return;
  }
  downloadTelegramCsv("trading-records.csv", rows);
  document.getElementById("matchedRecordsStatus").textContent =
    `Exported ${rows.length.toLocaleString()} trading record CSV row(s).`;
});
document.getElementById("brokerReportMatchedRecordsButton").addEventListener("click", () => {
  matchedRecordsState.broker = {
    vantage: "Vantage",
    puprime: "PU Prime",
  }[brokerReportsState.broker] || "all";
  matchedRecordsState.status = "matched";
  matchedRecordsState.tradeWindow = "all";
  matchedRecordsState.sort = "priority";
  matchedRecordsState.search = "";
  document.getElementById("matchedRecordsBrokerFilter").value = matchedRecordsState.broker;
  document.getElementById("matchedRecordsStatusFilter").value = matchedRecordsState.status;
  document.getElementById("matchedRecordsTradeFilter").value = "all";
  document.getElementById("matchedRecordsSort").value = "priority";
  document.getElementById("matchedRecordsSearch").value = "";
  showDashboardPage("matched-records");
});
document.getElementById("brokerReportClubButton").addEventListener("click", () => {
  const broker = {
    vantage: "Vantage",
    puprime: "PU Prime",
  }[brokerReportsState.broker] || "all";
  telegramMembersPageState.broker = broker;
  document.getElementById("telegramMembersBrokerFilter").value = broker;
  showDashboardPage("telegram-members");
  setTelegramMembersStatus("Select a Telegram member and enter the UID. The broker is detected automatically.");
});

function formatOverviewDateTime(value) {
  if (!value) return "Not imported";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString([], {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function overviewStatusRow(status, title, detail) {
  return `
    <li class="overview-health-item">
      <i class="overview-status-dot ${escapeHtml(status)}" aria-hidden="true"></i>
      <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>
    </li>`;
}

function overviewDirectorySummary() {
  const directory = telegramMemberDirectory();
  const members = directory.members || [];
  const summary = directory.summary || {};
  const linkedMembers = Number(summary.linked_members ?? members.filter((member) => (member.links || []).length).length);
  const uidLinks = Number(summary.uid_links ?? members.reduce((count, member) => count + (member.links || []).length, 0));
  const memberCount = Number(summary.members ?? members.length ?? 0);
  return {
    members,
    memberCount,
    linkedMembers,
    uidLinks,
    unlinkedMembers: Math.max(memberCount - linkedMembers, 0),
    activeMembers: Number(summary.active_members || 0),
    inactiveMembers: Number(summary.inactive_members || 0),
    unknownActivityMembers: Number(summary.unknown_activity_members || 0),
    matchedMembers: Number(summary.matched_members ?? members.filter((member) => member.current_match_status === "matched").length),
    membersNeedingCurrentMatch: Number(summary.members_needing_current_match ?? members.filter((member) => member.current_match_status !== "matched").length),
    historicalOnlyMembers: Number(summary.historical_only_members || 0),
    uidNotInReportMembers: Number(summary.uid_not_in_report_members || 0),
    vantageLinks: Number(summary.vantage_links || 0),
    puprimeLinks: Number(summary.puprime_links || 0),
  };
}

function overviewTradingRows() {
  if (!brokerReportsState.data && latestOverviewState.reportData) {
    brokerReportsState.data = latestOverviewState.reportData;
  }
  if (!brokerReportsState.data || !telegramMembersPageState.data) return [];
  return buildMatchedRecordsRows();
}

function overviewMatchSummary(rows, directorySummary) {
  const matchedRows = rows.filter((row) => tradingRowHasMatchStatus(row, "Matched"));
  const activeRows = matchedRows.filter((row) => row["Account Status"] === "Active");
  const inactiveRows = matchedRows.filter((row) => row["Account Status"] === "Inactive");
  const unknownRows = matchedRows.filter((row) => !["Active", "Inactive"].includes(row["Account Status"]));
  const historicalRows = rows.filter((row) => tradingRowHasMatchStatus(row, "Known from report history"));
  const missingReportRows = rows.filter((row) => tradingRowHasMatchStatus(row, "UID missing in report data"));
  const noTelegramRows = rows.filter((row) => tradingRowHasMatchStatus(row, "No Telegram link"));
  const linkingGapCount = noTelegramRows.length + directorySummary.membersNeedingCurrentMatch;
  return {
    matchedRows,
    activeRows,
    inactiveRows,
    unknownRows,
    historicalRows,
    missingReportRows,
    noTelegramRows,
    linkingGapCount,
    totalBalance: matchedRows.reduce((sum, row) => sum + Number(row["Total Balance"] || 0), 0),
    totalRebate: matchedRows.reduce((sum, row) => sum + Number(row["Total Rebate"] || 0), 0),
    rebateRows: matchedRows.reduce((sum, row) => sum + Number(row["Rebate Rows"] || 0), 0),
  };
}

function overviewMemberWatchlistCategories(directorySummary) {
  const members = directorySummary.members || [];
  return {
    needs_uid: members.filter((member) => member.current_match_status !== "matched"),
    inactive: members.filter((member) => member.activity_status === "inactive"),
    unknown: members.filter((member) => member.activity_status === "unknown"),
  };
}

function renderOverviewMemberWatchlist(directorySummary) {
  const categories = overviewMemberWatchlistCategories(directorySummary);
  const countIds = {
    needs_uid: "overviewWatchlistNeedsUidCount",
    inactive: "overviewWatchlistInactiveCount",
    unknown: "overviewWatchlistUnknownCount",
  };
  Object.entries(countIds).forEach(([category, id]) => {
    document.getElementById(id).textContent = Number(categories[category].length).toLocaleString();
  });
  if (!categories[overviewWatchlistState.category]?.length) {
    overviewWatchlistState.category = ["needs_uid", "inactive", "unknown"].find(
      (category) => categories[category].length
    ) || "needs_uid";
  }
  document.querySelectorAll("[data-overview-watchlist]").forEach((button) => {
    const category = button.dataset.overviewWatchlist;
    const active = category === overviewWatchlistState.category;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.disabled = categories[category].length === 0;
  });

  const rows = categories[overviewWatchlistState.category] || [];
  const target = document.getElementById("overviewMemberWatchlist");
  if (!rows.length) {
    target.innerHTML = '<li class="overview-watchlist-empty">No members require follow-up in this category.</li>';
    return;
  }
  target.innerHTML = rows.slice(0, 8).map((member) => {
    const name = member.display_name || member.username || `Telegram ID ${member.telegram_id}`;
    const username = member.username ? `@${String(member.username).replace(/^@/, "")}` : "No username";
    const groups = telegramMemberGroupsLabel(member);
    const memberLinks = member.links || [];
    let detail = memberLinks.length
      ? `${memberLinks.length.toLocaleString()} saved UID(s), but none match the current broker reports.`
      : "No broker UID is linked to this Telegram member.";
    let actionLabel = memberLinks.length ? "Resolve match" : "Link UID";
    let actionAttribute = memberLinks.length
      ? `data-overview-member-record="${escapeHtml(member.telegram_id)}" data-overview-record-status="needs_match"`
      : `data-overview-member-editor="${escapeHtml(member.telegram_id)}"`;
    if (overviewWatchlistState.category === "inactive") {
      detail = `${Number(member.account_count || 0).toLocaleString()} account(s) · ${money(member.total_equity || 0)} equity · last trade ${member.last_trade_date ? formatRebateDate(member.last_trade_date) : "not available"}`;
      actionLabel = "View records";
      actionAttribute = `data-overview-member-record="${escapeHtml(member.telegram_id)}" data-overview-record-status="inactive"`;
    } else if (overviewWatchlistState.category === "unknown") {
      detail = `${Number((member.links || []).length).toLocaleString()} linked UID(s) · no current account activity classification.`;
      actionLabel = (member.links || []).length ? "Review records" : "Link UID";
      actionAttribute = (member.links || []).length
        ? `data-overview-member-record="${escapeHtml(member.telegram_id)}" data-overview-record-status="all"`
        : `data-overview-member-editor="${escapeHtml(member.telegram_id)}"`;
    }
    return `<li class="overview-watchlist-row">
      <div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(username)} · ${escapeHtml(groups)}</small></div>
      <div><span>${escapeHtml(detail)}</span></div>
      <button class="overview-row-action primary" type="button" ${actionAttribute}>${escapeHtml(actionLabel)}</button>
    </li>`;
  }).join("");
}

function reportDatasetLoaded(statusReports, broker, datasets) {
  return datasets.some((dataset) => statusReports[broker]?.datasets?.[dataset]?.status === "manual_report");
}

function renderHelpfulOverview() {
  const reports = latestOverviewState.reportData || brokerReportsState.data || {};
  const combined = reports.combined || {};
  const rawMembers = combined.member_rows || [];
  const rawTotalBalance = rawMembers.reduce(
    (sum, row) => sum + Number(field(row, "Total Balance", "balance") || 0),
    0
  );
  const directorySummary = overviewDirectorySummary();
  const tradingRows = overviewTradingRows();
  const tradingUidRows = brokerReportsState.data && telegramMembersPageState.data
    ? buildMatchedUidRecords()
    : [];
  const matchSummary = overviewMatchSummary(tradingRows, directorySummary);
  const matchedCount = directorySummary.matchedMembers;
  const activeCount = directorySummary.activeMembers;
  const inactiveCount = directorySummary.inactiveMembers;
  const classifiedCount = activeCount + inactiveCount;
  const activeRate = classifiedCount ? (activeCount / classifiedCount) * 100 : 0;
  const rebateData = rebateInsightsState.data;
  const rebateView = rebateData?.combined || {};
  const rebateSummary = rebateView.summary || {};
  const topEarner = (rebateView.members || [])[0];
  const peakDay = rebateSummary.peak_day;
  const totalBalance = tradingRows.length ? matchSummary.totalBalance : rawTotalBalance;
  const totalRebate = tradingRows.length ? matchSummary.totalRebate : Number(rebateSummary.total_rebate || 0);
  const rebateRowCount = tradingRows.length ? matchSummary.rebateRows : Number(rebateSummary.transaction_rows || 0);
  const matchCoverage = directorySummary.memberCount
    ? (matchedCount / directorySummary.memberCount) * 100
    : 0;
  const groupRows = telegramMembersPageState.data?.groups || [];
  const groupCounts = Object.fromEntries(groupRows.map((row) => [row.group, Number(row.member_count || 0)]));
  const currentAccountCount = matchSummary.matchedRows.reduce(
    (sum, row) => sum + Number(row["Account Count"] || 0),
    0
  );

  document.getElementById("overviewMemberTotal").textContent = directorySummary.memberCount.toLocaleString();
  document.getElementById("overviewActiveMembers").textContent = activeCount.toLocaleString();
  document.getElementById("overviewInactiveMembers").textContent = matchSummary.linkingGapCount.toLocaleString();
  document.getElementById("overviewAccountTotal").textContent = matchedCount.toLocaleString();
  document.getElementById("overviewTotalBalance").textContent = formatCompactMoney(totalBalance);
  document.getElementById("overviewTotalRebate").textContent = formatCompactMoney(totalRebate);
  document.getElementById("overviewRebateRows").textContent = tradingRows.length
    ? `${rebateRowCount.toLocaleString()} matched rebate rows`
    : `${rebateRowCount.toLocaleString()} transaction rows`;
  document.getElementById("overviewActiveRate").textContent = `${activeRate.toFixed(1)}% of classified members`;
  document.getElementById("overviewMemberGroups").textContent = groupRows.length
    ? `Discussion ${Number(groupCounts.discussion || 0).toLocaleString()} · VIP ${Number(groupCounts.vip || 0).toLocaleString()}`
    : "From connected groups";
  document.getElementById("overviewLinkingGapDetail").textContent =
    `${matchSummary.noTelegramRows.length.toLocaleString()} unassigned broker UID(s) · ${directorySummary.membersNeedingCurrentMatch.toLocaleString()} member gap(s)`;
  document.getElementById("overviewMatchCoverage").textContent =
    `${matchCoverage.toFixed(1)}% current report coverage`;
  document.getElementById("overviewBalanceAccounts").textContent =
    `${currentAccountCount.toLocaleString()} current account(s)`;
  document.getElementById("overviewPriorityCoverage").textContent = `${matchCoverage.toFixed(1)}%`;
  document.getElementById("overviewPriorityUnassigned").textContent =
    matchSummary.noTelegramRows.length.toLocaleString();
  document.getElementById("overviewPriorityUnknown").textContent =
    directorySummary.unknownActivityMembers.toLocaleString();

  const priority = directorySummary.membersNeedingCurrentMatch
    ? {
        title: `${directorySummary.membersNeedingCurrentMatch.toLocaleString()} Telegram member(s) need a current broker match`,
        detail: `${directorySummary.unlinkedMembers.toLocaleString()} need a UID; ${directorySummary.historicalOnlyMembers.toLocaleString()} have only historical report evidence.`,
        action: "needs-match",
        label: "Resolve members",
      }
    : matchSummary.noTelegramRows.length
      ? {
          title: `${matchSummary.noTelegramRows.length.toLocaleString()} broker UID(s) need a Telegram owner`,
          detail: "Assign the current report records to existing Telegram members.",
          action: "no-telegram",
          label: "Assign UIDs",
        }
      : inactiveCount
        ? {
            title: `${inactiveCount.toLocaleString()} inactive member(s) need review`,
            detail: "Review their linked accounts before messaging or membership action.",
            action: "inactive",
            label: "Review members",
          }
        : {
            title: "Member linking and activity are up to date",
            detail: "No current member or broker UID linking gaps require action.",
            action: "brokers",
            label: "Open records",
          };
  document.getElementById("overviewPriorityTitle").textContent = priority.title;
  document.getElementById("overviewPriorityDetail").textContent = priority.detail;
  const priorityAction = document.getElementById("overviewPriorityAction");
  priorityAction.textContent = priority.label;
  priorityAction.dataset.overviewAction = priority.action;
  document.getElementById("overviewLinkingGapCard").dataset.overviewAction =
    directorySummary.membersNeedingCurrentMatch ? "needs-match" : "no-telegram";

  document.getElementById("overviewActivityTitle").textContent =
    `${activeCount.toLocaleString()} of ${classifiedCount.toLocaleString()} classified members active`;
  document.getElementById("overviewActivityPercent").textContent = `${activeRate.toFixed(1)}%`;
  document.getElementById("overviewActivityBar").style.width = `${Math.max(0, Math.min(100, activeRate)).toFixed(1)}%`;
  document.getElementById("overviewActivityActive").textContent = `${activeCount.toLocaleString()} active`;
  document.getElementById("overviewActivityInactive").textContent = `${inactiveCount.toLocaleString()} inactive · ${directorySummary.unknownActivityMembers.toLocaleString()} unknown`;

  const period = rebateSummary.date_start && rebateSummary.date_end
    ? `${formatRebateDate(rebateSummary.date_start)} – ${formatRebateDate(rebateSummary.date_end)}`
    : "No rebate period";
  document.getElementById("overviewPeriod").innerHTML = `<strong>Report period</strong> · ${escapeHtml(period)}`;
  document.getElementById("overviewRebatePeriod").textContent = period;

  const statusReports = latestOverviewState.reports || {};
  const importedDates = ["vantage", "puprime"].flatMap((broker) =>
    Object.values(statusReports[broker]?.datasets || {}).map((dataset) => dataset.imported_at).filter(Boolean)
  );
  const newestImport = importedDates.sort((a, b) => new Date(b) - new Date(a))[0];
  document.getElementById("overviewLastUpdated").textContent = newestImport
    ? `Reports imported ${formatOverviewDateTime(newestImport)}`
    : "No imported report timestamp";

  const concentration = Number(rebateSummary.top_five_share || 0);
  const attentionCandidates = [
    {
      status: matchSummary.missingReportRows.length ? "alert" : "good",
      title: matchSummary.missingReportRows.length
        ? `${matchSummary.missingReportRows.length.toLocaleString()} unverified saved UID(s)`
        : "Saved UIDs are verified",
      detail: matchSummary.missingReportRows.length
        ? "These values have never appeared as a UID or account number in any uploaded report."
        : `${matchedCount.toLocaleString()} member(s) have current report data and ${matchSummary.historicalRows.length.toLocaleString()} include historical UIDs.`,
      action: "missing-report",
      label: "Review",
      secondaryAction: "uploads",
      secondaryLabel: "Upload",
    },
    {
      status: matchSummary.noTelegramRows.length ? "watch" : "good",
      title: matchSummary.noTelegramRows.length
        ? `${matchSummary.noTelegramRows.length.toLocaleString()} broker UID(s) need Telegram member`
        : "Broker UIDs have Telegram coverage",
      detail: matchSummary.noTelegramRows.length
        ? "These UIDs appear in reports but are not assigned to a Telegram name yet."
        : "No unassigned broker report UIDs found.",
      action: "no-telegram",
      label: "Assign",
    },
    {
      status: directorySummary.membersNeedingCurrentMatch ? "watch" : "good",
      title: directorySummary.membersNeedingCurrentMatch
        ? `${directorySummary.membersNeedingCurrentMatch.toLocaleString()} current Telegram member(s) need a broker match`
        : "Current Telegram members are matched",
      detail: directorySummary.membersNeedingCurrentMatch
        ? `${directorySummary.unlinkedMembers.toLocaleString()} have no UID; ${directorySummary.historicalOnlyMembers.toLocaleString()} have only historical report evidence; ${directorySummary.uidNotInReportMembers.toLocaleString()} have UIDs absent from current reports.`
        : `${matchedCount.toLocaleString()} current member(s) have current broker-report coverage.`,
      action: "needs-match",
      label: "Resolve",
    },
    {
      status: inactiveCount ? "watch" : "good",
      title: inactiveCount
        ? `${inactiveCount.toLocaleString()} inactive Telegram member(s)`
        : "No inactive matched members",
      detail: inactiveCount
        ? "All linked accounts have both less than $50 equity and no trade within 30 days."
        : "Every classified matched member has at least one active account.",
      action: "inactive",
      label: "Review",
    },
    {
      status: directorySummary.unknownActivityMembers ? "watch" : "good",
      title: directorySummary.unknownActivityMembers
        ? `${directorySummary.unknownActivityMembers.toLocaleString()} member(s) have unknown activity`
        : "Member activity is classified",
      detail: directorySummary.unknownActivityMembers
        ? "These members need current broker account data before activity can be classified."
        : "Every current member with a UID has enough report data for activity classification.",
      action: "unknown-members",
      label: "Review",
    },
    {
      status: latestOverviewState.telegramConnected ? "good" : "alert",
      title: latestOverviewState.telegramConnected ? "Telegram connected" : "Telegram needs connection",
      detail: latestOverviewState.telegramConnected ? "Group scans, UID links and reviewed messaging are available." : "Connect Telegram before scanning groups or messaging.",
      action: "telegram",
      label: latestOverviewState.telegramConnected ? "Open" : "Connect",
    },
  ];
  const attention = attentionCandidates.filter((item) => item.status !== "good");
  if (!attention.length) {
    attention.push({
      status: "good",
      title: "No urgent issues",
      detail: "Current Telegram members, UID links and broker reports are aligned.",
      action: "brokers",
      label: "Open records",
    });
  }
  document.getElementById("overviewAttentionList").innerHTML = attention.map((item) => `
    <li class="overview-attention-item">
      <i class="overview-status-dot ${item.status}" aria-hidden="true"></i>
      <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail)}</span></div>
      <div class="overview-row-actions">
        <button class="overview-row-action ${item.status !== "good" ? "primary" : ""}" type="button" data-overview-action="${item.action}">${escapeHtml(item.label)}</button>
        ${item.secondaryAction ? `<button class="overview-row-action" type="button" data-overview-action="${item.secondaryAction}">${escapeHtml(item.secondaryLabel)}</button>` : ""}
      </div>
    </li>`).join("");

  const brokerRows = [
    ["vantage", "Vantage"],
    ["puprime", "PU Prime"],
  ].map(([key, label]) => {
    const brokerData = reports[key] || {};
    const scopedRows = tradingUidRows.filter((row) => row.Broker === label);
    const brokerMatchedRows = scopedRows.filter((row) => row["Match Status"] === "Matched");
    const brokerActiveRows = brokerMatchedRows.filter((row) => row["Account Status"] === "Active");
    const brokerInactiveRows = brokerMatchedRows.filter((row) => row["Account Status"] === "Inactive");
    const brokerReviewRows = scopedRows.filter((row) =>
      ["UID missing in report data", "No Telegram link"].includes(row["Match Status"])
    );
    const linkedRows = scopedRows.filter((row) => row["Telegram ID"]);
    const linkedFallback = key === "vantage" ? directorySummary.vantageLinks : directorySummary.puprimeLinks;
    const linkedCount = linkedRows.length || linkedFallback;
    const linkedMembers = new Set(linkedRows.map((row) => row["Telegram ID"])).size;
    const brokerBalance = brokerMatchedRows.reduce((sum, row) => sum + Number(row["Total Balance"] || 0), 0);
    const brokerRebate = brokerMatchedRows.reduce((sum, row) => sum + Number(row["Total Rebate"] || 0), 0);
    const accountRowCount = (brokerData.account_rows || []).length || (brokerData.accounts || []).length;
    const rebateRowCount = (brokerData.rebates || []).length;
    const accountLoaded = reportDatasetLoaded(statusReports, key, ["accounts", "funds", "opened_accounts"]);
    const rebateLoaded = reportDatasetLoaded(statusReports, key, ["rebates"]);
    const reportDetail = [
      accountLoaded ? `${accountRowCount.toLocaleString()} account rows` : "account report missing",
      rebateLoaded ? `${rebateRowCount.toLocaleString()} rebate rows` : "rebate report missing",
    ].join(" · ");
    return `
      <tr>
        <td class="overview-broker-name">${label}<small>${escapeHtml(reportDetail)}</small></td>
        <td>${linkedCount.toLocaleString()}<small>${linkedMembers.toLocaleString()} member(s)</small></td>
        <td>${brokerMatchedRows.length.toLocaleString()}</td>
        <td class="${brokerActiveRows.length ? "status-active" : ""}">${brokerActiveRows.length.toLocaleString()}</td>
        <td>${brokerInactiveRows.length.toLocaleString()}</td>
        <td>${escapeHtml(formatCompactMoney(brokerBalance))}</td>
        <td>${escapeHtml(formatCompactMoney(brokerRebate))}</td>
        <td class="${brokerReviewRows.length ? "status-inactive" : "status-active"}">${brokerReviewRows.length.toLocaleString()}</td>
      </tr>`;
  });
  document.getElementById("overviewBrokerRows").innerHTML = brokerRows.join("");

  document.getElementById("overviewNotional").textContent = formatCompactMoney(rebateSummary.notional_value);
  document.getElementById("overviewLots").textContent = formatCompactNumber(rebateSummary.total_lots);
  document.getElementById("overviewRebateMembers").textContent = Number(rebateSummary.member_count || 0).toLocaleString();
  document.getElementById("overviewTradingDays").textContent = Number(rebateSummary.trading_days || 0).toLocaleString();
  document.getElementById("overviewPeakDay").textContent = peakDay
    ? `${formatRebateDate(peakDay.Date)} · ${money(peakDay["Total Rebate"])}`
    : "—";
  document.getElementById("overviewTopEarner").textContent = topEarner
    ? `${topEarner.Name || topEarner["User ID"]} · ${money(topEarner["Total Rebate"])}`
    : "—";

  const healthRows = [
    overviewStatusRow(
      latestOverviewState.telegramConnected ? "good" : "alert",
      "Telegram",
      latestOverviewState.telegramConnected ? "Connected and ready" : "Not connected"
    ),
    overviewStatusRow(
      telegramMembersPageState.data ? (directorySummary.uidLinks ? "good" : "watch") : "watch",
      "Telegram member directory",
      telegramMembersPageState.data
        ? `${directorySummary.memberCount.toLocaleString()} group member(s) · ${directorySummary.uidLinks.toLocaleString()} linked UID(s) · ${directorySummary.unlinkedMembers.toLocaleString()} without UID`
        : "Loading saved Telegram member links"
    ),
    overviewStatusRow(
      matchSummary.linkingGapCount || matchSummary.missingReportRows.length ? "watch" : matchedCount ? "good" : "watch",
      "Trading record matches",
      `${matchedCount.toLocaleString()} current member(s) matched · ${directorySummary.membersNeedingCurrentMatch.toLocaleString()} member gap(s) · ${matchSummary.noTelegramRows.length.toLocaleString()} broker UID(s) unassigned · ${matchSummary.missingReportRows.length.toLocaleString()} saved UID(s) unverified`
    ),
    ...["vantage", "puprime"].map((key) => {
      const brokerStatus = statusReports[key] || {};
      const hasAccounts = reportDatasetLoaded(statusReports, key, ["accounts", "funds", "opened_accounts"]);
      const hasRebates = brokerStatus.datasets?.rebates?.status === "manual_report";
      const name = key === "vantage" ? "Vantage reports" : "PU Prime reports";
      const detail = [hasAccounts ? "IB account loaded" : "IB account missing", hasRebates ? "rebate loaded" : "rebate missing"].join(" · ");
      return overviewStatusRow(hasAccounts && hasRebates ? "good" : "watch", name, detail);
    }),
    overviewStatusRow(
      concentration >= 60 ? "watch" : concentration ? "good" : "watch",
      "Rebate concentration",
      concentration ? `Top five earners hold ${concentration.toFixed(1)}% of rebate.` : "Upload rebate reports to calculate concentration."
    ),
  ];
  document.getElementById("overviewHealthList").innerHTML = healthRows.join("");
  renderOverviewMemberWatchlist(directorySummary);
}

function runOverviewAction(action) {
  const recordStatusByAction = {
    active: "active",
    inactive: "inactive",
    matched: "matched",
    "needs-match": "needs_match",
    "missing-report": "missing_report",
    "no-telegram": "no_telegram",
    brokers: "all",
  };
  if (recordStatusByAction[action]) {
    matchedRecordsState.broker = "all";
    matchedRecordsState.status = recordStatusByAction[action];
    matchedRecordsState.tradeWindow = "all";
    matchedRecordsState.sort = "priority";
    matchedRecordsState.search = "";
    document.getElementById("matchedRecordsBrokerFilter").value = "all";
    document.getElementById("matchedRecordsStatusFilter").value = recordStatusByAction[action];
    document.getElementById("matchedRecordsTradeFilter").value = "all";
    document.getElementById("matchedRecordsSort").value = "priority";
    document.getElementById("matchedRecordsSearch").value = "";
    showDashboardPage("matched-records");
    return;
  }
  if (action === "telegram-members") {
    telegramMembersPageState.search = "";
    telegramMembersPageState.broker = "all";
    telegramMembersPageState.status = "unlinked";
    document.getElementById("telegramMembersSearch").value = "";
    document.getElementById("telegramMembersBrokerFilter").value = "all";
    document.getElementById("telegramMembersStatusFilter").value = "unlinked";
    showDashboardPage("telegram-members");
    setTelegramMembersStatus("Showing Telegram members who still need a UID.");
    return;
  }
  if (action === "telegram-all" || action === "unknown-members") {
    const status = action === "unknown-members" ? "unknown" : "all";
    telegramMembersPageState.search = "";
    telegramMembersPageState.broker = "all";
    telegramMembersPageState.status = status;
    document.getElementById("telegramMembersSearch").value = "";
    document.getElementById("telegramMembersBrokerFilter").value = "all";
    document.getElementById("telegramMembersStatusFilter").value = status;
    showDashboardPage("telegram-members");
    setTelegramMembersStatus(status === "unknown"
      ? "Showing members whose activity needs current account data."
      : "Showing all current Telegram group members.");
    return;
  }
  const pageByAction = {
    rebates: "rebate-insights",
    uploads: "uploads",
    telegram: "telegram",
  };
  showDashboardPage(pageByAction[action] || "overview");
}

document.querySelector(".helpful-overview").addEventListener("click", (event) => {
  const watchlistTab = event.target.closest("[data-overview-watchlist]");
  if (watchlistTab) {
    overviewWatchlistState.category = watchlistTab.dataset.overviewWatchlist;
    renderHelpfulOverview();
    return;
  }
  const memberEditor = event.target.closest("[data-overview-member-editor]");
  if (memberEditor) {
    openTelegramMemberEditor(memberEditor.dataset.overviewMemberEditor);
    return;
  }
  const memberRecord = event.target.closest("[data-overview-member-record]");
  if (memberRecord) {
    matchedRecordsState.broker = "all";
    matchedRecordsState.status = memberRecord.dataset.overviewRecordStatus || "all";
    matchedRecordsState.tradeWindow = "all";
    matchedRecordsState.sort = "priority";
    matchedRecordsState.search = memberRecord.dataset.overviewMemberRecord || "";
    document.getElementById("matchedRecordsBrokerFilter").value = "all";
    document.getElementById("matchedRecordsStatusFilter").value = matchedRecordsState.status;
    document.getElementById("matchedRecordsTradeFilter").value = "all";
    document.getElementById("matchedRecordsSort").value = "priority";
    document.getElementById("matchedRecordsSearch").value = matchedRecordsState.search;
    showDashboardPage("matched-records");
    return;
  }
  const button = event.target.closest("[data-overview-action]");
  if (button) runOverviewAction(button.dataset.overviewAction);
});

function formatCompactMoney(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: Math.abs(amount) >= 100000 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatCompactNumber(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", {
    notation: Math.abs(amount) >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatRebateDate(value) {
  if (!value) return "—";
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

function renderRebateTrend(data, selected) {
  const palette = { vantage: "#62d89b", puprime: "#73bdf2" };
  const availableSeries = selected === "combined"
    ? [
        { key: "vantage", label: "Vantage", rows: data.brokers.vantage.daily || [] },
        { key: "puprime", label: "PU Prime", rows: data.brokers.puprime.daily || [] },
      ]
    : [{
        key: selected,
        label: selected === "vantage" ? "Vantage" : "PU Prime",
        rows: data.brokers[selected].daily || [],
      }];
  const target = document.getElementById("rebateTrendChart");
  const legend = document.getElementById("rebateTrendLegend");
  const hiddenSeries = selected === "combined"
    ? new Set(rebateInsightsState.hiddenTrendSeries)
    : new Set();
  let series = availableSeries.filter((item) => !hiddenSeries.has(item.key));
  if (!series.length) {
    rebateInsightsState.hiddenTrendSeries = [];
    hiddenSeries.clear();
    series = [...availableSeries];
  }
  legend.innerHTML = availableSeries.map((item) =>
    `<button type="button" data-rebate-trend-series="${item.key}" aria-pressed="${String(!hiddenSeries.has(item.key))}"${availableSeries.length === 1 ? " disabled" : ""}><i style="background:${palette[item.key]}"></i>${escapeHtml(item.label)}</button>`
  ).join("");
  legend.querySelectorAll("[data-rebate-trend-series]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.rebateTrendSeries;
      const hidden = new Set(rebateInsightsState.hiddenTrendSeries);
      const visibleCount = availableSeries.filter((item) => !hidden.has(item.key)).length;
      if (hidden.has(key)) hidden.delete(key);
      else if (visibleCount > 1) hidden.add(key);
      rebateInsightsState.hiddenTrendSeries = [...hidden];
      renderRebateTrend(data, selected);
    });
  });

  const dates = [...new Set(availableSeries.flatMap((item) => item.rows.map((row) => row.Date)))].sort();
  if (!dates.length) {
    target.innerHTML = '<div class="rebate-rank-empty">No dated rebate transactions.</div>';
    return;
  }

  const width = 900;
  const height = 270;
  const padding = { left: 64, right: 22, top: 18, bottom: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const lookups = series.map((item) => ({
    ...item,
    values: Object.fromEntries(item.rows.map((row) => [row.Date, Number(row["Total Rebate"] || 0)])),
  }));
  const maxValue = Math.max(1, ...lookups.flatMap((item) => Object.values(item.values)));
  const x = (index) => padding.left + (dates.length === 1 ? plotWidth / 2 : (index / (dates.length - 1)) * plotWidth);
  const y = (value) => padding.top + plotHeight - (Number(value || 0) / maxValue) * plotHeight;

  const grid = Array.from({ length: 5 }, (_, index) => {
    const value = maxValue * (1 - index / 4);
    const position = padding.top + (plotHeight * index) / 4;
    return `
      <line x1="${padding.left}" y1="${position}" x2="${width - padding.right}" y2="${position}" stroke="#28303c" stroke-width="1" />
      <text x="${padding.left - 10}" y="${position + 4}" text-anchor="end" fill="#7f899b" font-size="10">${escapeHtml(formatCompactMoney(value))}</text>`;
  }).join("");
  const lines = lookups.map((item) => {
    const points = dates.map((day, index) => `${x(index)},${y(item.values[day] || 0)}`).join(" ");
    const dots = dates.map((day, index) => {
      const amount = item.values[day] || 0;
      return `<circle cx="${x(index)}" cy="${y(amount)}" r="3" fill="${palette[item.key]}" stroke="#10141d" stroke-width="2"><title>${escapeHtml(item.label)} · ${escapeHtml(formatRebateDate(day))}: ${escapeHtml(money(amount))}</title></circle>`;
    }).join("");
    return `<polyline points="${points}" fill="none" stroke="${palette[item.key]}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />${dots}`;
  }).join("");
  const focusDots = lookups.map((item) =>
    `<circle data-rebate-trend-dot="${item.key}" r="5" fill="${palette[item.key]}" stroke="#10141d" stroke-width="2" opacity="0" pointer-events="none" />`
  ).join("");
  const hitAreas = dates.map((day, index) => {
    const step = dates.length === 1 ? plotWidth : plotWidth / (dates.length - 1);
    const start = dates.length === 1 ? padding.left : Math.max(padding.left, x(index) - step / 2);
    const end = dates.length === 1 ? width - padding.right : Math.min(width - padding.right, x(index) + step / 2);
    const pointSummary = lookups.map((item) =>
      `${item.label} ${money(item.values[day] || 0)}`
    ).join(", ");
    return `<rect class="rebate-chart-hit-area" data-rebate-trend-index="${index}" x="${start}" y="${padding.top}" width="${Math.max(1, end - start)}" height="${plotHeight}" fill="transparent" tabindex="0" aria-label="${escapeHtml(`${formatRebateDate(day)}: ${pointSummary}`)}" />`;
  }).join("");
  const labelIndexes = [...new Set([0, Math.floor((dates.length - 1) / 2), dates.length - 1])];
  const labels = labelIndexes.map((index) =>
    `<text x="${x(index)}" y="${height - 10}" text-anchor="middle" fill="#7f899b" font-size="10">${escapeHtml(formatRebateDate(dates[index]).replace(/\s\d{4}$/, ""))}</text>`
  ).join("");
  target.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Daily rebate trend">
      ${grid}${lines}${labels}
      <line class="rebate-chart-guide" x1="0" y1="${padding.top}" x2="0" y2="${padding.top + plotHeight}" stroke="#d7dce6" stroke-width="1" stroke-dasharray="3 4" opacity="0" pointer-events="none" />
      ${focusDots}${hitAreas}
    </svg>
    <div class="rebate-chart-tooltip" role="status" aria-live="polite"></div>`;

  const svg = target.querySelector("svg");
  const guide = target.querySelector(".rebate-chart-guide");
  const tooltip = target.querySelector(".rebate-chart-tooltip");
  const showPoint = (index) => {
    const safeIndex = Math.max(0, Math.min(dates.length - 1, Number(index)));
    const day = dates[safeIndex];
    const pointX = x(safeIndex);
    guide.setAttribute("x1", pointX);
    guide.setAttribute("x2", pointX);
    guide.setAttribute("opacity", "1");
    lookups.forEach((item) => {
      const dot = target.querySelector(`[data-rebate-trend-dot="${item.key}"]`);
      if (!dot) return;
      dot.setAttribute("cx", pointX);
      dot.setAttribute("cy", y(item.values[day] || 0));
      dot.setAttribute("opacity", "1");
    });
    tooltip.innerHTML = `<strong>${escapeHtml(formatRebateDate(day))}</strong>${lookups.map((item) =>
      `<span><i style="background:${palette[item.key]}"></i>${escapeHtml(item.label)} ${escapeHtml(money(item.values[day] || 0))}</span>`
    ).join("")}`;
    tooltip.classList.add("visible");
    const targetRect = target.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const pixelX = (pointX / width) * svgRect.width + svgRect.left - targetRect.left;
    const tooltipWidth = tooltip.offsetWidth;
    tooltip.style.left = `${Math.max(10, Math.min(targetRect.width - tooltipWidth - 10, pixelX - tooltipWidth / 2))}px`;
  };
  const hidePoint = () => {
    guide.setAttribute("opacity", "0");
    target.querySelectorAll("[data-rebate-trend-dot]").forEach((dot) => dot.setAttribute("opacity", "0"));
    tooltip.classList.remove("visible");
  };
  target.querySelectorAll("[data-rebate-trend-index]").forEach((area) => {
    const showArea = () => showPoint(area.dataset.rebateTrendIndex);
    area.addEventListener("pointerenter", showArea);
    area.addEventListener("pointermove", showArea);
    area.addEventListener("pointerdown", showArea);
    area.addEventListener("focus", showArea);
  });
  target.addEventListener("pointerleave", hidePoint);
  target.addEventListener("focusout", (event) => {
    if (!target.contains(event.relatedTarget)) hidePoint();
  });
}

function renderRebateBrokerComparison(data) {
  const combinedTotal = Number(data.combined.summary.total_rebate || 0);
  const target = document.getElementById("rebateBrokerComparison");
  target.innerHTML = ["vantage", "puprime"].map((broker) => {
    const summary = data.brokers[broker].summary;
    const label = broker === "vantage" ? "Vantage" : "PU Prime";
    const share = combinedTotal ? (Number(summary.total_rebate || 0) / combinedTotal) * 100 : 0;
    return `
      <div class="rebate-broker-row ${broker}">
        <div class="rebate-broker-row-head"><strong>${label}</strong><span>${escapeHtml(money(summary.total_rebate))}</span></div>
        <div class="rebate-progress"><i style="width:${Math.max(0, Math.min(100, share)).toFixed(2)}%"></i></div>
        <div class="rebate-broker-stats">
          <span><strong>${share.toFixed(1)}%</strong> rebate share</span>
          <span><strong>${summary.member_count}</strong> members</span>
          <span><strong>${escapeHtml(formatCompactMoney(summary.notional_value))}</strong> notional</span>
          <span><strong>${escapeHtml(money(summary.rebate_per_million))}</strong> per $1M</span>
        </div>
      </div>`;
  }).join("");
}

function renderRebateRankList(targetId, rows, labelField, limit = 8) {
  const target = document.getElementById(targetId);
  const visible = (rows || []).filter((row) => Number(row["Total Rebate"] || 0) > 0).slice(0, limit);
  if (!visible.length) {
    target.innerHTML = '<div class="rebate-rank-empty">No rebate value available.</div>';
    return;
  }
  const maxValue = Math.max(...visible.map((row) => Number(row["Total Rebate"] || 0)), 1);
  target.innerHTML = visible.map((row) => {
    const amount = Number(row["Total Rebate"] || 0);
    const width = Math.max(0, Math.min(100, (amount / maxValue) * 100));
    const supporting = [
      `${Number(row["Share %"] || 0).toFixed(1)}% share`,
      `${formatCompactNumber(row["Total Lots"])} lots`,
      Number(row.Members || 0) ? `${row.Members} members` : "",
    ].filter(Boolean).join(" · ");
    return `
      <div class="rebate-rank-item">
        <div class="rebate-rank-head"><strong title="${escapeHtml(row[labelField])}">${escapeHtml(row[labelField])}</strong><span>${escapeHtml(money(amount))}</span></div>
        <div class="rebate-progress"><i style="width:${width.toFixed(2)}%"></i></div>
        <div class="rebate-rank-meta"><span>${escapeHtml(supporting)}</span><span>${escapeHtml(formatCompactMoney(row["Notional Value"]))} notional</span></div>
      </div>`;
  }).join("");
}

function renderRebateQuality(quality) {
  const difference = Number(quality.summary_difference || 0);
  const reconciliation = Math.abs(difference) <= 0.05
    ? "Matched"
    : `${difference > 0 ? "+" : ""}${money(difference)}`;
  document.getElementById("rebateDataQuality").innerHTML = `
    <div><span>Summary reconciliation</span><strong>${escapeHtml(reconciliation)}</strong></div>
    <div><span>Campaign attribution</span><strong>${Number(quality.campaign_attribution_pct || 0).toFixed(1)}%</strong></div>
    <div><span>Missing UID rows</span><strong>${Number(quality.missing_uid_rows || 0).toLocaleString()}</strong></div>
    <div><span>Missing instruments</span><strong>${Number(quality.missing_instrument_rows || 0).toLocaleString()}</strong></div>`;
}

function renderRebateInsights() {
  const data = rebateInsightsState.data;
  if (!data) return;
  const selected = rebateInsightsState.selected;
  const view = selected === "combined" ? data.combined : data.brokers[selected];
  const summary = view.summary || {};
  const hasData = Number(summary.transaction_rows || 0) > 0;
  document.getElementById("rebateInsightsEmpty").classList.toggle("hidden", hasData);
  document.getElementById("rebateInsightsContent").classList.toggle("hidden", !hasData);
  if (!hasData) return;

  const topEarner = (view.members || [])[0];
  const peakDay = summary.peak_day;
  document.getElementById("insightTotalRebate").textContent = formatCompactMoney(summary.total_rebate);
  document.getElementById("insightPeakDay").textContent = peakDay
    ? `${formatRebateDate(peakDay.Date)} · ${money(peakDay["Total Rebate"])}`
    : "No peak day";
  document.getElementById("insightNotional").textContent = formatCompactMoney(summary.notional_value);
  document.getElementById("insightRebateRate").textContent = `${money(summary.rebate_per_million)} per $1M`;
  document.getElementById("insightLots").textContent = formatCompactNumber(summary.total_lots);
  document.getElementById("insightTradingDays").textContent = `${summary.trading_days || 0} trading days`;
  document.getElementById("insightMembers").textContent = Number(summary.member_count || 0).toLocaleString();
  document.getElementById("insightAccounts").textContent = `${Number(summary.account_count || 0).toLocaleString()} accounts`;
  document.getElementById("insightAverageMember").textContent = money(summary.average_rebate_per_member);
  document.getElementById("insightTransactions").textContent = `${Number(summary.transaction_rows || 0).toLocaleString()} transaction rows`;
  document.getElementById("insightConcentration").textContent = `${Number(summary.top_five_share || 0).toFixed(1)}%`;
  document.getElementById("insightTopEarner").textContent = topEarner
    ? `${topEarner.Name || topEarner["User ID"]} · ${money(topEarner["Total Rebate"])}`
    : "No earners";
  document.getElementById("rebateEarnerCount").textContent = `${summary.member_count || 0} members`;
  document.getElementById("rebateInsightDateRange").textContent =
    `${formatRebateDate(summary.date_start)} – ${formatRebateDate(summary.date_end)}`;
  const sources = selected === "combined"
    ? [data.brokers.vantage.source?.filename, data.brokers.puprime.source?.filename].filter(Boolean)
    : [data.brokers[selected].source?.filename].filter(Boolean);
  document.getElementById("rebateInsightSource").textContent = sources.join(" + ") || "Imported rebate data";

  renderRebateTrend(data, selected);
  renderRebateBrokerComparison(data);
  renderRebateRankList("rebateAssetClassBars", view.asset_classes, "Asset Class");
  renderRebateRankList("rebateInstrumentBars", view.instruments, "Instrument");
  renderRebateRankList("rebateAccountTypeBars", view.account_types, "Account Type", 6);
  renderRebateRankList("rebateCampaignBars", view.campaigns, "Campaign", 6);
  renderRebateQuality(view.data_quality || {});
  renderDataGrid("rebateMemberTable", view.members || [], "No rebate earners found.");
}

async function loadRebateInsights(force = false) {
  if (rebateInsightsState.loading) return;
  if (rebateInsightsState.data && !force) {
    renderRebateInsights();
    renderHelpfulOverview();
    return;
  }
  rebateInsightsState.loading = true;
  document.getElementById("rebateInsightSource").textContent = "Loading rebate analytics…";
  try {
    rebateInsightsState.data = await requestJson("/api/reports/rebate-insights", { method: "GET" });
    renderRebateInsights();
    renderHelpfulOverview();
  } catch (error) {
    document.getElementById("rebateInsightsEmpty").classList.remove("hidden");
    document.getElementById("rebateInsightsContent").classList.add("hidden");
    document.getElementById("rebateInsightsEmpty").textContent = error.message;
  } finally {
    rebateInsightsState.loading = false;
  }
}

document.querySelectorAll("[data-rebate-broker]").forEach((button) => {
  button.addEventListener("click", () => {
    rebateInsightsState.selected = button.dataset.rebateBroker;
    document.querySelectorAll("[data-rebate-broker]").forEach((option) => {
      const active = option.dataset.rebateBroker === rebateInsightsState.selected;
      option.classList.toggle("active", active);
      option.setAttribute("aria-selected", String(active));
    });
    renderRebateInsights();
  });
});

function renderDashboard(data) {
  latestOverviewState.dashboard = data;
  renderHelpfulOverview();
}

async function loadDashboard() {
  try {
    const data = await requestJson("/api/cache", { method: "GET" });
    renderDashboard(data);
    await loadReportData();
  } catch (error) {
    document.getElementById("dashboardMessage").textContent = error.message;
  }
}

async function refreshDashboard() {
  const message = document.getElementById("dashboardMessage");
  message.textContent = "Updating dashboard data...";
  try {
    const data = await requestJson("/api/sync", {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderDashboard(data);
    await loadReportData();
    message.textContent = `Updated ${new Date(data.last_synced_at).toLocaleString()}.`;
  } catch (error) {
    message.textContent = error.message;
  }
}

async function importReport(broker, section, file) {
  const message = document.getElementById("dashboardMessage");
  message.textContent = `Importing ${broker === "vantage" ? "Vantage" : "PU Prime"} report...`;
  const response = await fetch(
    `/api/reports/${broker}?section=${section}&filename=${encodeURIComponent(file.name)}`,
    { method: "POST", credentials: "include", body: await file.arrayBuffer() }
  );
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Report import failed.");
  const detail = Object.entries(result.datasets || {}).map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`).join(", ");
  message.textContent = `Imported ${detail} from ${result.filename}${result.skipped_count ? `; skipped ${result.skipped_count} invalid rows` : ""}.`;
  await loadConnections();
  if (result.datasets && result.datasets.accounts) {
    await refreshDashboard();
  } else {
    await loadReportData();
  }
  if (section === "rebate") {
    rebateInsightsState.data = null;
    await loadRebateInsights(true);
  }
  return result;
}

const telegramMemberFile = document.getElementById("telegramMemberFile");
const telegramMemberChoose = document.getElementById("telegramMemberChoose");
const telegramMemberRemove = document.getElementById("telegramMemberRemove");
const telegramMemberImportMessage = document.getElementById("telegramMemberImportMessage");

telegramMemberChoose.addEventListener("click", () => telegramMemberFile.click());
telegramMemberFile.addEventListener("change", async () => {
  const file = telegramMemberFile.files[0];
  telegramMemberFile.value = "";
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    telegramMemberImportMessage.textContent = "Choose a .csv file.";
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    telegramMemberImportMessage.textContent = "The member CSV must be 5 MB or smaller.";
    return;
  }
  telegramMemberChoose.disabled = true;
  telegramMemberImportMessage.textContent = `Loading ${file.name}…`;
  try {
    const response = await fetch(
      `/api/telegram/members/import?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        credentials: "include",
        body: await file.arrayBuffer(),
      }
    );
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Member import failed.");
    telegramMemberImportMessage.textContent =
      `${result.message}${result.skipped_count ? ` ${result.skipped_count} invalid or duplicate row(s) skipped.` : ""} No Telegram messages were sent.`;
    await loadConnections();
    await refreshDashboard();
  } catch (error) {
    telegramMemberImportMessage.textContent = error.message;
  } finally {
    telegramMemberChoose.disabled = false;
  }
});

telegramMemberRemove.addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Remove the imported Telegram member CSV data?\n\n" +
    "This does not remove anyone from Telegram and does not send a message."
  );
  if (!confirmed) return;
  telegramMemberRemove.disabled = true;
  telegramMemberImportMessage.textContent = "Removing imported member data…";
  try {
    const result = await requestJson("/api/telegram/members/import", { method: "DELETE" });
    telegramMemberImportMessage.textContent = `${result.message} No Telegram messages were sent.`;
    await loadConnections();
    await refreshDashboard();
  } catch (error) {
    telegramMemberImportMessage.textContent = error.message;
    telegramMemberRemove.disabled = false;
  }
});

const reportQueues = {};
const reportQueueLocks = {};
const reportSectionConfig = {
  ib_account_report: {
    keySuffix: "IbAccountReport",
    label: "IB Account Report",
  },
  rebate: {
    keySuffix: "Rebate",
    label: "Rebate Reports",
  },
};

function queueKey(broker, section) {
  return `${broker}${reportSectionConfig[section].keySuffix}`;
}

function fileIdentity(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validateQueuedFile(file, section) {
  const extension = file.name.toLowerCase().split(".").pop();
  const allowed = section === "rebate" ? ["xlsx", "csv"] : ["xlsx", "csv", "json"];
  if (!allowed.includes(extension)) {
    return `Unsupported file type. Choose ${allowed.map((value) => "." + value).join(", ")}.`;
  }
  if (file.size > 10 * 1024 * 1024) {
    return "File is larger than the 10 MB upload limit.";
  }
  if (!file.size) return "The selected file is empty.";
  return "";
}

function renderReportQueue(broker, section) {
  const key = queueKey(broker, section);
  const queue = reportQueues[key];
  const locked = Boolean(reportQueueLocks[key]);
  const target = document.getElementById(`${key}Queue`);
  const uploadButton = document.getElementById(`${key}Upload`);
  const clearButton = document.getElementById(`${key}Clear`);
  if (!queue.length) {
    target.innerHTML = "";
    uploadButton.disabled = true;
    clearButton.disabled = true;
    return;
  }
  target.innerHTML = queue.map((item) => `
    <div class="queued-file">
      <div class="queued-file-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</div>
      ${item.status === "uploading" ? '<span class="status">Uploading…</span>' :
        item.status === "success" ? '<span class="status status-active">Imported</span>' :
        locked ? '<span class="status">Waiting…</span>' :
        `<button class="remove-file-button" data-file-id="${escapeHtml(item.id)}" type="button">Remove</button>`}
      <div class="queued-file-meta">${formatFileSize(item.file.size)} · ${item.file.name.split(".").pop().toUpperCase()}</div>
      ${item.message ? `<div class="queued-file-result ${item.status === "success" ? "success" : "error"}">${escapeHtml(item.message)}</div>` : ""}
    </div>
  `).join("");
  target.querySelectorAll(".remove-file-button").forEach((button) => {
    button.addEventListener("click", () => {
      reportQueues[key] = reportQueues[key].filter((item) => item.id !== button.dataset.fileId);
      renderReportQueue(broker, section);
    });
  });
  uploadButton.disabled = locked || !queue.some((item) => item.status === "ready");
  clearButton.disabled = locked;
}

for (const broker of ["vantage", "puprime"]) {
  for (const section of Object.keys(reportSectionConfig)) {
    const key = queueKey(broker, section);
    reportQueues[key] = [];
    reportQueueLocks[key] = false;
    const input = document.getElementById(`${key}File`);
    const chooseButton = document.getElementById(`${key}Button`);
    const uploadButton = document.getElementById(`${key}Upload`);
    const clearButton = document.getElementById(`${key}Clear`);

    chooseButton.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      const existing = new Set(reportQueues[key].map((item) => item.id));
      for (const file of input.files) {
        const id = fileIdentity(file);
        if (existing.has(id)) continue;
        const validationError = validateQueuedFile(file, section);
        reportQueues[key].push({
          id,
          file,
          status: validationError ? "error" : "ready",
          message: validationError,
        });
        existing.add(id);
      }
      input.value = "";
      renderReportQueue(broker, section);
    });

    clearButton.addEventListener("click", () => {
      reportQueues[key] = [];
      renderReportQueue(broker, section);
    });

    document.getElementById(`${key}RemoveData`).addEventListener("click", async (event) => {
      const brokerName = broker === "vantage" ? "Vantage" : "PU Prime";
      const sectionName = reportSectionConfig[section].label;
      const confirmed = window.confirm(
        `Remove all imported ${sectionName} data from ${brokerName}?\n\n` +
        "This clears the displayed rows and totals. A recoverable server backup will be kept."
      );
      if (!confirmed) return;
      const button = event.currentTarget;
      button.disabled = true;
      document.getElementById("dashboardMessage").textContent =
        `Removing imported ${sectionName} data from ${brokerName}…`;
      try {
        const result = await requestJson(
          `/api/reports/${broker}?section=${section}`,
          { method: "DELETE" }
        );
        reportQueues[key] = [];
        renderReportQueue(broker, section);
        await loadConnections();
        await loadReportData();
        rebateInsightsState.data = null;
        await refreshDashboard();
        document.getElementById("dashboardMessage").textContent =
          `${result.message} The previous data was moved to recoverable server trash.`;
      } catch (error) {
        document.getElementById("dashboardMessage").textContent = error.message;
        button.disabled = false;
      }
    });

    uploadButton.addEventListener("click", async () => {
      const ready = reportQueues[key].filter((item) => item.status === "ready");
      if (!ready.length) return;
      reportQueueLocks[key] = true;
      chooseButton.disabled = true;
      uploadButton.disabled = true;
      clearButton.disabled = true;
      let imported = 0;
      for (const item of ready) {
        item.status = "uploading";
        item.message = "";
        renderReportQueue(broker, section);
        try {
          const result = await importReport(broker, section, item.file);
          const details = Object.entries(result.datasets || {})
            .map(([name, count]) => `${count} ${name.replaceAll("_", " ")}`)
            .join(", ");
          item.status = "success";
          item.message = details ? `Accepted: ${details}.` : "File imported successfully.";
          imported += 1;
        } catch (error) {
          item.status = "error";
          item.message = error.message || "This file does not match the selected report section.";
        }
        renderReportQueue(broker, section);
      }
      chooseButton.disabled = false;
      reportQueueLocks[key] = false;
      clearButton.disabled = false;
      document.getElementById("dashboardMessage").textContent =
        `Finished ${ready.length} file(s): ${imported} imported, ${ready.length - imported} need attention.`;
      await loadConnections();
      await loadReportData();
      rebateInsightsState.data = null;
      renderReportQueue(broker, section);
    });
  }
}

let outreachTemplates = {};
let previewedRecipients = [];
let selectedRecipientSet = new Set();
let filteredRecipientRows = [];
let telegramWorkspaceData = null;
let telegramDiagnostics = null;
let outreachHistoryRows = [];
let filteredOutreachHistoryRows = [];
let replyDirectoryRows = [];
let filteredReplyDirectoryRows = [];
let telegramAccountLinkData = null;
let filteredTelegramMemberAssignments = [];
let filteredTelegramAccountLinkRows = [];
let selectedTelegramLinkCandidates = new Set();
let manualTelegramLinkMember = null;
let telegramAccountSearchTimer = null;

function downloadTelegramCsv(filename, rows) {
  if (!rows.length) return;
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const csv = [
    columns.map(csvCell).join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
  ].join("\n");
  const link = document.createElement("a");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function renderTelegramWorkspace() {
  const data = telegramWorkspaceData || {};
  const outreach = data.outreach || {};
  const replies = data.replies || {};
  const accountLinks = data.account_links?.summary || {};
  document.getElementById("telegramMetricSent").textContent = Number(outreach.sent_total || 0).toLocaleString();
  document.getElementById("telegramMetricSentRecent").textContent =
    `${Number(outreach.sent_last_7_days || 0).toLocaleString()} this week`;
  document.getElementById("telegramMetricRecipients").textContent =
    Number(outreach.unique_recipients || 0).toLocaleString();
  document.getElementById("telegramMetricReplies").textContent = Number(replies.total || 0).toLocaleString();
  document.getElementById("telegramMetricPending").textContent =
    `${Number(replies.pending || 0).toLocaleString()} pending`;
  document.getElementById("telegramMetricLinked").textContent =
    Number(accountLinks.linked_members ?? accountLinks.linked ?? replies.linked ?? 0).toLocaleString();

  const groupSummary = outreach.groups || {};
  for (const groupName of ["discussion", "vip"]) {
    const target = document.querySelector(`[data-workspace-group="${groupName}"]`);
    const group = groupSummary[groupName] || {};
    const diagnostic = (telegramDiagnostics?.groups || []).find((row) => row.group === groupName);
    const status = diagnostic?.status === "error"
      ? "Needs attention"
      : diagnostic
        ? "Ready"
        : group.initialized
          ? "Tracking active"
          : "Not tracked";
    const details = diagnostic?.status === "error"
      ? diagnostic.error
      : diagnostic
        ? `${diagnostic.resolved_group_name} · ${diagnostic.discoverable_recipients} discoverable`
        : group.initialized
          ? `${group.baseline_count || 0} members in baseline`
          : "Run Check groups, then start tracking if needed";
    target.querySelector("strong").textContent = status;
    target.querySelector("small").textContent = details;
    target.querySelector("strong").classList.toggle("telegram-warning-text", status === "Needs attention");
  }

  document.getElementById("telegramGroupsCheckedAt").textContent = telegramDiagnostics
    ? "Checked just now"
    : "Saved tracking state";
  let nextStep = "Connect Telegram to preview recipients and scan replies.";
  if (telegramAuthorizationVerified) {
    const diagnosticErrors = (telegramDiagnostics?.groups || []).some((group) => group.status === "error");
    const trackingCount = Object.values(groupSummary).filter((group) => group.initialized).length;
    if (!telegramDiagnostics) nextStep = "Run Check groups to confirm Discussion and VIP access.";
    else if (diagnosticErrors) nextStep = "Review the group warning, then confirm the connected account belongs to that group.";
    else if (!trackingCount) nextStep = "Start tracking before using the New members audience.";
    else if (Number(accountLinks.suggested || 0) + Number(accountLinks.needs_review || 0)) {
      const linkCount = Number(accountLinks.suggested || 0) + Number(accountLinks.needs_review || 0);
      nextStep = `${linkCount} Telegram-to-broker link${linkCount === 1 ? " is" : "s are"} waiting for approval.`;
    }
    else if (Number(replies.pending || 0)) nextStep = `${replies.pending} reply match${replies.pending === 1 ? " is" : "es are"} waiting for review.`;
    else if (!Number(outreach.sent_total || 0)) nextStep = "Preview a small recipient group and send your first reviewed message.";
    else nextStep = "Scan replies to capture UID details from recently contacted members.";
  }
  document.getElementById("telegramNextStep").textContent = nextStep;
}

async function loadTelegramWorkspace() {
  const status = document.getElementById("telegramWorkspaceStatus");
  try {
    telegramWorkspaceData = await requestJson("/api/telegram/workspace", { method: "GET" });
    renderTelegramWorkspace();
    status.textContent = telegramWorkspaceData.outreach?.last_sent_at
      ? `Last successful delivery ${formatOverviewDateTime(telegramWorkspaceData.outreach.last_sent_at)}.`
      : "No successful deliveries saved yet.";
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("telegramRefreshWorkspaceButton").addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  await Promise.all([loadTelegramHealth(), loadTelegramWorkspace(), loadReplyDirectory(), loadOutreachHistory()]);
  event.currentTarget.disabled = false;
});

document.querySelectorAll("[data-telegram-go]").forEach((button) => {
  button.addEventListener("click", () => showTelegramSubpage(button.dataset.telegramGo));
});

function telegramMemberAssignmentRows() {
  const data = telegramAccountLinkData || {};
  const linksByMember = new Map();
  for (const candidate of data.candidates || []) {
    if (candidate.status !== "linked" || candidate.decision !== "approved") continue;
    const telegramId = String(candidate.telegram_id || "");
    if (!linksByMember.has(telegramId)) linksByMember.set(telegramId, new Map());
    linksByMember.get(telegramId).set(String(candidate.uid || ""), candidate);
  }
  return (data.members || []).map((member) => {
    const telegramId = String(member.telegram_id || "");
    const suggestions = (data.candidates || [])
      .filter((row) => String(row.telegram_id || "") === telegramId)
      .filter((row) => row.status === "suggested" && row.decision === "pending")
      .sort((left, right) => Number(right.confidence || 0) - Number(left.confidence || 0));
    return {
      ...member,
      telegram_id: telegramId,
      links: [...(linksByMember.get(telegramId)?.values() || [])],
      suggested_uid: suggestions[0]?.uid || "",
    };
  }).sort((left, right) => {
    if (Boolean(left.links.length) !== Boolean(right.links.length)) return left.links.length ? 1 : -1;
    return String(left.display_name || left.username || left.telegram_id)
      .localeCompare(String(right.display_name || right.username || right.telegram_id));
  });
}

function renderTelegramMemberAssignments() {
  const allRows = telegramMemberAssignmentRows();
  const query = document.getElementById("telegramMemberAssignmentSearch").value.trim().toLowerCase();
  const statusFilter = document.getElementById("telegramMemberAssignmentFilter").value;
  const groupFilter = document.getElementById("telegramMemberAssignmentGroup").value;
  filteredTelegramMemberAssignments = allRows.filter((row) => {
    const linked = Boolean(row.links.length);
    const matchesStatus = statusFilter === "all"
      || (statusFilter === "remaining" && !linked)
      || (statusFilter === "linked" && linked);
    const matchesGroup = groupFilter === "all" || (row.groups || []).includes(groupFilter);
    const matchesQuery = !query || [
      row.display_name,
      row.username,
      row.telegram_id,
      ...row.links.flatMap((link) => [link.uid, ...(link.report_names || [])]),
    ].join(" ").toLowerCase().includes(query);
    return matchesStatus && matchesGroup && matchesQuery;
  });

  const remaining = allRows.filter((row) => !row.links.length).length;
  document.getElementById("telegramMemberAssignmentCount").textContent =
    `${filteredTelegramMemberAssignments.length.toLocaleString()} shown · ${remaining.toLocaleString()} remaining`;

  const target = document.getElementById("telegramMemberAssignmentList");
  if (!filteredTelegramMemberAssignments.length) {
    target.innerHTML = `<div class="empty-state">${
      allRows.length ? "No members match this view." : "Scan Telegram groups to load members."
    }</div>`;
    return;
  }

  target.innerHTML = filteredTelegramMemberAssignments.map((row) => {
    const username = row.username ? `@${row.username}` : "No username";
    const groups = (row.groups || []).map((group) => group === "vip" ? "VIP" : "Discussion").join(" + ") || "—";
    const linkedAccounts = row.links.length
      ? row.links.map((link) => `<div class="telegram-member-current-link">
          <div><strong>UID ${escapeHtml(link.uid)}</strong><small>${escapeHtml((link.brokers || []).join(" + ") || "Broker unavailable")}${(link.report_names || []).length ? ` · ${escapeHtml(link.report_names.join(", "))}` : ""}</small></div>
          <button class="unlink-member-uid" type="button" data-telegram-id="${escapeHtml(row.telegram_id)}" data-uid="${escapeHtml(link.uid)}" aria-label="Remove UID ${escapeHtml(link.uid)}">Remove</button>
        </div>`).join("")
      : '<span class="telegram-link-status unmatched">UID needed</span>';
    return `<div class="telegram-member-assignment-row">
      <div class="telegram-member-assignment-identity">
        <strong>${escapeHtml(row.display_name || "Unknown")}</strong>
        <small>${escapeHtml(username)} · ID ${escapeHtml(row.telegram_id)}</small>
        <small>${escapeHtml(groups)}</small>
      </div>
      <div class="telegram-member-current-links">${linkedAccounts}</div>
      <form class="telegram-member-uid-form" data-telegram-id="${escapeHtml(row.telegram_id)}">
        <input name="uid" type="text" inputmode="numeric" autocomplete="off" value="${escapeHtml(row.suggested_uid || "")}" placeholder="Enter broker UID" aria-label="Broker UID for ${escapeHtml(row.display_name || row.telegram_id)}">
        <button class="primary" type="submit">Link UID</button>
        <button class="find-member-account" type="button" data-telegram-id="${escapeHtml(row.telegram_id)}">Find</button>
        <small class="telegram-member-assignment-feedback" aria-live="polite"></small>
      </form>
    </div>`;
  }).join("");

  target.querySelectorAll(".telegram-member-uid-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      assignTelegramMemberUid(form);
    });
  });
  target.querySelectorAll(".find-member-account").forEach((button) => {
    button.addEventListener("click", () => openManualTelegramAccountLink(button.dataset.telegramId));
  });
  target.querySelectorAll(".unlink-member-uid").forEach((button) => {
    button.addEventListener("click", () => unlinkTelegramAccountLink(button.dataset.telegramId, button.dataset.uid));
  });
}

function telegramAccountLinkRows() {
  const data = telegramAccountLinkData || {};
  const candidates = data.candidates || [];
  const memberIdsWithOptions = new Set(
    candidates
      .filter((row) => row.decision !== "rejected")
      .map((row) => String(row.telegram_id))
  );
  const unmatched = (data.members || [])
    .filter((member) => !memberIdsWithOptions.has(String(member.telegram_id)))
    .map((member) => ({
      id: `unmatched:${member.telegram_id}`,
      telegram_id: member.telegram_id,
      telegram_display_name: member.display_name,
      telegram_username: member.username,
      groups: member.groups || [],
      brokers: [],
      report_names: [],
      status: "unmatched",
      decision: "pending",
      confidence: 0,
      reason: "No reliable broker-account suggestion was found.",
      match_method: "Manual account selection available",
      uid: "",
    }));
  return [...candidates, ...unmatched];
}

function telegramAccountLinkStatusLabel(status) {
  return {
    suggested: "Strong suggestion",
    needs_review: "Needs review",
    linked: "Linked",
    unmatched: "Unmatched",
    conflict: "Conflict",
    rejected: "Rejected",
  }[status] || status || "Pending";
}

function telegramAccountLinkSourceLabel(source) {
  return {
    telegram_reply: "Telegram reply",
    identity_match: "Identity match",
    approved_link: "Approved link",
    manual: "Manual selection",
  }[source] || source || "No evidence";
}

function updateTelegramAccountLinkSelection() {
  const count = selectedTelegramLinkCandidates.size;
  document.getElementById("telegramAccountLinkSelectionCount").textContent = `${count} selected`;
  document.getElementById("approveTelegramLinksButton").disabled = !count;
}

function renderTelegramApprovedLinks() {
  const data = telegramAccountLinkData || {};
  const rows = data.approved_links || (data.candidates || []).filter(
    (row) => row.status === "linked" && row.decision === "approved"
  );
  const target = document.getElementById("telegramApprovedLinkList");
  const count = rows.length;
  document.getElementById("telegramApprovedLinkCount").textContent =
    `${count.toLocaleString()} ${count === 1 ? "link" : "links"}`;
  if (!count) {
    target.innerHTML = '<div class="empty-state">No UID links yet.</div>';
    return;
  }

  target.innerHTML = rows.map((row) => {
    const telegramId = String(row.telegram_id || "");
    const name = row.telegram_display_name || row.telegram_username || `Telegram ${telegramId}`;
    const username = row.telegram_username ? `@${String(row.telegram_username).replace(/^@/, "")}` : "";
    const accountDetails = [
      ...(row.brokers || []),
      ...(row.report_names || []),
    ].filter(Boolean).join(" · ") || "Broker account";
    return `<div class="telegram-approved-link-row">
      <div>
        <strong>${escapeHtml(name)}</strong>
        <small>${username ? `${escapeHtml(username)} · ` : ""}ID ${escapeHtml(telegramId)}</small>
      </div>
      <div class="telegram-approved-link-account">
        <strong>UID ${escapeHtml(row.uid || "")}</strong>
        <small>${escapeHtml(accountDetails)}</small>
      </div>
      <button class="remove-approved-uid-link" type="button" data-telegram-id="${escapeHtml(telegramId)}" data-uid="${escapeHtml(row.uid || "")}">Remove</button>
    </div>`;
  }).join("");
  target.querySelectorAll(".remove-approved-uid-link").forEach((button) => {
    button.addEventListener("click", () => {
      unlinkTelegramAccountLink(button.dataset.telegramId, button.dataset.uid);
    });
  });
}

function renderTelegramAccountLinks() {
  const data = telegramAccountLinkData || {};
  renderManualTelegramMemberOptions();
  const summary = data.summary || {};
  const memberRows = telegramMemberAssignmentRows();
  const linkedMembers = summary.linked_members ?? memberRows.filter((row) => row.links.length).length;
  const remainingMembers = summary.remaining ?? Math.max(Number(summary.discovered || 0) - linkedMembers, 0);
  const suggestionsAwaitingReview = Number(summary.suggested || 0) + Number(summary.needs_review || 0);
  document.getElementById("telegramLinkMetricDiscovered").textContent =
    Number(summary.discovered || 0).toLocaleString();
  document.getElementById("telegramLinkMetricLinked").textContent =
    Number(linkedMembers).toLocaleString();
  document.getElementById("telegramLinkMetricRemaining").textContent =
    Number(remainingMembers).toLocaleString();
  document.getElementById("telegramLinkMetricSuggested").textContent =
    suggestionsAwaitingReview.toLocaleString();
  document.getElementById("telegramAccountLinkSuggestionCount").textContent =
    `${suggestionsAwaitingReview.toLocaleString()} awaiting review`;
  renderTelegramApprovedLinks();
  renderTelegramMemberAssignments();

  const query = document.getElementById("telegramAccountLinkSearch").value.trim().toLowerCase();
  const statusFilter = document.getElementById("telegramAccountLinkStatusFilter").value;
  const groupFilter = document.getElementById("telegramAccountLinkGroupFilter").value;
  const brokerFilter = document.getElementById("telegramAccountLinkBrokerFilter").value;
  filteredTelegramAccountLinkRows = telegramAccountLinkRows().filter((row) => {
    const matchesQuery = !query || [
      row.telegram_display_name,
      row.telegram_username,
      row.telegram_id,
      row.uid,
      ...(row.report_names || []),
      ...(row.brokers || []),
    ].join(" ").toLowerCase().includes(query);
    const matchesStatus = statusFilter === "all"
      || (statusFilter === "review" && ["suggested", "needs_review", "conflict", "unmatched"].includes(row.status))
      || row.status === statusFilter;
    const matchesGroup = groupFilter === "all" || (row.groups || []).includes(groupFilter);
    const matchesBroker = brokerFilter === "all" || (row.brokers || []).includes(brokerFilter);
    return matchesQuery && matchesStatus && matchesGroup && matchesBroker;
  });

  const selectableIds = new Set(
    filteredTelegramAccountLinkRows
      .filter((row) => row.decision === "pending" && ["suggested", "needs_review"].includes(row.status))
      .map((row) => row.id)
  );
  selectedTelegramLinkCandidates = new Set(
    [...selectedTelegramLinkCandidates].filter((id) => selectableIds.has(id))
  );
  updateTelegramAccountLinkSelection();

  const target = document.getElementById("telegramAccountLinkTable");
  if (!filteredTelegramAccountLinkRows.length) {
    target.innerHTML = `<div class="empty-state">${data.needs_scan ? "Run Scan groups to discover Telegram members." : "No account links match these filters."}</div>`;
    return;
  }
  target.innerHTML = `<table>
    <thead><tr><th>Select</th><th>Telegram member</th><th>Groups</th><th>Broker account</th><th>Evidence</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>${filteredTelegramAccountLinkRows.map((row) => {
      const selectable = selectableIds.has(row.id);
      const confidence = Math.round(Number(row.confidence || 0) * 100);
      const username = row.telegram_username ? `@${row.telegram_username}` : "No username";
      const groups = (row.groups || []).map((group) => group === "vip" ? "VIP" : "Discussion").join(" + ") || "—";
      const accountCopy = row.uid
        ? `<strong>${escapeHtml(row.uid)}</strong><small>${escapeHtml((row.brokers || []).join(" + ") || "Broker not available")}</small><small>${escapeHtml((row.report_names || []).join(", ") || "Name not in current reports")}</small><small>${Number(row.account_count || 0)} account(s) · ${escapeHtml(money(row.total_balance || 0))}</small>`
        : `<strong>No account selected</strong><small>Use Find account for a manual link.</small>`;
      let actions = "";
      if (selectable) {
        actions += `<button class="approve-telegram-link" type="button" data-id="${escapeHtml(row.id)}">Approve</button>`;
      }
      if (row.decision === "pending" && ["suggested", "needs_review", "conflict"].includes(row.status)) {
        actions += `<button class="reject-telegram-link" type="button" data-id="${escapeHtml(row.id)}">Reject</button>`;
      }
      if (["unmatched", "needs_review", "conflict"].includes(row.status)) {
        actions += `<button class="find-telegram-account" type="button" data-telegram-id="${escapeHtml(row.telegram_id)}">Find account</button>`;
      }
      if (row.decision === "rejected") {
        actions += `<button class="restore-telegram-link" type="button" data-id="${escapeHtml(row.id)}">Restore</button>`;
      }
      if (row.status === "linked") {
        actions += `<button class="unlink-telegram-link" type="button" data-telegram-id="${escapeHtml(row.telegram_id)}" data-uid="${escapeHtml(row.uid)}">Remove link</button>`;
      }
      return `<tr>
        <td data-label="Select"><span>${selectable ? `<input class="telegram-link-checkbox" type="checkbox" value="${escapeHtml(row.id)}" ${selectedTelegramLinkCandidates.has(row.id) ? "checked" : ""}>` : "—"}</span></td>
        <td data-label="Telegram"><div class="telegram-link-member"><strong>${escapeHtml(row.telegram_display_name || "Unknown")}</strong><small>${escapeHtml(username)}</small><small>ID ${escapeHtml(row.telegram_id)}</small></div></td>
        <td data-label="Groups"><span>${escapeHtml(groups)}</span></td>
        <td data-label="Broker"><div class="telegram-link-account">${accountCopy}</div></td>
        <td data-label="Evidence"><div class="telegram-link-evidence"><strong>${escapeHtml(telegramAccountLinkSourceLabel(row.source))}</strong>${row.uid ? `<small class="telegram-link-confidence">${confidence}% confidence</small>` : ""}<small>${escapeHtml(row.reason || row.match_method || "")}</small></div></td>
        <td data-label="Status"><span class="telegram-link-status ${escapeHtml(row.status)}">${escapeHtml(telegramAccountLinkStatusLabel(row.status))}</span></td>
        <td data-label="Actions"><span>${actions || "—"}</span></td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;

  target.querySelectorAll(".telegram-link-checkbox").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) selectedTelegramLinkCandidates.add(input.value);
      else selectedTelegramLinkCandidates.delete(input.value);
      updateTelegramAccountLinkSelection();
    });
  });
  target.querySelectorAll(".approve-telegram-link").forEach((button) => {
    button.addEventListener("click", () => reviewTelegramAccountLinks([button.dataset.id], "approved"));
  });
  target.querySelectorAll(".reject-telegram-link").forEach((button) => {
    button.addEventListener("click", () => reviewTelegramAccountLinks([button.dataset.id], "rejected"));
  });
  target.querySelectorAll(".restore-telegram-link").forEach((button) => {
    button.addEventListener("click", () => reviewTelegramAccountLinks([button.dataset.id], "pending"));
  });
  target.querySelectorAll(".find-telegram-account").forEach((button) => {
    button.addEventListener("click", () => openManualTelegramAccountLink(button.dataset.telegramId));
  });
  target.querySelectorAll(".unlink-telegram-link").forEach((button) => {
    button.addEventListener("click", () => unlinkTelegramAccountLink(button.dataset.telegramId, button.dataset.uid));
  });
}

async function loadTelegramAccountLinks() {
  const status = document.getElementById("telegramAccountLinkStatus");
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links", { method: "GET" });
    telegramMembersPageState.data = telegramAccountLinkData;
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    status.textContent = telegramAccountLinkData.needs_scan
      ? "No saved scan. Connect Telegram, then run Scan groups."
      : `Last scanned ${formatOverviewDateTime(telegramAccountLinkData.last_scanned_at)}.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("scanTelegramAccountLinksButton").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = document.getElementById("telegramAccountLinkStatus");
  if (!telegramAuthorizationVerified) {
    status.textContent = "Reconnect Telegram before scanning VIP and Discussion.";
    telegramConnectButton.click();
    return;
  }
  button.disabled = true;
  status.textContent = "Reading VIP and Discussion members, then comparing uploaded broker reports…";
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links/scan", { method: "POST" });
    telegramMembersPageState.data = telegramAccountLinkData;
    selectedTelegramLinkCandidates.clear();
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    const summary = telegramAccountLinkData.summary || {};
    const groupCounts = Object.fromEntries(
      (telegramAccountLinkData.groups || []).map((group) => [group.group, group.member_count || 0])
    );
    const warning = (telegramAccountLinkData.warnings || [])[0];
    status.textContent =
      `Discussion ${groupCounts.discussion || 0} · VIP ${groupCounts.vip || 0}. ` +
      `${summary.suggested || 0} strong suggestion(s), ${summary.needs_review || 0} needing review, ` +
      `${summary.unmatched || 0} unmatched.` + (warning ? ` ${warning}` : "");
    await loadDashboard();
  } catch (error) {
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    button.disabled = !telegramAuthorizationVerified;
  }
});

document.getElementById("refreshTelegramAccountLinksButton").addEventListener("click", loadTelegramAccountLinks);

document.getElementById("telegramManualUidLinkForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const telegramId = form.elements.telegram_id.value.trim();
  const uid = form.elements.uid.value.trim();
  const button = document.getElementById("telegramManualUidLinkButton");
  const status = document.getElementById("telegramManualUidLinkStatus");
  if (!telegramId || !uid) {
    status.textContent = "Select a Telegram member and enter a UID.";
    return;
  }

  button.disabled = true;
  try {
    await linkTelegramMemberUid(telegramId, uid, status);
    form.reset();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

for (const id of [
  "telegramMemberAssignmentSearch",
  "telegramMemberAssignmentFilter",
  "telegramMemberAssignmentGroup",
]) {
  document.getElementById(id).addEventListener(
    id === "telegramMemberAssignmentSearch" ? "input" : "change",
    renderTelegramMemberAssignments
  );
}
for (const id of [
  "telegramAccountLinkSearch",
  "telegramAccountLinkStatusFilter",
  "telegramAccountLinkGroupFilter",
  "telegramAccountLinkBrokerFilter",
]) {
  document.getElementById(id).addEventListener(
    id === "telegramAccountLinkSearch" ? "input" : "change",
    renderTelegramAccountLinks
  );
}

document.getElementById("selectStrongTelegramLinksButton").addEventListener("click", () => {
  filteredTelegramAccountLinkRows
    .filter((row) => row.status === "suggested" && row.decision === "pending" && Number(row.confidence || 0) >= 0.94)
    .forEach((row) => selectedTelegramLinkCandidates.add(row.id));
  renderTelegramAccountLinks();
});

document.getElementById("clearTelegramLinkSelectionButton").addEventListener("click", () => {
  selectedTelegramLinkCandidates.clear();
  renderTelegramAccountLinks();
});

document.getElementById("approveTelegramLinksButton").addEventListener("click", () => {
  const candidateIds = [...selectedTelegramLinkCandidates];
  if (!candidateIds.length) return;
  if (!window.confirm(`Approve ${candidateIds.length} selected Telegram-to-broker link(s)?`)) return;
  reviewTelegramAccountLinks(candidateIds, "approved");
});

async function reviewTelegramAccountLinks(candidateIds, decision) {
  const status = document.getElementById("telegramAccountLinkStatus");
  status.textContent = `${decision === "approved" ? "Approving" : decision === "rejected" ? "Rejecting" : "Restoring"} ${candidateIds.length} link(s)…`;
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links/review", {
      method: "POST",
      body: JSON.stringify({ candidate_ids: candidateIds, decision }),
    });
    telegramMembersPageState.data = telegramAccountLinkData;
    candidateIds.forEach((id) => selectedTelegramLinkCandidates.delete(id));
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    await Promise.all([loadDashboard(), loadTelegramWorkspace()]);
    status.textContent = decision === "approved"
      ? `${candidateIds.length} link(s) approved and applied to the broker dashboard.`
      : decision === "rejected"
        ? `${candidateIds.length} suggestion(s) rejected.`
        : `${candidateIds.length} suggestion(s) restored for review.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("exportTelegramAccountLinksButton").addEventListener("click", () => {
  downloadTelegramCsv("telegram-broker-account-links.csv", filteredTelegramAccountLinkRows.map((row) => ({
    "Telegram Name": row.telegram_display_name || "",
    "Telegram Username": row.telegram_username ? `@${row.telegram_username}` : "",
    "Telegram ID": row.telegram_id || "",
    Groups: (row.groups || []).join(", "),
    UID: row.uid || "",
    Brokers: (row.brokers || []).join(", "),
    "Broker Name": (row.report_names || []).join(", "),
    Confidence: row.uid ? `${Math.round(Number(row.confidence || 0) * 100)}%` : "",
    Evidence: row.reason || "",
    Status: telegramAccountLinkStatusLabel(row.status),
  })));
});

const telegramAccountLinkDialog = document.getElementById("telegramAccountLinkDialog");
document.getElementById("telegramAccountLinkDialogClose").addEventListener("click", () => telegramAccountLinkDialog.close());

function openManualTelegramAccountLink(telegramId) {
  const member = (telegramAccountLinkData?.members || []).find(
    (row) => String(row.telegram_id) === String(telegramId)
  );
  if (!member) return;
  manualTelegramLinkMember = member;
  document.getElementById("telegramAccountLinkMember").textContent =
    `${member.display_name || "Unknown"}${member.username ? ` · @${member.username}` : ""}`;
  document.getElementById("telegramAccountOptionSearch").value = "";
  document.getElementById("telegramAccountOptionBroker").value = "all";
  telegramAccountLinkDialog.showModal();
  loadTelegramAccountOptions();
  document.getElementById("telegramAccountOptionSearch").focus();
}

async function loadTelegramAccountOptions() {
  const query = document.getElementById("telegramAccountOptionSearch").value.trim();
  const broker = document.getElementById("telegramAccountOptionBroker").value;
  const status = document.getElementById("telegramAccountOptionStatus");
  const target = document.getElementById("telegramAccountOptionResults");
  status.textContent = "Searching uploaded broker accounts…";
  try {
    const result = await requestJson(
      `/api/telegram/account-links/accounts?query=${encodeURIComponent(query)}&broker=${encodeURIComponent(broker)}&limit=50`,
      { method: "GET" }
    );
    status.textContent = `${result.row_count} matching UID(s). Showing up to 50.`;
    if (!(result.rows || []).length) {
      target.innerHTML = '<div class="empty-state">No broker accounts match this search.</div>';
      return;
    }
    target.innerHTML = result.rows.map((row) => `<div class="telegram-account-option">
      <div><strong>${escapeHtml(row.report_name || "Unnamed broker account")}</strong><small>UID ${escapeHtml(row.uid)} · ${escapeHtml((row.brokers || []).join(" + "))}</small><small>${Number(row.account_count || 0)} account(s) · ${escapeHtml(money(row.total_balance || 0))}</small></div>
      <button class="approve-manual-telegram-link" type="button" data-uid="${escapeHtml(row.uid)}">Approve link</button>
    </div>`).join("");
    target.querySelectorAll(".approve-manual-telegram-link").forEach((button) => {
      button.addEventListener("click", () => approveManualTelegramAccountLink(button.dataset.uid));
    });
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("telegramAccountOptionSearch").addEventListener("input", () => {
  clearTimeout(telegramAccountSearchTimer);
  telegramAccountSearchTimer = setTimeout(loadTelegramAccountOptions, 250);
});
document.getElementById("telegramAccountOptionBroker").addEventListener("change", loadTelegramAccountOptions);

async function approveManualTelegramAccountLink(uid) {
  const status = document.getElementById("telegramAccountOptionStatus");
  if (!manualTelegramLinkMember) return;
  status.textContent = `Approving UID ${uid}…`;
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links/manual", {
      method: "POST",
      body: JSON.stringify({
        telegram_id: manualTelegramLinkMember.telegram_id,
        uid,
      }),
    });
    telegramMembersPageState.data = telegramAccountLinkData;
    telegramAccountLinkDialog.close();
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    await Promise.all([loadDashboard(), loadTelegramWorkspace()]);
    document.getElementById("telegramAccountLinkStatus").textContent =
      `UID ${uid} approved for ${manualTelegramLinkMember.display_name || "the Telegram member"}.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

async function assignTelegramMemberUid(form) {
  const telegramId = form.dataset.telegramId;
  const input = form.elements.uid;
  const uid = input.value.trim();
  const button = form.querySelector('button[type="submit"]');
  const feedback = form.querySelector(".telegram-member-assignment-feedback");
  if (!uid) {
    feedback.textContent = "Enter a broker UID.";
    input.focus();
    return;
  }
  button.disabled = true;
  feedback.textContent = `Linking UID ${uid}…`;
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links/manual", {
      method: "POST",
      body: JSON.stringify({ telegram_id: telegramId, uid }),
    });
    telegramMembersPageState.data = telegramAccountLinkData;
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    document.getElementById("telegramAccountLinkStatus").textContent =
      `UID ${uid} approved and linked.`;
    await Promise.allSettled([loadDashboard(), loadTelegramWorkspace()]);
  } catch (error) {
    feedback.textContent = error.message;
    button.disabled = false;
  }
}

async function unlinkTelegramAccountLink(telegramId, uid) {
  if (!window.confirm(`Remove the approved link to UID ${uid}?`)) return;
  const status = document.getElementById("telegramAccountLinkStatus");
  const manualStatus = document.getElementById("telegramManualUidLinkStatus");
  status.textContent = `Removing UID ${uid}…`;
  manualStatus.textContent = `Removing UID ${uid}…`;
  try {
    telegramAccountLinkData = await requestJson("/api/telegram/account-links/unlink", {
      method: "POST",
      body: JSON.stringify({ telegram_id: telegramId, uid }),
    });
    telegramMembersPageState.data = telegramAccountLinkData;
    renderTelegramAccountLinks();
    if (dashboardView.dataset.activePage === "telegram-members") renderTelegramMembersPage();
    if (dashboardView.dataset.activePage === "matched-records") renderMatchedRecordsPage();
    renderHelpfulOverview();
    await Promise.all([loadDashboard(), loadTelegramWorkspace(), loadReplyDirectory()]);
    status.textContent = `UID ${uid} was unlinked and removed from the broker dashboard.`;
    manualStatus.textContent = `UID ${uid} was unlinked.`;
  } catch (error) {
    status.textContent = error.message;
    manualStatus.textContent = error.message;
  }
}

async function loadOutreachTemplates() {
  try {
    outreachTemplates = await requestJson("/api/telegram/outreach/templates", { method: "GET" });
    document.getElementById("outreachMessage").value = outreachTemplates.welcome || "";
    updateMessageCharacterCount();
    resetSendConfirmation();
  } catch (error) {
    document.getElementById("outreachStatus").textContent = error.message;
  }
}

document.getElementById("outreachTemplate").addEventListener("change", (event) => {
  if (event.target.value !== "custom") {
    document.getElementById("outreachMessage").value = outreachTemplates[event.target.value] || "";
    updateMessageCharacterCount();
    resetSendConfirmation();
  }
});

function selectedRecipientIds() {
  return [...selectedRecipientSet];
}

function updateRecipientSelectionUi() {
  const count = selectedRecipientSet.size;
  document.getElementById("recipientSelectionCount").textContent = `${count} selected`;
  document.getElementById("sendOutreachButton").textContent = count
    ? `Send to ${count}`
    : "Send messages";
  updateSendButtonState();
}

function renderFilteredRecipients() {
  const target = document.getElementById("recipientPreview");
  const query = document.getElementById("recipientSearch").value.trim().toLowerCase();
  filteredRecipientRows = previewedRecipients.filter((recipient) =>
    [recipient.display_name, recipient.username, recipient.telegram_id, recipient.group]
      .join(" ")
      .toLowerCase()
      .includes(query)
  );
  if (!filteredRecipientRows.length) {
    target.innerHTML = `<div class="empty-state">${previewedRecipients.length ? "No recipients match this search." : "Preview recipients to continue."}</div>`;
    updateRecipientSelectionUi();
    return;
  }
  target.innerHTML = `<table>
    <thead><tr><th>Select</th><th>Name</th><th>Username</th><th>Telegram ID</th><th>Group</th></tr></thead>
    <tbody>${filteredRecipientRows.map((recipient) => `<tr>
      <td><input class="recipient-checkbox" type="checkbox" value="${escapeHtml(recipient.telegram_id)}" ${selectedRecipientSet.has(String(recipient.telegram_id)) ? "checked" : ""}></td>
      <td>${escapeHtml(recipient.display_name || "—")}</td>
      <td>${escapeHtml(recipient.username ? "@" + recipient.username : "—")}</td>
      <td>${escapeHtml(recipient.telegram_id)}</td>
      <td>${escapeHtml(recipient.group)}</td>
    </tr>`).join("")}</tbody>
  </table>`;
  target.querySelectorAll(".recipient-checkbox").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) selectedRecipientSet.add(input.value);
      else selectedRecipientSet.delete(input.value);
      resetSendConfirmation();
      updateRecipientSelectionUi();
    });
  });
  updateRecipientSelectionUi();
}

function renderRecipientPreview(recipients, emptyMessage = "Preview recipients to see who is eligible.") {
  previewedRecipients = recipients;
  selectedRecipientSet = new Set();
  document.getElementById("recipientSearch").value = "";
  document.getElementById("telegramRecipientTools").hidden = !recipients.length;
  document.getElementById("outreachConfirm").checked = false;
  document.getElementById("outreachConfirmationText").value = "";
  if (!recipients.length) {
    document.getElementById("recipientPreview").innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    updateRecipientSelectionUi();
    return;
  }
  renderFilteredRecipients();
}

function resetSendConfirmation() {
  document.getElementById("outreachConfirm").checked = false;
  document.getElementById("outreachConfirmationText").value = "";
  updateSendButtonState();
}

function updateSendButtonState() {
  const selected = selectedRecipientIds().length;
  const reviewed = document.getElementById("outreachConfirm").checked;
  const confirmation = document.getElementById("outreachConfirmationText").value.trim();
  const message = document.getElementById("outreachMessage").value.trim();
  document.getElementById("sendOutreachButton").disabled =
    !telegramAuthorizationVerified || !selected || !reviewed || confirmation !== "SEND" || !message;
}

document.getElementById("initializeTrackingButton").addEventListener("click", async () => {
  const status = document.getElementById("outreachStatus");
  status.textContent = "Reading current group members to create a baseline…";
  try {
    const result = await requestJson("/api/telegram/outreach/initialize", {
      method: "POST",
      body: JSON.stringify({ group: document.getElementById("outreachGroup").value }),
    });
    status.textContent = result.message;
    renderRecipientPreview([]);
    await loadTelegramWorkspace();
  } catch (error) {
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  }
});

document.getElementById("checkTelegramSetupButton").addEventListener("click", async () => {
  const status = document.getElementById("telegramWorkspaceStatus");
  const button = document.getElementById("checkTelegramSetupButton");
  button.disabled = true;
  status.textContent = "Checking the connected account and configured groups…";
  try {
    const result = await requestJson("/api/telegram/outreach/diagnostics", {
      method: "GET",
    });
    telegramDiagnostics = result;
    renderTelegramWorkspace();
    const ready = (result.groups || []).filter((group) => group.status !== "error").length;
    status.textContent = `${ready} of ${(result.groups || []).length} groups are ready. No messages were sent.`;
  } catch (error) {
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    button.disabled = !telegramAuthorizationVerified;
  }
});

document.getElementById("previewRecipientsButton").addEventListener("click", async () => {
  const status = document.getElementById("outreachStatus");
  status.textContent = "Loading eligible recipients…";
  try {
    const result = await requestJson("/api/telegram/outreach/preview", {
      method: "POST",
      body: JSON.stringify({
        group: document.getElementById("outreachGroup").value,
        audience: document.getElementById("outreachAudience").value,
      }),
    });
    renderRecipientPreview(result.recipients || [], result.message);
    status.textContent = result.message;
  } catch (error) {
    renderRecipientPreview([]);
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  }
});

document.getElementById("selectAllRecipientsButton").addEventListener("click", () => {
  filteredRecipientRows.forEach((recipient) => selectedRecipientSet.add(String(recipient.telegram_id)));
  resetSendConfirmation();
  renderFilteredRecipients();
});

document.getElementById("clearRecipientSelectionButton").addEventListener("click", () => {
  selectedRecipientSet.clear();
  resetSendConfirmation();
  renderFilteredRecipients();
});

document.getElementById("recipientSearch").addEventListener("input", renderFilteredRecipients);

document.getElementById("exportRecipientsButton").addEventListener("click", () => {
  downloadTelegramCsv("telegram-recipient-preview.csv", filteredRecipientRows.map((row) => ({
    Name: row.display_name || "",
    Username: row.username ? `@${row.username}` : "",
    "Telegram ID": row.telegram_id,
    Group: row.group,
  })));
});

document.getElementById("outreachConfirm").addEventListener("change", updateSendButtonState);
document.getElementById("outreachConfirmationText").addEventListener("input", updateSendButtonState);
function updateMessageCharacterCount() {
  const length = document.getElementById("outreachMessage").value.length;
  document.getElementById("outreachCharacterCount").textContent = `${length} / 4096`;
}

document.getElementById("outreachMessage").addEventListener("input", () => {
  updateMessageCharacterCount();
  resetSendConfirmation();
});

document.getElementById("clearMessageButton").addEventListener("click", () => {
  document.getElementById("outreachTemplate").value = "custom";
  document.getElementById("outreachMessage").value = "";
  updateMessageCharacterCount();
  resetSendConfirmation();
  document.getElementById("outreachMessage").focus();
});

const outreachAudienceDescriptions = {
  new: "Members discovered after the selected group's tracking baseline.",
  existing: "Every discoverable member in the selected Telegram group.",
  unmatched: "Discoverable members not yet linked to an uploaded broker UID.",
  active: "Matched members classified active from the latest broker reports.",
  inactive: "Matched members classified inactive from the latest broker reports.",
};

function updateOutreachAudienceHelp() {
  const audience = document.getElementById("outreachAudience").value;
  document.getElementById("outreachAudienceHelp").textContent = outreachAudienceDescriptions[audience];
}

document.getElementById("outreachAudience").addEventListener("change", updateOutreachAudienceHelp);
updateOutreachAudienceHelp();

for (const controlId of ["outreachGroup", "outreachAudience"]) {
  document.getElementById(controlId).addEventListener("change", () => {
    renderRecipientPreview([]);
    document.getElementById("outreachStatus").textContent =
      "Audience changed. Preview recipients again before sending.";
  });
}

let uidReplyWatchTimer = null;
let uidReplyWatchStopTimer = null;
let uidReplyWatchFirstTimer = null;
let uidReplyScanBusy = false;

async function scanAndLoadExactUidMatches(source = "automatic") {
  if (uidReplyScanBusy) return;
  uidReplyScanBusy = true;
  const replyStatus = document.getElementById("replyMatchStatus");
  replyStatus.textContent = "Checking Telegram replies for UID details…";
  try {
    const scan = await requestJson("/api/telegram/reply-matches/scan", {
      method: "POST",
      body: JSON.stringify({ days: 30 }),
    });
    const matches = await requestJson("/api/telegram/reply-matches", { method: "GET" });
    const exactMatches = (matches.candidates || []).filter(
      (row) => row.decision === "pending" && row.match_status === "exact_match"
    );
    let approved = 0;
    for (const row of exactMatches) {
      await requestJson("/api/telegram/reply-matches/review", {
        method: "POST",
        body: JSON.stringify({ candidate_id: row.id, decision: "approved" }),
      });
      approved += 1;
    }
    await loadReplyMatches();
    if (approved) await refreshDashboard();
    const message =
      `Checked ${scan.checked_messages} replies; loaded ${approved} exact UID match${approved === 1 ? "" : "es"}.` +
      ((matches.candidates || []).some(
        (row) => row.decision === "pending" && row.match_status === "needs_review"
      ) ? " Ambiguous replies are waiting for review." : "");
    replyStatus.textContent = `${message} This scan did not send any messages.`;
  } catch (error) {
    const message = `${source === "automatic" ? "Automatic reply check" : "Reply scan"} paused: ${error.message}`;
    replyStatus.textContent = message;
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    uidReplyScanBusy = false;
  }
}

function startUidReplyWatch() {
  if (uidReplyWatchTimer) clearInterval(uidReplyWatchTimer);
  if (uidReplyWatchStopTimer) clearTimeout(uidReplyWatchStopTimer);
  if (uidReplyWatchFirstTimer) clearTimeout(uidReplyWatchFirstTimer);
  document.getElementById("replyMatchStatus").textContent =
    "UID reply monitoring is active for one hour while this page remains open. No additional messages will be sent.";
  uidReplyWatchFirstTimer = setTimeout(() => scanAndLoadExactUidMatches("automatic"), 15000);
  uidReplyWatchTimer = setInterval(
    () => scanAndLoadExactUidMatches("automatic"),
    60000
  );
  uidReplyWatchStopTimer = setTimeout(() => {
    clearInterval(uidReplyWatchTimer);
    uidReplyWatchTimer = null;
    document.getElementById("replyMatchStatus").textContent =
      "Reply monitoring finished after one hour. Press Scan incoming replies to check again.";
  }, 60 * 60 * 1000);
}

document.getElementById("sendOutreachButton").addEventListener("click", async () => {
  const status = document.getElementById("outreachStatus");
  const recipientIds = selectedRecipientIds();
  const message = document.getElementById("outreachMessage").value.trim();
  if (!recipientIds.length || !message) {
    status.textContent = "Select recipients and review the message first.";
    return;
  }
  const confirmed = window.confirm(
    `Send this Telegram message to ${recipientIds.length} selected recipient(s)?\n\n` +
    "This is the final step. Press Cancel if you do not want to send now."
  );
  if (!confirmed) {
    status.textContent = "Send cancelled. No Telegram message was sent.";
    return;
  }
  const button = document.getElementById("sendOutreachButton");
  button.disabled = true;
  status.textContent = `Sending to ${recipientIds.length} selected recipient(s)…`;
  try {
    const result = await requestJson("/api/telegram/outreach/send", {
      method: "POST",
      body: JSON.stringify({
        group: document.getElementById("outreachGroup").value,
        audience: document.getElementById("outreachAudience").value,
        recipient_ids: recipientIds,
        message,
        confirm_send: true,
        confirmation_text: "SEND",
      }),
    });
    const failureDetails = (result.failed || [])
      .slice(0, 3)
      .map((row) => `${row.display_name || row.telegram_id}: ${row.error}`)
      .join(" | ");
    status.textContent =
      `Sent ${result.sent_count}. Failed ${result.failed_count}. ` +
      (failureDetails ? `Telegram reported: ${failureDetails}. ` : "") +
      (result.sent_count > 0
        ? "Reply monitoring has started; exact UID matches will load automatically while this page remains open."
        : "No reply monitoring was started because no message was delivered.");
    renderRecipientPreview([]);
    if (result.sent_count > 0) startUidReplyWatch();
    await Promise.all([loadTelegramWorkspace(), loadOutreachHistory()]);
  } catch (error) {
    status.textContent = error.message;
    resetSendConfirmation();
    refreshTelegramHealthForAuthorizationError(error);
  }
});

function renderReplyDirectory(rows = null) {
  if (Array.isArray(rows)) replyDirectoryRows = rows;
  const query = document.getElementById("replyDirectorySearch").value.trim().toLowerCase();
  const filter = document.getElementById("replyDirectoryFilter").value;
  filteredReplyDirectoryRows = replyDirectoryRows.filter((row) => {
    const matchesQuery = [row.telegram_name, row.uid, row.broker, row.original_reply]
      .join(" ")
      .toLowerCase()
      .includes(query);
    const matchesFilter = filter === "all"
      || (filter === "pending" && row.decision === "pending")
      || (filter === "linked" && row.linked)
      || (filter === "uid_not_found" && row.match_status === "uid_not_found")
      || (filter === "rejected" && row.decision === "rejected");
    return matchesQuery && matchesFilter;
  });
  const target = document.getElementById("replyDirectoryTable");
  document.getElementById("replyDirectoryCount").textContent =
    filter === "all" && !query
      ? `${replyDirectoryRows.length} ${replyDirectoryRows.length === 1 ? "reply" : "replies"}`
      : `${filteredReplyDirectoryRows.length} of ${replyDirectoryRows.length}`;
  if (!filteredReplyDirectoryRows.length) {
    target.innerHTML = `<div class="empty-state">${replyDirectoryRows.length ? "No replies match these filters." : "No replies scanned yet."}</div>`;
    return;
  }
  const statusLabels = {
    exact_match: "Linked",
    needs_review: "Needs review",
    uid_not_found: "UID not found",
  };
  target.innerHTML = `<table>
    <thead><tr><th>Telegram Name</th><th>UID</th><th>Broker</th><th>Found via</th><th>Status</th><th>Reply &amp; Actions</th></tr></thead>
    <tbody>${filteredReplyDirectoryRows.map((row) => `<tr data-directory-row data-id="${escapeHtml(row.candidate_id)}">
      <td>
        <span class="directory-display"><strong>${escapeHtml(row.telegram_name || "Unknown")}</strong></span>
        <input class="directory-edit hidden" data-field="telegram_name" value="${escapeHtml(row.telegram_name || "")}">
      </td>
      <td>
        <span class="directory-display">${escapeHtml(row.uid || "—")}</span>
        <input class="directory-edit hidden" data-field="uid" inputmode="numeric" value="${escapeHtml(row.uid || "")}">
      </td>
      <td>
        <span class="directory-display">${escapeHtml(row.broker || "Not specified")}</span>
        <select class="directory-edit hidden" data-field="broker">
          <option value="PU Prime" ${row.broker === "PU Prime" ? "selected" : ""}>PU Prime</option>
          <option value="Vantage" ${row.broker === "Vantage" ? "selected" : ""}>Vantage</option>
        </select>
      </td>
      <td>${row.source === "open_scan" ? "Existing chat" : "Automated message"}</td>
      <td>
        <span class="status ${row.linked ? "status-active" : "status-inactive"}">
          ${escapeHtml(statusLabels[row.match_status] || (row.linked ? "Linked" : "Needs review"))}
        </span>
        ${row.report_client_name ? `<div class="telegram-inline-note">Report: ${escapeHtml(row.report_client_name)}${Number(row.account_count) > 1 ? ` · ${escapeHtml(row.account_count)} accounts` : ""}</div>` : ""}
        ${row.reason ? `<div class="telegram-inline-note">${escapeHtml(row.reason)}</div>` : ""}
        ${row.decision === "rejected" ? '<div class="telegram-inline-note">Rejected — will not be used</div>' : ""}
        ${!row.linked && row.decision !== "rejected" ? '<div class="telegram-inline-note">Approve in Review matches to use this UID</div>' : ""}
      </td>
      <td>
        <details><summary>View original reply</summary><div class="telegram-original-reply">${escapeHtml(row.original_reply || "—")}</div></details>
        <button class="directory-edit-button" type="button">Edit</button>
        <button class="directory-save-button hidden" type="button">Save</button>
        <button class="directory-cancel-button hidden" type="button">Cancel</button>
        <button class="directory-delete-button" type="button">Delete</button>
      </td>
    </tr>`).join("")}</tbody>
  </table>`;
  target.querySelectorAll("[data-directory-row]").forEach((row) => {
    const setEditing = (editing) => {
      row.querySelectorAll(".directory-display").forEach((element) => element.classList.toggle("hidden", editing));
      row.querySelectorAll(".directory-edit").forEach((element) => element.classList.toggle("hidden", !editing));
      row.querySelector(".directory-edit-button").classList.toggle("hidden", editing);
      row.querySelector(".directory-save-button").classList.toggle("hidden", !editing);
      row.querySelector(".directory-cancel-button").classList.toggle("hidden", !editing);
    };
    row.querySelector(".directory-edit-button").addEventListener("click", () => setEditing(true));
    row.querySelector(".directory-cancel-button").addEventListener("click", loadReplyDirectory);
    row.querySelector(".directory-save-button").addEventListener("click", async () => {
      const value = (field) => row.querySelector(`[data-field="${field}"]`).value;
      try {
        await requestJson("/api/telegram/reply-directory/edit", {
          method: "POST",
          body: JSON.stringify({
            candidate_id: row.dataset.id,
            telegram_name: value("telegram_name"),
            uid: value("uid"),
            broker: value("broker"),
          }),
        });
        await Promise.all([loadReplyDirectory(), loadReplyMatches()]);
        await refreshDashboard();
      } catch (error) {
        document.getElementById("replyDirectoryStatus").textContent = error.message;
      }
    });
    row.querySelector(".directory-delete-button").addEventListener("click", async () => {
      if (!window.confirm("Delete this automatically detected reply?")) return;
      try {
        await requestJson("/api/telegram/reply-directory/delete", {
          method: "POST",
          body: JSON.stringify({ candidate_id: row.dataset.id }),
        });
        await Promise.all([loadReplyDirectory(), loadReplyMatches()]);
        await refreshDashboard();
      } catch (error) {
        document.getElementById("replyDirectoryStatus").textContent = error.message;
      }
    });
  });
}

document.getElementById("replyDirectorySearch").addEventListener("input", () => renderReplyDirectory());
document.getElementById("replyDirectoryFilter").addEventListener("change", () => renderReplyDirectory());
document.getElementById("exportReplyDirectoryButton").addEventListener("click", () => {
  downloadTelegramCsv("telegram-reply-directory.csv", filteredReplyDirectoryRows.map((row) => ({
    "Telegram Name": row.telegram_name || "",
    UID: row.uid || "",
    Broker: row.broker || "",
    Source: row.source === "open_scan" ? "Existing chat" : "Automated message",
    Status: row.linked ? "Linked" : row.match_status || row.decision,
    "Original Reply": row.original_reply || "",
  })));
});

async function loadReplyDirectory() {
  const status = document.getElementById("replyDirectoryStatus");
  try {
    const result = await requestJson("/api/telegram/reply-directory", { method: "GET" });
    renderReplyDirectory(result.rows || []);
    status.textContent = result.row_count
      ? `${result.row_count} reply record(s) loaded.`
      : "No reply records saved. Nothing is sent automatically.";
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("connectAndScanRepliesButton").addEventListener("click", async () => {
  const button = document.getElementById("connectAndScanRepliesButton");
  const status = document.getElementById("replyDirectoryStatus");
  if (!latestOverviewState.telegramConnected) {
    status.textContent = "Complete the Telegram connection, then press this button again to scan replies.";
    telegramConnectButton.click();
    return;
  }
  button.disabled = true;
  const scanAllChats = document.getElementById("replyDirectoryScanAllChats").checked;
  const scanDays = Number(document.getElementById("replyDirectoryScanDays").value);
  status.textContent = scanAllChats
    ? "Reading incoming Telegram replies and existing chats…"
    : "Reading incoming Telegram replies…";
  try {
    const scan = await requestJson("/api/telegram/reply-matches/scan", {
      method: "POST",
      body: JSON.stringify({ days: scanDays, scan_mode: scanAllChats ? "all_chats" : "prompted" }),
    });
    await Promise.all([loadReplyDirectory(), loadReplyMatches()]);
    await loadTelegramWorkspace();
    status.textContent =
      `Checked ${scan.checked_messages} incoming messages from ${scan.prompted_recipients || 0} prompted recipients ` +
      `across ${scan.checked_chats || 0} available private chats` +
      (scanAllChats ? " (including chats without a sent message)" : "") + `. ` +
      `Found or updated ${scan.new_or_updated_matches} UID reply record(s). No messages were sent.`;
  } catch (error) {
    status.textContent = error.message;
    refreshTelegramHealthForAuthorizationError(error);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("eraseReplyDirectoryButton").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Erase all scanned reply records and UID links created from those replies?\n\n" +
    "Imported members and broker reports will be kept. No message will be sent."
  );
  if (!confirmed) return;
  const status = document.getElementById("replyDirectoryStatus");
  status.textContent = "Clearing scanned reply data…";
  try {
    const result = await requestJson("/api/telegram/reply-directory", { method: "DELETE" });
    renderReplyDirectory([]);
    await Promise.all([loadReplyMatches(), loadTelegramWorkspace()]);
    status.textContent = result.message;
  } catch (error) {
    status.textContent = error.message;
  }
});

function replyMatchBadge(status) {
  const labels = {
    exact_match: "Exact match",
    needs_review: "Needs review",
    uid_not_found: "UID not found",
  };
  return labels[status] || status || "Pending";
}

function renderReplyMatches(candidates) {
  const target = document.getElementById("replyMatchTable");
  document.getElementById("reviewRepliesToggle").textContent =
    `Review matches (${candidates.length})`;
  if (!candidates.length) {
    target.innerHTML = '<div class="empty-state">No matches to review.</div>';
    return;
  }
  target.innerHTML = `<table>
    <thead><tr>
      <th>Telegram Name</th><th>Original Reply</th><th>UID</th><th>Broker</th>
      <th>Found via</th><th>Result</th><th>Decision</th><th>Actions</th>
    </tr></thead>
    <tbody>${candidates.map((row) => `<tr data-reply-row data-id="${escapeHtml(row.id)}">
      <td>
        <span class="reply-display"><strong>${escapeHtml(row.telegram_display_name || "Unknown")}</strong><br>
          <small>${escapeHtml(row.telegram_username ? "@" + row.telegram_username : row.telegram_id)}</small></span>
        <input class="reply-edit hidden" data-field="telegram_name" value="${escapeHtml(row.telegram_display_name || "")}">
      </td>
      <td><details><summary>View reply</summary>
        <div class="telegram-original-reply">${escapeHtml(row.reply_text || "—")}</div>
        <small>${escapeHtml(row.chat_name || "")}</small>
      </details></td>
      <td>
        <span class="reply-display"><strong>${escapeHtml(row.uid || "—")}</strong></span>
        <input class="reply-edit hidden" data-field="uid" inputmode="numeric" value="${escapeHtml(row.uid || "")}">
      </td>
      <td>
        <span class="reply-display">${escapeHtml(row.broker_name || row.broker || "Not specified")}</span>
        <select class="reply-edit hidden" data-field="broker">
          <option value="PU Prime" ${(row.broker_name || row.broker) === "PU Prime" ? "selected" : ""}>PU Prime</option>
          <option value="Vantage" ${(row.broker_name || row.broker) === "Vantage" ? "selected" : ""}>Vantage</option>
        </select>
      </td>
      <td>${row.source === "open_scan" ? "Existing chat" : "Automated message"}</td>
      <td><span class="status">${escapeHtml(replyMatchBadge(row.match_status))}</span><br>
        <small>${escapeHtml(row.reason || "")}</small></td>
      <td><span class="status">${escapeHtml(row.decision || "pending")}</span></td>
      <td>
        <button class="approve-reply-button" type="button" ${row.match_status === "uid_not_found" ? "disabled title=\"Upload a report containing this UID first\"" : ""}>Approve</button>
        <button class="reject-reply-button" type="button">Reject</button>
        <button class="edit-reply-button" type="button">Edit</button>
        <button class="save-reply-button hidden" type="button">Save</button>
        <button class="cancel-reply-button hidden" type="button">Cancel</button>
        <button class="delete-reply-button" type="button">Delete</button>
      </td>
    </tr>`).join("")}</tbody>
  </table>`;
  target.querySelectorAll("[data-reply-row]").forEach((row) => {
    row.querySelector(".approve-reply-button").addEventListener("click", () => reviewReplyMatch(row.dataset.id, "approved"));
    row.querySelector(".reject-reply-button").addEventListener("click", () => reviewReplyMatch(row.dataset.id, "rejected"));
    const setEditing = (editing) => {
      row.querySelectorAll(".reply-display").forEach((element) => element.classList.toggle("hidden", editing));
      row.querySelectorAll(".reply-edit").forEach((element) => element.classList.toggle("hidden", !editing));
      row.querySelector(".edit-reply-button").classList.toggle("hidden", editing);
      row.querySelector(".save-reply-button").classList.toggle("hidden", !editing);
      row.querySelector(".cancel-reply-button").classList.toggle("hidden", !editing);
    };
    row.querySelector(".edit-reply-button").addEventListener("click", () => setEditing(true));
    row.querySelector(".cancel-reply-button").addEventListener("click", loadReplyMatches);
    row.querySelector(".save-reply-button").addEventListener("click", async () => {
      const value = (field) => row.querySelector(`[data-field="${field}"]`).value;
      try {
        await requestJson("/api/telegram/reply-directory/edit", {
          method: "POST",
          body: JSON.stringify({
            candidate_id: row.dataset.id,
            telegram_name: value("telegram_name"),
            uid: value("uid"),
            broker: value("broker"),
          }),
        });
        await Promise.all([loadReplyMatches(), loadReplyDirectory()]);
        await refreshDashboard();
      } catch (error) {
        document.getElementById("replyMatchStatus").textContent = error.message;
      }
    });
    row.querySelector(".delete-reply-button").addEventListener("click", async () => {
      if (!window.confirm("Delete this reply record?")) return;
      try {
        await requestJson("/api/telegram/reply-directory/delete", {
          method: "POST",
          body: JSON.stringify({ candidate_id: row.dataset.id }),
        });
        await Promise.all([loadReplyMatches(), loadReplyDirectory()]);
        await refreshDashboard();
      } catch (error) {
        document.getElementById("replyMatchStatus").textContent = error.message;
      }
    });
  });
}

document.getElementById("reviewRepliesToggle").addEventListener("click", () => {
  const details = document.getElementById("replyReviewDetails");
  details.classList.toggle("hidden");
  document.getElementById("reviewRepliesToggle").setAttribute(
    "aria-expanded",
    String(!details.classList.contains("hidden"))
  );
});

async function loadReplyMatches() {
  const status = document.getElementById("replyMatchStatus");
  try {
    const result = await requestJson("/api/telegram/reply-matches", { method: "GET" });
    const pending = (result.candidates || []).filter((row) => row.decision === "pending");
    renderReplyMatches(pending);
    status.textContent = pending.length
      ? `${pending.length} match${pending.length === 1 ? "" : "es"} waiting for review.`
      : "No matches are waiting for review.";
  } catch (error) {
    status.textContent = error.message;
  }
}

async function reviewReplyMatch(candidateId, decision) {
  const status = document.getElementById("replyMatchStatus");
  status.textContent = `${decision === "approved" ? "Approving" : "Rejecting"} match…`;
  try {
    const result = await requestJson("/api/telegram/reply-matches/review", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, decision }),
    });
    await Promise.all([loadReplyMatches(), loadReplyDirectory(), loadTelegramWorkspace()]);
    if (decision === "approved") await refreshDashboard();
    status.textContent = decision === "approved"
      ? `${result.message} Dashboard totals updated.`
      : result.message;
  } catch (error) {
    status.textContent = error.message;
  }
}

function renderOutreachHistory() {
  const query = document.getElementById("outreachHistorySearch").value.trim().toLowerCase();
  const group = document.getElementById("outreachHistoryGroup").value;
  filteredOutreachHistoryRows = outreachHistoryRows.filter((row) => {
    const matchesQuery = [row.display_name, row.telegram_id, row.group, row.audience]
      .join(" ")
      .toLowerCase()
      .includes(query);
    return matchesQuery && (group === "all" || row.group === group);
  });
  const target = document.getElementById("outreachHistoryTable");
  if (!filteredOutreachHistoryRows.length) {
    target.innerHTML = `<div class="empty-state">${outreachHistoryRows.length ? "No deliveries match these filters." : "No successful deliveries saved yet."}</div>`;
    return;
  }
  target.innerHTML = `<table>
    <thead><tr><th>Recipient</th><th>Telegram ID</th><th>Group</th><th>Audience</th><th>Delivered</th></tr></thead>
    <tbody>${filteredOutreachHistoryRows.map((row) => `<tr>
      <td><strong>${escapeHtml(row.display_name || "Unknown")}</strong></td>
      <td>${escapeHtml(row.telegram_id || "—")}</td>
      <td>${escapeHtml(row.group || "—")}</td>
      <td>${escapeHtml(row.audience || "—")}</td>
      <td>${escapeHtml(formatOverviewDateTime(row.sent_at))}</td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function loadOutreachHistory() {
  const status = document.getElementById("outreachHistoryStatus");
  try {
    const result = await requestJson("/api/telegram/outreach/history", { method: "GET" });
    outreachHistoryRows = result.history || [];
    renderOutreachHistory();
    status.textContent = `${outreachHistoryRows.length} successful deliver${outreachHistoryRows.length === 1 ? "y" : "ies"} saved.`;
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("outreachHistorySearch").addEventListener("input", renderOutreachHistory);
document.getElementById("outreachHistoryGroup").addEventListener("change", renderOutreachHistory);
document.getElementById("refreshOutreachHistoryButton").addEventListener("click", loadOutreachHistory);
document.getElementById("exportOutreachHistoryButton").addEventListener("click", () => {
  downloadTelegramCsv("telegram-delivery-history.csv", filteredOutreachHistoryRows.map((row) => ({
    Recipient: row.display_name || "",
    "Telegram ID": row.telegram_id || "",
    Group: row.group || "",
    Audience: row.audience || "",
    Delivered: row.sent_at || "",
  })));
});

let deferredInstallPrompt = null;
const installAppButton = document.getElementById("installAppButton");

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  installAppButton.classList.remove("hidden");
});

installAppButton.addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  installAppButton.classList.add("hidden");
});

window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  installAppButton.classList.add("hidden");
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js?v=56", { updateViaCache: "none" })
      .then((registration) => registration.update())
      .catch((error) => {
        console.error("Service worker registration failed:", error);
      });
  });
}



    async function restoreSession() {
      try {
        const user = await requestJson("/api/auth/me", {
          method: "GET",
        });

        showDashboard(user);
      } catch {
        showAuthentication();
      }
    }

    restoreSession();
  