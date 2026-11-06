(function () {
  "use strict";

  const labels = {
    source_conflict: "Conflicting source values",
    repeated_source_row: "Repeated source row",
    missing_settlement: "Missing clean settlement",
    multiple_settlements: "Multiple settlement IDs",
    unexpected_settlement: "Settlement without ledger",
    payment_currency_mismatch: "Payment currency mismatch",
    payment_amount_mismatch: "Payment amount mismatch",
    missing_payout: "Missing clean payout",
    payout_currency_mismatch: "Payout currency mismatch",
    payout_amount_mismatch: "Payout amount mismatch",
    unexpected_payout: "Payout without settlements",
  };
  const pageSize = 12;
  let report;
  let selectedSnapshot = 0;
  let currentPage = 0;
  let filtered = [];
  const el = (id) => document.getElementById(id);
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const count = (value) => new Intl.NumberFormat("en-US").format(value);

  function amount(cents, currency = "", signed = false) {
    if (cents === null || cents === undefined) return "—";
    const value = BigInt(cents);
    const absolute = value < 0n ? -value : value;
    const prefix = value < 0n ? "−" : signed && value > 0n ? "+" : "";
    return `${prefix}${(absolute / 100n).toLocaleString("en-US")}.${String(absolute % 100n).padStart(2, "0")}${currency ? ` ${currency}` : ""}`;
  }

  function difference(cents) {
    return `<span class="${BigInt(cents ?? 0) === 0n ? "zero" : "delta"}">${amount(cents, "", true)}</span>`;
  }

  function renderSnapshot(index) {
    selectedSnapshot = index;
    const snapshot = report.snapshots[index];
    document.querySelectorAll("[data-snapshot]").forEach((button) => {
      const active = Number(button.dataset.snapshot) === index;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    el("delivery-note").textContent =
      index === 0
        ? "First delivery, with missing records, conflicts and deliberate amount errors."
        : "Late records and revisions applied. Eight duplicate settlement bookings still need review.";
    el("ledger-population").textContent =
      `${count(snapshot.counts.ledger)} current ledger payments`;
    el("matched").textContent = count(snapshot.matched_payments);
    el("open-checks").textContent = count(snapshot.counts.issues);
    el("quarantined").textContent = count(snapshot.quarantined_records);
    el("raw-count").textContent = count(snapshot.counts.raw_records);
    el("nav-count").textContent = count(snapshot.counts.issues);
    el("issue-total").textContent = count(snapshot.counts.issues);
    el("balances").innerHTML = snapshot.currencies
      .map(
        (row) => `<tr>
      <td><span class="currency">${escape(row.currency)}</span></td>
      <td>${amount(row.ledger_net_cents)}</td><td>${amount(row.settlement_net_cents)}</td>
      <td>${difference(row.settlement_variance_cents)}</td><td>${amount(row.payout_net_cents)}</td>
      <td>${difference(row.payout_variance_cents)}</td></tr>`,
      )
      .join("");
    const types = [
      ...new Set(snapshot.issues.map((row) => row.issue_type)),
    ].sort();
    const merchants = [
      ...new Set(snapshot.issues.map((row) => row.merchant_id).filter(Boolean)),
    ].sort();
    el("type-filter").innerHTML =
      '<option value="">All checks</option>' +
      types
        .map(
          (type) =>
            `<option value="${escape(type)}">${escape(labels[type] || type)}</option>`,
        )
        .join("");
    el("merchant-filter").innerHTML =
      '<option value="">All merchants</option>' +
      merchants
        .map((merchant) => `<option>${escape(merchant)}</option>`)
        .join("");
    resetFilters();
  }

  function filterRows() {
    const search = el("search").value.trim().toLowerCase();
    filtered = report.snapshots[selectedSnapshot].issues.filter((row) => {
      const searchable =
        `${row.entity_id} ${row.reason} ${row.merchant_id} ${labels[row.issue_type]}`.toLowerCase();
      return (
        (!search || searchable.includes(search)) &&
        (!el("type-filter").value ||
          row.issue_type === el("type-filter").value) &&
        (!el("merchant-filter").value ||
          row.merchant_id === el("merchant-filter").value) &&
        (!el("currency-filter").value ||
          row.currency === el("currency-filter").value)
      );
    });
    currentPage = 0;
    renderRows();
  }

  function renderRows() {
    const start = currentPage * pageSize;
    const rows = filtered.slice(start, start + pageSize);
    el("issue-rows").innerHTML =
      rows
        .map(
          (row) => `<tr>
      <td><span class="issue-title"><i class="issue-marker ${escape(row.severity)}"></i>${escape(labels[row.issue_type] || row.issue_type)}</span><span class="record-id">${escape(row.entity_id)}</span></td>
      <td>${escape(row.merchant_id || "—")}</td><td>${escape(row.currency || "—")}</td>
      <td class="money">${amount(row.expected_cents)}</td><td class="money">${amount(row.observed_cents)}</td>
      <td class="money">${difference(row.variance_cents)}</td>
      <td><button class="inspect" data-case="${escape(row.issue_id)}">Inspect</button></td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="7">No checks match these filters.</td></tr>';
    const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
    el("result-count").textContent = filtered.length
      ? `${start + 1}–${Math.min(start + pageSize, filtered.length)} of ${count(filtered.length)} checks`
      : "0 checks";
    el("page-count").textContent = `${currentPage + 1} / ${pages}`;
    el("previous").disabled = currentPage === 0;
    el("next").disabled = currentPage + 1 >= pages;
  }

  function resetFilters() {
    ["search", "type-filter", "merchant-filter", "currency-filter"].forEach(
      (id) => {
        el(id).value = "";
      },
    );
    filterRows();
  }

  function inspectCase(id) {
    const issue = report.snapshots[selectedSnapshot].issues.find(
      (row) => row.issue_id === id,
    );
    el("case-title").textContent =
      `${labels[issue.issue_type] || issue.issue_type} · ${issue.entity_id}`;
    el("case-reason").textContent = issue.reason;
    el("case-amounts").innerHTML = [
      ["Expected net", amount(issue.expected_cents, issue.currency || "")],
      ["Observed net", amount(issue.observed_cents, issue.currency || "")],
      ["Difference", amount(issue.variance_cents, issue.currency || "", true)],
    ]
      .map(
        ([label, value]) =>
          `<div><span>${label}</span><strong>${escape(value)}</strong></div>`,
      )
      .join("");
    el("case-records").innerHTML =
      issue.source_records
        .map(
          (record) => `<details class="source-record">
      <summary>${escape(record.kind)} · ${escape(record.record_id)} · revision ${record.revision}<br>${escape(record.filename)} · import ${record.batch_id} · data row ${record.row_number}</summary>
      <pre>${escape(JSON.stringify(record.payload, null, 2))}</pre></details>`,
        )
        .join("") ||
      '<p class="quiet">The expected aggregate is shown above. See the SQL report for its contributing settlement group.</p>';
    el("case-dialog").showModal();
  }

  function downloadCsv() {
    const columns = [
      "issue_type",
      "entity_id",
      "merchant_id",
      "currency",
      "expected_cents",
      "observed_cents",
      "variance_cents",
      "reason",
    ];
    const cell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [
      columns.join(","),
      ...filtered.map((row) =>
        columns.map((name) => cell(row[name])).join(","),
      ),
    ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `synthetic-reconciliation-${selectedSnapshot === 0 ? "initial" : "corrected"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function start() {
    try {
      const response = await fetch("data/demo.json");
      if (!response.ok)
        throw new Error(`Data request returned ${response.status}`);
      report = await response.json();
      el("audit-rows").innerHTML = report.ingestion
        .map(
          (run, index) => `<tr>
        <td>${["Initial delivery", "Late corrections", "Replay all files"][index]}</td>
        <td>${count(run.files_loaded)}</td><td>${count(run.rows_loaded)}</td>
        <td>${count(run.keys_reconsidered)}</td><td>${count(run.files_replayed)}</td></tr>`,
        )
        .join("");
      renderSnapshot(0);
      el("content").hidden = false;
    } catch (error) {
      el("error").hidden = false;
      el("delivery-note").textContent = "Data could not be loaded.";
      console.error(error);
    }
  }

  document.querySelectorAll("[data-snapshot]").forEach((button) => {
    button.addEventListener("click", () =>
      renderSnapshot(Number(button.dataset.snapshot)),
    );
  });
  ["search", "type-filter", "merchant-filter", "currency-filter"].forEach(
    (id) => el(id).addEventListener("input", filterRows),
  );
  el("reset").addEventListener("click", resetFilters);
  el("previous").addEventListener("click", () => {
    currentPage -= 1;
    renderRows();
  });
  el("next").addEventListener("click", () => {
    currentPage += 1;
    renderRows();
  });
  el("issue-rows").addEventListener("click", (event) => {
    const button = event.target.closest("[data-case]");
    if (button) inspectCase(button.dataset.case);
  });
  el("download").addEventListener("click", downloadCsv);
  el("close-case").addEventListener("click", () => el("case-dialog").close());
  el("case-dialog").addEventListener("click", (event) => {
    if (event.target === el("case-dialog")) {
      const box = el("case-dialog").getBoundingClientRect();
      if (
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom
      )
        el("case-dialog").close();
    }
  });
  start();
})();
