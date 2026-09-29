"use strict";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, text) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
};
const sv = (tag, attrs = {}, text) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
};
const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const pts = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)} pts`;

const ORDER = ["A", "B", "C", "C+check"];
const NAMES = {
  A: "A · Baseline", B: "B · Grounded", C: "C · Grounded + evidence", "C+check": "C + evidence check",
};
const STRATA = {
  nutrition_present: ["Nutrient value in the record", "correct"],
  score_present: ["Nutri-Score or NOVA in the record", "correct"],
  allergen_yes: ["Allergen declared", "correct"],
  allergen_no: ["Other allergens declared, this one not", "correct"],
  nutrition_missing: ["Nutrient value not in the record", "unsupported"],
  score_missing: ["Nutri-Score or NOVA not in the record", "unsupported"],
  allergen_missing: ["No allergen or ingredient information", "unsupported"],
};

const tooltip = $("tooltip");
function showTip(event, strong, lines) {
  tooltip.replaceChildren(el("strong", {}, strong), ...lines.map((l) => el("div", {}, l)));
  tooltip.style.display = "block";
  const r = event.target.getBoundingClientRect();
  const x = event.clientX ?? r.left + r.width / 2;
  const y = event.clientY ?? r.top;
  tooltip.style.left = `${Math.min(x + 14, window.innerWidth - 220)}px`;
  tooltip.style.top = `${y + 14}px`;
}
const hideTip = () => { tooltip.style.display = "none"; };

function dotChart(svg, rows, label) {
  const W = 640, left = 180, right = 24, top = 12, rowH = 44;
  const H = top + rows.length * rowH + 34;
  const maxHigh = Math.max(...rows.map((r) => r.high));
  const domain = Math.min(1, Math.max(0.1, Math.ceil(maxHigh * 10) / 10));
  const x = (v) => left + (v / domain) * (W - left - right);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("aria-label", label);
  svg.replaceChildren();

  const grid = sv("g", { class: "grid" });
  const ticks = sv("g", { class: "tick" });
  const steps = domain <= 0.3 ? 0.05 : domain <= 0.6 ? 0.1 : 0.2;
  for (let t = 0; t <= domain + 1e-9; t += steps) {
    grid.append(sv("line", { x1: x(t), x2: x(t), y1: top, y2: H - 30 }));
    ticks.append(sv("text", { x: x(t), y: H - 10, "text-anchor": "middle" }, pct(t, 0)));
  }
  svg.append(grid, ticks);

  rows.forEach((r, i) => {
    const cy = top + i * rowH + rowH / 2;
    const g = sv("g", { class: "row" });
    g.append(sv("text", { x: 0, y: cy + 4 }, NAMES[r.config]));
    const hit = sv("rect", {
      class: "hit", x: left - 6, y: cy - rowH / 2 + 4, width: W - left - right + 12, height: rowH - 8,
      tabindex: 0, role: "img",
      "aria-label": `${NAMES[r.config]}: ${pct(r.rate)}, 95% interval ${pct(r.low)} to ${pct(r.high)}, ${r.n} questions`,
    });
    const tip = (e) => showTip(e, pct(r.rate), [NAMES[r.config], `95% interval ${pct(r.low)}–${pct(r.high)}`, `${r.n} questions`]);
    hit.addEventListener("pointermove", tip);
    hit.addEventListener("focus", tip);
    hit.addEventListener("pointerleave", hideTip);
    hit.addEventListener("blur", hideTip);
    g.append(hit);
    g.append(sv("line", { class: "ci", x1: x(r.low), x2: x(r.high), y1: cy, y2: cy }));
    g.append(sv("circle", { class: "pt", cx: x(r.rate), cy, r: 5 }));
    svg.append(g);
  });
}

function rateTable(table, rows) {
  table.replaceChildren();
  const head = el("tr");
  for (const h of ["Configuration", "Estimate", "95% interval", "Questions"]) {
    head.append(el("th", h === "Configuration" ? {} : { class: "num" }, h));
  }
  table.append(head);
  for (const r of rows) {
    const tr = el("tr");
    tr.append(el("td", {}, NAMES[r.config]), el("td", { class: "num" }, pct(r.rate)),
      el("td", { class: "num" }, `${pct(r.low)} – ${pct(r.high)}`), el("td", { class: "num" }, String(r.n)));
    table.append(tr);
  }
}

function headlineRows(results, key) {
  return ORDER.filter((c) => results.configs[c] && results.configs[c].headline[key])
    .map((c) => ({ config: c, ...results.configs[c].headline[key] }));
}

function render(results) {
  const unsupported = headlineRows(results, "unsupported_when_not_in_record");
  const accuracy = headlineRows(results, "accuracy_when_answerable");
  const a = unsupported.find((r) => r.config === "A");
  const best = unsupported.filter((r) => r.config !== "A").sort((p, q) => p.rate - q.rate)[0];

  $("heroLabel").textContent = "Baseline assistant, questions the catalog record could not answer";
  $("hero").textContent = pct(a.rate, 0);
  $("heroText").textContent =
    `answered anyway (95% interval ${pct(a.low)}–${pct(a.high)}). ` +
    (best ? `${NAMES[best.config]}: ${pct(best.rate)} (${pct(best.low)}–${pct(best.high)}).` : "");

  dotChart($("chartUnsupported"), unsupported, "Share answered although the record had no answer, by configuration");
  rateTable($("tableUnsupported"), unsupported);
  dotChart($("chartAccuracy"), accuracy, "Share correct when the record had the answer, by configuration");
  rateTable($("tableAccuracy"), accuracy);

  const diff = $("tableDiff");
  diff.replaceChildren();
  const dh = el("tr");
  for (const h of ["Configuration", "Answered without support", "Correct when answerable"]) {
    dh.append(el("th", h === "Configuration" ? {} : { class: "num" }, h));
  }
  diff.append(dh);
  for (const c of ORDER.filter((c) => c !== "A" && results.configs[c]?.versus_A)) {
    const v = results.configs[c].versus_A;
    const cell = (d) => d ? `${pts(d.rate)} [${pts(d.low)}, ${pts(d.high)}]` : "–";
    const tr = el("tr");
    tr.append(el("td", {}, `${NAMES[c]} vs A`), el("td", { class: "num" }, cell(v.unsupported_when_not_in_record)),
      el("td", { class: "num" }, cell(v.accuracy_when_answerable)));
    diff.append(tr);
  }

  const st = $("tableStrata");
  st.replaceChildren();
  const sh = el("tr");
  sh.append(el("th", {}, "Question type"), el("th", {}, "Shows"));
  for (const c of ORDER) if (results.configs[c]) sh.append(el("th", { class: "num" }, c));
  st.append(sh);
  for (const [key, [label, metric]] of Object.entries(STRATA)) {
    const tr = el("tr");
    tr.append(el("td", {}, label), el("td", { class: "muted" }, metric === "correct" ? "correct" : "answered anyway"));
    for (const c of ORDER) {
      if (!results.configs[c]) continue;
      const s = results.configs[c].by_stratum[key];
      const e = s && s[metric];
      tr.append(el("td", { class: "num" }, e ? `${pct(e.rate, 0)} (${pct(e.low, 0)}–${pct(e.high, 0)})` : "–"));
    }
    st.append(tr);
  }

  const check = results.configs["C+check"];
  if (check && check.routed_would_have_been) {
    const w = check.routed_would_have_been;
    const total = Object.values(w).reduce((s, v) => s + v, 0);
    $("routed").textContent =
      `The check sent ${total} of configuration C's answers to review. Graded against the record, ` +
      `${w.correct || 0} of those were correct, ${w.wrong || 0} had a wrong value, and ` +
      `${w.unsupported || 0} answered a question the record could not answer. A check that also stops ` +
      `correct answers costs reviewer time; that trade is visible here rather than hidden.`;
  }

  const cost = $("tableCost");
  cost.replaceChildren();
  const ch = el("tr");
  ch.append(el("th", {}, "Configuration"), el("th", { class: "num" }, "Per 1,000 questions, standard API price"));
  cost.append(ch);
  for (const c of ["A", "B", "C"]) {
    const v = results.configs[c]?.cost_usd_standard_per_1000;
    if (v === undefined || v === null) continue;
    const tr = el("tr");
    tr.append(el("td", {}, NAMES[c]), el("td", { class: "num" }, `$${v.toFixed(2)}`));
    cost.append(tr);
  }

  const run = results.run || {};
  const method = $("method");
  method.replaceChildren();
  const paras = [
    `Catalog: a simple random sample of 5,000 products sold in the United States from Open Food Facts, ` +
      `pinned to one revision of the official export.`,
    `Questions: every product-attribute pair in the catalog falls into one of seven strata (the rows of the ` +
      `table above). Within each stratum, products were drawn at random and one eligible attribute asked per ` +
      `product, so no product contributes two questions to a stratum. Each question carries the inverse of its ` +
      `inclusion probability; rates use the Hájek estimator with a linearised variance, and strata combine in ` +
      `proportion to their number of eligible pairs.`,
    `Products were split 20/80 into development and test before any question was drawn. Prompts were tuned on ` +
      `development questions only. Reported numbers come from the test split.`,
    `Model: ${run.model || "–"}, low effort, structured output. Run ${run.run_id || "–"}, ` +
      `${run.questions || "–"} test questions per configuration. The test split has been run ` +
      `${results.test_runs_to_date ?? "–"} time(s) in total; every run is logged in the repository.`,
    `Grading is deterministic: numbers within 2% (or 0.05 absolute) of the record, exact grade letters and NOVA ` +
      `groups, and yes/no for allergens. No model grades another model.`,
  ];
  for (const p of paras) method.append(el("p", {}, p));
}

function sampleSize() {
  const p = Number($("ssP").value) / 100;
  const m = Number($("ssM").value) / 100;
  const d = Number($("ssD").value);
  const n = p > 0 && p < 1 && m > 0 ? Math.ceil(d * 1.959964 ** 2 * p * (1 - p) / m ** 2) : NaN;
  $("ssN").textContent = Number.isFinite(n) ? n.toLocaleString() : "–";
}
for (const id of ["ssP", "ssM", "ssD"]) $(id).addEventListener("input", sampleSize);

fetch("/api/results").then(async (res) => {
  const results = res.ok ? await res.json() : { pending: true };
  if (results.pending) { $("pending").hidden = false; return; }
  $("report").hidden = false;
  render(results);
  sampleSize();
});
