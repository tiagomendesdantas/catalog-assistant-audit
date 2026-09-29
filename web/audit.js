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
const est = (e, d = 1) => (e ? `${pct(e.rate, d)} (${pct(e.low, d)}–${pct(e.high, d)})` : "–");
const diff = (d) => (d ? `${pts(d.rate)} [${pts(d.low)}, ${pts(d.high)}]` : "–");

const ORDER = ["A", "B", "C", "C+check"];
const CONDITIONS = { clean: "Exact record", retrieval: "With similar products" };
const SHORT = { A: "A · Baseline", B: "B · Grounded", C: "C · Evidence", "C+check": "C + check" };
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
  tooltip.style.left = `${Math.min(x + 14, window.innerWidth - 240)}px`;
  tooltip.style.top = `${y + 14}px`;
}
const hideTip = () => { tooltip.style.display = "none"; };

function niceDomain(maxHigh) {
  return Math.min(1, Math.max(0.1, Math.ceil(maxHigh * 10) / 10));
}

function dotChart(svg, rows, label, domain, condition) {
  const W = 460, left = 128, right = 18, top = 8, rowH = 40;
  const H = top + rows.length * rowH + 32;
  const x = (v) => left + (v / domain) * (W - left - right);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("aria-label", label);
  svg.replaceChildren();
  const grid = sv("g", { class: "grid" });
  const ticks = sv("g", { class: "tick" });
  const step = domain <= 0.3 ? 0.05 : domain <= 0.6 ? 0.1 : 0.2;
  for (let t = 0; t <= domain + 1e-9; t += step) {
    grid.append(sv("line", { x1: x(t), x2: x(t), y1: top, y2: H - 28 }));
    ticks.append(sv("text", { x: x(t), y: H - 8, "text-anchor": "middle" }, pct(t, 0)));
  }
  svg.append(grid, ticks);
  rows.forEach((r, i) => {
    const cy = top + i * rowH + rowH / 2;
    const g = sv("g", { class: "row" });
    g.append(sv("text", { x: 0, y: cy + 4 }, SHORT[r.config]));
    const text = `${NAMES[r.config]}, ${CONDITIONS[condition]}: ${pct(r.rate)}, 95% interval ${pct(r.low)} to ${pct(r.high)}, ${r.n} questions`;
    const hit = sv("rect", {
      class: "hit", x: left - 6, y: cy - rowH / 2 + 3, width: W - left - right + 12, height: rowH - 6,
      tabindex: 0, role: "img", "aria-label": text,
    });
    const tip = (e) => showTip(e, pct(r.rate), [NAMES[r.config], CONDITIONS[condition],
      `95% interval ${pct(r.low)}–${pct(r.high)}`, `${r.n} questions`]);
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

function headline(block, key) {
  return ORDER.filter((c) => block.configs[c]?.headline[key])
    .map((c) => ({ config: c, ...block.configs[c].headline[key] }));
}

function metricSection(model, key, chartId, tableId, label) {
  const series = {};
  for (const cond of Object.keys(CONDITIONS)) {
    if (model.conditions[cond]) series[cond] = headline(model.conditions[cond], key);
  }
  const all = Object.values(series).flat();
  const domain = niceDomain(Math.max(...all.map((r) => r.high)));
  for (const [cond, rows] of Object.entries(series)) {
    dotChart($(`${chartId}-${cond}`), rows, `${label}, ${CONDITIONS[cond]}`, domain, cond);
  }
  const table = $(tableId);
  table.replaceChildren();
  const head = el("tr");
  head.append(el("th", {}, "Configuration"));
  for (const cond of Object.keys(series)) head.append(el("th", { class: "num" }, CONDITIONS[cond]));
  head.append(el("th", { class: "num" }, "Questions per condition"));
  table.append(head);
  for (const config of ORDER) {
    const tr = el("tr");
    tr.append(el("td", {}, NAMES[config]));
    let n = "–";
    for (const [cond, rows] of Object.entries(series)) {
      const r = rows.find((x) => x.config === config);
      tr.append(el("td", { class: "num" }, est(r)));
      if (r) n = String(r.n);
    }
    tr.append(el("td", { class: "num" }, n));
    table.append(tr);
  }
}

function render(results, modelName) {
  const model = results.models[modelName];
  const retr = model.conditions.retrieval || model.conditions.clean;
  const clean = model.conditions.clean;
  const aRetr = retr.configs.A.headline.unsupported_when_not_in_record;
  const aClean = clean.configs.A.headline.unsupported_when_not_in_record;
  const best = ORDER.filter((c) => c !== "A" && retr.configs[c])
    .map((c) => ({ c, e: retr.configs[c].headline.unsupported_when_not_in_record }))
    .sort((p, q) => p.e.rate - q.e.rate)[0];

  $("heroLabel").textContent =
    `${modelName}, baseline assistant, with similar products in context: questions the record could not answer`;
  $("hero").textContent = pct(aRetr.rate, aRetr.rate < 0.1 ? 1 : 0);  // 0.3% must not read as 0%
  $("heroText").textContent =
    `answered anyway (95% interval ${pct(aRetr.low)}–${pct(aRetr.high)}); with the exact record, ` +
    `${pct(aClean.rate)}. ` + (best ? `${NAMES[best.c]}, with similar products: ${pct(best.e.rate)} ` +
    `(${pct(best.e.low)}–${pct(best.e.high)}).` : "");

  metricSection(model, "unsupported_when_not_in_record", "chartUnsupported", "tableUnsupported",
    "Share answered although the record had no answer");
  metricSection(model, "accuracy_when_answerable", "chartAccuracy", "tableAccuracy",
    "Share correct when the record had the answer");

  const effect = $("tableEffect");
  effect.replaceChildren();
  const eh = el("tr");
  for (const h of ["Configuration", "Answered without support", "Correct when answerable",
    "Matches another product"]) eh.append(el("th", h === "Configuration" ? {} : { class: "num" }, h));
  effect.append(eh);
  for (const c of ORDER) {
    const e = model.retrieval_effect?.[c];
    if (!e) continue;
    const tr = el("tr");
    tr.append(el("td", {}, NAMES[c]), el("td", { class: "num" }, diff(e.unsupported_when_not_in_record)),
      el("td", { class: "num" }, diff(e.accuracy_when_answerable)),
      el("td", { class: "num" }, String(retr.configs[c]?.matches_neighbor ?? "–")));
    effect.append(tr);
  }

  const dt = $("tableDiff");
  dt.replaceChildren();
  const dh = el("tr");
  for (const h of ["Configuration", "Context", "Answered without support", "Correct when answerable"]) {
    dh.append(el("th", ["Configuration", "Context"].includes(h) ? {} : { class: "num" }, h));
  }
  dt.append(dh);
  for (const [cond, block] of Object.entries(model.conditions)) {
    for (const c of ORDER.filter((c) => c !== "A" && block.configs[c]?.versus_A)) {
      const v = block.configs[c].versus_A;
      const tr = el("tr");
      tr.append(el("td", {}, `${NAMES[c]} vs A`), el("td", {}, CONDITIONS[cond]),
        el("td", { class: "num" }, diff(v.unsupported_when_not_in_record)),
        el("td", { class: "num" }, diff(v.accuracy_when_answerable)));
      dt.append(tr);
    }
  }

  const st = $("tableStrata");
  st.replaceChildren();
  const sh = el("tr");
  sh.append(el("th", {}, "Question type"), el("th", {}, "Shows"));
  for (const c of ORDER) sh.append(el("th", { class: "num" }, c));
  st.append(sh);
  for (const [key, [label, metric]] of Object.entries(STRATA)) {
    const tr = el("tr");
    tr.append(el("td", {}, label), el("td", { class: "muted" }, metric === "correct" ? "correct" : "answered anyway"));
    for (const c of ORDER) {
      const parts = Object.keys(CONDITIONS).map((cond) => {
        const e = model.conditions[cond]?.configs[c]?.by_stratum[key]?.[metric];
        return e ? pct(e.rate, 0) : "–";
      });
      tr.append(el("td", { class: "num" }, parts.join(" / ")));
    }
    st.append(tr);
  }

  const lines = [];
  for (const [cond, block] of Object.entries(model.conditions)) {
    const w = block.configs["C+check"]?.routed_would_have_been;
    if (!w) continue;
    const total = Object.values(w).reduce((s, v) => s + v, 0);
    lines.push(`${CONDITIONS[cond]}: the check sent ${total} of configuration C's answers to review; graded ` +
      `against the record, ${w.correct || 0} were correct, ${w.wrong || 0} had a wrong value and ` +
      `${w.unsupported || 0} answered a question the record could not answer.`);
  }
  $("routed").textContent = lines.join(" ") +
    " A check that also stops correct answers costs reviewer time; that trade is shown rather than hidden.";

  const cost = $("tableCost");
  cost.replaceChildren();
  const ch = el("tr");
  ch.append(el("th", {}, "Configuration"));
  for (const cond of Object.keys(CONDITIONS)) ch.append(el("th", { class: "num" }, `${CONDITIONS[cond]}, per 1,000 questions`));
  cost.append(ch);
  for (const c of ["A", "B", "C"]) {
    const tr = el("tr");
    tr.append(el("td", {}, NAMES[c]));
    for (const cond of Object.keys(CONDITIONS)) {
      const v = model.conditions[cond]?.configs[c]?.cost_usd_standard_per_1000;
      tr.append(el("td", { class: "num" }, v ? `$${v.toFixed(2)}` : "–"));
    }
    cost.append(tr);
  }

  const runs = results.runs.map((r) => `${r.model} (${r.run_id}, ${r.questions} questions, ${r.reasoning_effort} reasoning effort)`);
  const method = $("method");
  method.replaceChildren();
  for (const p of [
    "Catalog: a simple random sample of 5,000 products sold in the United States from Open Food Facts, " +
      "pinned to one revision of the official export.",
    "Questions: every product-attribute pair falls into one of seven strata (the rows of the table above). Within " +
      "each stratum, products were drawn at random and one eligible attribute asked per product, so no product " +
      "contributes two questions to a stratum. Each question carries the inverse of its inclusion probability; " +
      "rates use the Hájek estimator with a linearised variance, and strata combine in proportion to their number " +
      "of eligible pairs.",
    "Context: every question is asked twice, once with the exact record and once with the record plus the two " +
      "products whose names are most similar (character 3–4-gram TF-IDF, cosine), in a shuffled order. Ground " +
      "truth is always the named product's record.",
    "Products were split 20/80 into development and test before any question was drawn. Prompts and grading rules " +
      "were adjusted on development questions only, and every change is listed in docs/EVAL_PLAN.md. Reported " +
      `numbers come from the test split. Runs: ${runs.join("; ")}. The test split has been run ` +
      `${results.test_runs_to_date} time(s) in total; every run is logged in the repository.`,
    "Grading is deterministic: numbers within 2% (or 0.05 absolute) of the record, exact grade letters and NOVA " +
      "groups, and yes/no for allergens. No model grades another model.",
  ]) method.append(el("p", {}, p));
}

function modelSwitch(results) {
  const names = Object.keys(results.models);
  let current = names.includes("gpt-6.1-sol") ? "gpt-6.1-sol" : names[0];
  const box = $("modelSwitch");
  const draw = () => {
    box.replaceChildren();
    for (const name of names) {
      const b = el("button", { type: "button", class: "ghost", "aria-pressed": String(name === current) }, name);
      b.addEventListener("click", () => { current = name; draw(); render(results, current); });
      box.append(b);
    }
  };
  draw();
  render(results, current);
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
  if (results.pending || !results.models) { $("pending").hidden = false; return; }
  $("report").hidden = false;
  modelSwitch(results);
  sampleSize();
});
