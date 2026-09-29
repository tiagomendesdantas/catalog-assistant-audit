"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, text) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
};

const FIELD_LABELS = {
  product_name: "Product", brand: "Brand", package_size: "Package size", categories: "Categories",
  ingredients: "Ingredients", allergens_declared: "Allergens declared",
  may_contain_traces_of: "May contain traces of", labels: "Labels", nutri_score_grade: "Nutri-Score",
  nova_group: "NOVA group", nutrition_per_100g: "Nutrition per 100 g",
};

const OUTCOMES = {
  correct: ["good", "Correct"],
  held_back: ["good", "Correctly declined"],
  wrong: ["bad", "Wrong value"],
  unsupported: ["bad", "Answered without support in the record"],
  abstained: ["neutral", "Declined, but the record had it"],
  routed: ["warn", "Sent to human review"],
  failed: ["neutral", "No usable output"],
  answered: ["good", "Answered from the record"],
  not_in_catalog: ["neutral", "The catalog doesn't list this"],
  routed_to_review: ["warn", "Sent to human review: the cited evidence doesn't match the record"],
};

const CONFIG_NAMES = {
  A: "A · Baseline", B: "B · Grounded", C: "C · Grounded + evidence", "C+check": "C + evidence check",
};

function badge(outcome) {
  const [tone, label] = OUTCOMES[outcome] || ["neutral", outcome];
  const span = el("span", { class: `badge ${tone}` });
  span.append(el("span", { class: "dot", "aria-hidden": "true" }), document.createTextNode(label));
  return span;
}

function recordList(record) {
  const dl = el("dl", { class: "record" });
  for (const [key, value] of Object.entries(record)) {
    dl.append(el("dt", {}, FIELD_LABELS[key] || key));
    const dd = el("dd");
    if (Array.isArray(value)) dd.textContent = value.join(", ");
    else if (value && typeof value === "object") {
      const inner = el("dl", { class: "record nested" });
      for (const [k, v] of Object.entries(value)) inner.append(el("dt", {}, k), el("dd", {}, String(v)));
      dd.append(inner);
    } else dd.textContent = String(value);
    dl.append(dd);
  }
  return dl;
}

let current = null;
let timer = null;

async function search(q) {
  const res = await fetch(`/api/products?q=${encodeURIComponent(q)}&limit=25`);
  const items = await res.json();
  const list = $("results");
  list.replaceChildren();
  if (!items.length) list.append(el("li", { class: "small muted" }, "No product matches."));
  for (const item of items) {
    const li = el("li");
    const btn = el("button", { type: "button" });
    btn.append(document.createTextNode(item.name));
    if (item.brand) btn.append(el("span", { class: "muted" }, ` · ${item.brand}`));
    btn.addEventListener("click", () => select(item.code));
    li.append(btn);
    list.append(li);
  }
}

async function select(code) {
  const res = await fetch(`/api/products/${encodeURIComponent(code)}`);
  if (!res.ok) return;
  const data = await res.json();
  current = data;
  const box = $("product");
  box.replaceChildren(recordList(data.record));
  const src = el("p", { class: "small" });
  const link = el("a", { href: data.source, rel: "noopener" }, "This product on Open Food Facts");
  src.append(link);
  box.append(src);
  $("question").disabled = false;
  $("askBtn").disabled = false;
  $("answer").replaceChildren();
  $("question").focus();
}

async function ask(event) {
  event.preventDefault();
  if (!current) return;
  const question = $("question").value.trim();
  if (question.length < 3) return;
  const out = $("answer");
  out.replaceChildren(el("p", { class: "small muted" }, "Asking…"));
  $("askBtn").disabled = true;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: current.code, question }),
    });
    const data = await res.json().catch(() => ({}));
    out.replaceChildren();
    if (!res.ok) {
      out.append(el("p", { class: "small" }, data.detail || "The assistant is unavailable right now."));
      return;
    }
    out.append(badge(data.outcome));
    if (data.reply) out.append(el("p", {}, data.reply));
    if (data.evidence && data.evidence.length) {
      const ul = el("ul", { class: "small" });
      for (const item of data.evidence) {
        const li = el("li");
        li.append(el("code", {}, item.field), document.createTextNode(`: ${item.value}`));
        ul.append(li);
      }
      out.append(el("p", { class: "small muted" }, "Evidence cited by the assistant"), ul);
    }
    if (data.cost_usd !== undefined) {
      out.append(el("p", { class: "small muted" },
        `${data.seconds}s · $${data.cost_usd.toFixed(4)} · ${data.served_by || ""}`));
    }
  } finally {
    $("askBtn").disabled = false;
  }
}

async function examples() {
  const box = $("examples");
  const res = await fetch("/api/examples");
  const items = res.ok ? await res.json() : [];
  if (!items.length) {
    box.replaceChildren(el("p", { class: "small muted" }, "Examples appear here after the test run is published."));
    return;
  }
  box.replaceChildren();
  for (const ex of items) {
    const card = el("div", { class: "card" });
    const context = ex.condition === "retrieval"
      ? `With similar products in context: ${ex.also_in_context.join("; ")}`
      : "Exact record only";
    card.append(el("p", { class: "small muted" }, `${ex.product_name} · ${context}`));
    card.append(el("h3", {}, ex.question));
    card.append(el("p", { class: "small" }, `The record says: ${ex.record_says}`));
    const table = el("table");
    for (const cfg of ["A", "B", "C", "C+check"]) {
      const a = ex.answers[cfg];
      if (!a) continue;
      const tr = el("tr");
      tr.append(el("th", {}, CONFIG_NAMES[cfg]));
      const td = el("td");
      td.append(badge(a.outcome));
      if (a.matches_neighbor) td.append(el("span", { class: "small muted" }, " · matches another product's record"));
      if (a.reply && cfg !== "C+check") td.append(el("div", { class: "small" }, a.reply));
      tr.append(td);
      table.append(tr);
    }
    card.append(table);
    box.append(card);
  }
}

const CHIPS = [
  "How much sugar per 100 g?", "Does it contain milk?", "What is its Nutri-Score grade?",
  "Is it gluten-free?", "How much fiber per 100 g?",
];
for (const text of CHIPS) {
  const b = el("button", { type: "button", class: "ghost" }, text);
  b.addEventListener("click", () => { $("question").value = text; $("question").focus(); });
  $("chips").append(b);
}

$("search").addEventListener("input", (e) => {
  clearTimeout(timer);
  timer = setTimeout(() => search(e.target.value), 180);
});
$("ask").addEventListener("submit", ask);
search("");
examples();
