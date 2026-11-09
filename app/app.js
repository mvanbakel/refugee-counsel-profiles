/* Know Your Lawyer — static single-page app.
   Data: data/profiles.json, built by src/profiles.py. */

"use strict";

const API = "https://api.a2aj.ca/fetch";
const PAGE = 30;
const view = document.getElementById("view");
const tip = document.getElementById("tooltip");

let DATA = null;
let BY_ID = new Map();
const state = { q: "", country: "", sort: "decisions", min5: true, shown: PAGE };

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const num = (x, d = 1) => (Number.isInteger(x) ? String(x) : x.toFixed(d));
const plural = (n, one, many = one + "s") => `${num(n)} ${n === 1 ? one : many}`;
const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const years = (p) => (p.first_year === p.last_year ? `${p.first_year}` : `${p.first_year}–${p.last_year}`);
const fmtDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });

function countryCount(p, c) {
  if (!c) return 0;
  return p.cases.filter((x) => x.co === c && x.t === "claim").length;
}

const VERDICT = {
  above: { short: "Above expected", long: "More published acceptances than expected for similar cases" },
  in_line: { short: "In line with similar cases", long: "In line with similar cases — the data can't tell this counsel apart from the average" },
  below: { short: "Below expected", long: "Fewer published acceptances than expected for similar cases" },
  not_enough: { short: "Too few cases to compare", long: "Not enough published decisions to compare fairly" },
};
// For "no credible basis", fewer is better, so the colours flip.
const NCB_VERDICT = {
  above: { cls: "below", text: "More “no credible basis” findings than expected" },
  in_line: { cls: "in_line", text: "In line with similar cases" },
  below: { cls: "above", text: "Fewer “no credible basis” findings than expected" },
  not_enough: { cls: "not_enough", text: "Too few cases to compare" },
};

function badge(v, text) {
  return `<span class="badge ${esc(v)}">${esc(text ?? VERDICT[v].short)}</span>`;
}

function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      tip.textContent = el.getAttribute("data-tip");
      tip.style.left = Math.min(e.clientX + 12, window.innerWidth - 250) + "px";
      tip.style.top = e.clientY + 14 + "px";
      tip.classList.add("show");
    });
    el.addEventListener("mouseleave", () => tip.classList.remove("show"));
  });
}

// ---------- routing ----------
function route() {
  tip.classList.remove("show");
  const h = location.hash.replace(/^#/, "") || "/";
  const [, page, id] = h.split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => a.removeAttribute("aria-current"));
  if (page === "counsel" && id) {
    renderProfile(decodeURIComponent(id));
  } else if (page === "about") {
    document.querySelector('[data-nav="about"]').setAttribute("aria-current", "page");
    renderAbout();
  } else {
    document.querySelector('[data-nav="home"]').setAttribute("aria-current", "page");
    renderHome();
  }
}

// ---------- home ----------
function filtered() {
  const q = fold(state.q.trim());
  let list = DATA.profiles.filter((p) => {
    if (state.min5 && p.decisions < 5) return false;
    if (q && !fold(p.name).includes(q)) return false;
    if (state.country && countryCount(p, state.country) === 0) return false;
    return true;
  });
  const by = {
    decisions: (a, b) => b.decisions - a.decisions,
    country: (a, b) => countryCount(b, state.country) - countryCount(a, state.country) || b.decisions - a.decisions,
    recent: (a, b) => b.last_year - a.last_year || b.decisions - a.decisions,
    results: (a, b) => {
      const r = (p) => (p.vs_expected.ratio == null ? -1 : p.vs_expected.ratio);
      return r(b) - r(a) || b.decisions - a.decisions;
    },
    name: (a, b) => a.name.localeCompare(b.name),
  }[state.sort];
  return list.sort(by);
}

function renderHome() {
  document.title = "Find counsel · Know Your Lawyer";
  const o = DATA.overall;
  const countryOpts = DATA.countries
    .map((c) => `<option value="${esc(c.name)}"${c.name === state.country ? " selected" : ""}>${esc(c.name)}</option>`)
    .join("");
  view.innerHTML = `
    <section class="intro">
      <div>
        <h1>Find out who has argued refugee claims, and how their cases went</h1>
        <p>Profiles of ${DATA.profiles.length.toLocaleString()} lawyers and representatives who appear in
          ${o.decisions.toLocaleString()} published decisions of the Refugee Protection Division (${o.years[0]}–${o.years[1]}).
          See how much experience each one has, which countries their clients came from, and how their results compare with similar cases.</p>
      </div>
      <div class="note" role="note">
        <strong>Read this first</strong>
        The Board publishes only a small, mostly negative share of its decisions: about ${pct(o.accepted_rate)} of the claims here were accepted, far below the real rate.
        Use these profiles to compare experience, not as a lawyer's true success rate. <a href="#/about">How it works</a>
      </div>
    </section>

    <form class="controls" id="controls" role="search" onsubmit="return false">
      <div class="field field-search">
        <label for="q">Search by name</label>
        <input type="search" id="q" placeholder="e.g. Silcoff" value="${esc(state.q)}" autocomplete="off">
      </div>
      <div class="field">
        <label for="country">Claimant's country</label>
        <select id="country"><option value="">Any country</option>${countryOpts}</select>
      </div>
      <div class="field">
        <label for="sort">Sort by</label>
        <select id="sort">
          <option value="decisions">Most decisions</option>
          <option value="country"${state.country ? "" : " disabled"}>Most cases from this country</option>
          <option value="results">Results vs similar cases</option>
          <option value="recent">Most recent</option>
          <option value="name">Name (A–Z)</option>
        </select>
      </div>
      <label class="check"><input type="checkbox" id="min5"${state.min5 ? " checked" : ""}> 5+ decisions only</label>
    </form>
    <p class="country-context" id="country-context"></p>
    <div class="results-meta"><span id="count" aria-live="polite"></span></div>
    <ul class="list" id="list"></ul>
    <div id="more-wrap"></div>`;

  document.getElementById("sort").value = state.sort;
  const update = () => { state.shown = PAGE; drawList(); };
  document.getElementById("q").addEventListener("input", (e) => { state.q = e.target.value; update(); });
  document.getElementById("country").addEventListener("change", (e) => {
    state.country = e.target.value;
    const sortSel = document.getElementById("sort");
    sortSel.querySelector('option[value="country"]').disabled = !state.country;
    if (state.country && state.sort === "decisions") state.sort = "country";
    if (!state.country && state.sort === "country") state.sort = "decisions";
    sortSel.value = state.sort;
    update();
  });
  document.getElementById("sort").addEventListener("change", (e) => { state.sort = e.target.value; update(); });
  document.getElementById("min5").addEventListener("change", (e) => { state.min5 = e.target.checked; update(); });
  drawList();
}

function drawList() {
  const list = filtered();
  const ctx = document.getElementById("country-context");
  const c = DATA.countries.find((x) => x.name === state.country);
  ctx.innerHTML = c
    ? `Across all counsel, ${pct(c.rate, 1)} of the ${c.claims.toLocaleString()} published claims from ${esc(c.name)} were accepted. Counsel are sorted by how many ${esc(c.name)} claims they handled.`
    : "";
  document.getElementById("count").textContent = `${list.length.toLocaleString()} ${list.length === 1 ? "profile" : "profiles"}`;
  const ul = document.getElementById("list");
  if (!list.length) {
    ul.innerHTML = `<li class="empty">No counsel match. Try another spelling, or untick “5+ decisions only”.</li>`;
    document.getElementById("more-wrap").innerHTML = "";
    return;
  }
  ul.innerHTML = list.slice(0, state.shown).map((p) => {
    const cc = countryCount(p, state.country);
    const big = state.country ? cc : p.decisions;
    const bigLabel = state.country ? `${esc(state.country)} claims` : "decisions";
    const chips = p.countries.slice(0, 4)
      .map(([n, k]) => `<span class="chip${n === state.country ? " hl" : ""}">${esc(n)} · ${k}</span>`).join("");
    // Verdicts are shown only on the profile, next to their explanation, not as bare labels here.
    return `<li><a class="card" href="#/counsel/${encodeURIComponent(p.id)}">
      <div>
        <div class="card-name">${esc(p.name)}</div>
        <div class="card-sub">${years(p)} · ${plural(p.decisions, "decision")} · ${plural(p.countries_n, "country", "countries")}</div>
      </div>
      <div class="card-right">
        <div class="card-big">${big}</div><div class="card-big-label">${bigLabel}</div>
      </div>
      <div class="chips">${chips}</div>
    </a></li>`;
  }).join("");
  const mw = document.getElementById("more-wrap");
  mw.innerHTML = list.length > state.shown
    ? `<button type="button" class="more" id="more">Show more (${(list.length - state.shown).toLocaleString()} left)</button>` : "";
  const more = document.getElementById("more");
  if (more) more.addEventListener("click", () => { state.shown += PAGE; drawList(); });
}

// ---------- profile ----------
function ratioChart(cmp) {
  // Dot = this counsel's ratio; band = 95% range; dashed line = what similar cases would predict.
  const W = 520, H = 74, L = 8, R = 8, max = Math.max(4, Math.ceil(cmp.hi || 0));
  const x = (v) => L + (Math.min(v, max) / max) * (W - L - R);
  const ticks = [];
  for (let t = 0; t <= max; t++) ticks.push(t);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Results ratio ${cmp.ratio}, 95% range ${cmp.lo} to ${cmp.hi}. 1 means the same as similar cases.">
    ${ticks.map((t) => `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="10" y2="44"/><text x="${x(t)}" y="62" text-anchor="middle">${t}×</text>`).join("")}
    <line class="ref" x1="${x(1)}" x2="${x(1)}" y1="4" y2="48"/>
    <line class="range" x1="${x(cmp.lo)}" x2="${x(cmp.hi)}" y1="27" y2="27"
      data-tip="Likely range: ${cmp.lo}× to ${cmp.hi}× the expected number"/>
    <circle class="dot" cx="${x(cmp.ratio)}" cy="27" r="7"
      data-tip="${cmp.ratio}× the acceptances expected for similar cases"/>
  </svg>
  <div class="small muted" style="display:flex;justify-content:space-between;margin-top:2px">
    <span>Fewer acceptances</span><span>Dashed line = similar cases</span><span>More acceptances</span>
  </div>`;
}

function yearChart(p) {
  const counts = {};
  p.cases.forEach((c) => { counts[c.y] = (counts[c.y] || 0) + 1; });
  const y0 = DATA.overall.years[0], y1 = DATA.overall.years[1];
  const ys = [];
  for (let y = y0; y <= y1; y++) ys.push(y);
  const max = Math.max(...Object.values(counts));
  const W = 520, H = 150, B = 22, T = 10, step = W / ys.length, bw = Math.max(4, step - 4);
  const h = (v) => (v / max) * (H - B - T);
  const gridVals = [Math.round(max / 2), max].filter((v, i, a) => v > 0 && a.indexOf(v) === i);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Decisions per year, ${y0} to ${y1}">
    ${gridVals.map((v) => `<line class="grid" x1="0" x2="${W}" y1="${H - B - h(v)}" y2="${H - B - h(v)}"/><text x="${W}" y="${H - B - h(v) - 4}" text-anchor="end">${v}</text>`).join("")}
    <line class="axis" x1="0" x2="${W}" y1="${H - B}" y2="${H - B}"/>
    ${ys.map((y, i) => {
      const v = counts[y] || 0, bx = i * step + (step - bw) / 2;
      const label = (y - y0) % 3 === 0 ? `<text x="${bx + bw / 2}" y="${H - 6}" text-anchor="middle">${y}</text>` : "";
      const bar = v ? `<path class="bar" d="M${bx},${H - B} v${-(h(v) - 3)} q0,-3 3,-3 h${bw - 6} q3,0 3,3 v${h(v) - 3} z"/>` : "";
      return `<g data-tip="${y}: ${plural(v, "decision")}"><rect class="hit" x="${i * step}" y="${T}" width="${step}" height="${H - B - T}"/>${bar}</g>${label}`;
    }).join("")}
  </svg>`;
}

function hbars(rows, unit) {
  if (!rows.length) return `<p class="muted small">None recorded.</p>`;
  const max = Math.max(...rows.map((r) => r[1]));
  return `<ul class="hbars">${rows.map(([n, k]) => `
    <li class="hbar" data-tip="${esc(n)}: ${plural(k, unit)}">
      <span class="hbar-label">${esc(n)}</span>
      <span class="hbar-track"><span class="hbar-fill" style="width:${(k / max) * 100}%"></span></span>
      <span class="hbar-val">${k}</span>
    </li>`).join("")}</ul>`;
}

function renderProfile(id) {
  const p = BY_ID.get(id);
  if (!p) {
    view.innerHTML = `<a class="crumb" href="#/">← All counsel</a><div class="panel empty">No profile found.</div>`;
    return;
  }
  document.title = `${p.name} · Know Your Lawyer`;
  const cmp = p.vs_expected;
  const ncb = p.ncb_vs_expected;
  const claims = p.claims;
  const nAcc = p.cases.filter((c) => c.t === "claim" && c.o === "accepted").length;
  const nSplit = p.cases.filter((c) => c.t === "claim" && c.o === "split").length;
  const splitNote = nSplit ? ` and partly accepted in <strong>${nSplit}</strong> (some family members accepted, others not; each counts as half)` : "";
  const resultLine = claims
    ? `Accepted in <strong>${nAcc}</strong>${splitNote} of ${plural(claims, "published claim")}. For claims from the same countries, before the same board members, in the same years, with the Minister involved as often, we would expect about <strong>${num(p.expected_accepted, 1)}</strong>.`
    : "No decided claims in the published decisions.";
  const otherTypes = Object.entries(p.other_types)
    .map(([k, v]) => `${v} ${({ cessation: "cessation", vacation: "vacation", reopening: "reopening", abandonment: "abandonment", reinstatement: "reinstatement" })[k] || k}`).join(", ");
  const countryOpts = [...new Set(p.cases.map((c) => c.co).filter(Boolean))].sort()
    .map((c) => `<option>${esc(c)}</option>`).join("");

  view.innerHTML = `
    <a class="crumb" href="#/">← All counsel</a>
    <div class="profile-head">
      <div>
        <h1>${esc(p.name)}</h1>
        <p class="muted" style="margin:0">Appears in ${plural(p.decisions, "published decision")} · ${years(p)} · ${p.regions.map(([r]) => esc(r)).join(", ")}</p>
      </div>
      ${badge(cmp.verdict, VERDICT[cmp.verdict].short)}
    </div>

    <div class="tiles">
      <div class="tile"><div class="tile-value">${p.decisions}</div><div class="tile-label">Published decisions</div></div>
      <div class="tile"><div class="tile-value">${claims}</div><div class="tile-label">Refugee claims decided</div></div>
      <div class="tile"><div class="tile-value">${p.countries_n}</div><div class="tile-label">Claimants' countries</div></div>
      <div class="tile"><div class="tile-value">${p.last_year - p.first_year + 1}</div><div class="tile-label">Years active (${years(p)})</div></div>
    </div>

    <div class="grid-2">
      <section class="panel" aria-labelledby="h-res">
        <h2 id="h-res">Results compared with similar cases</h2>
        <p class="verdict">${esc(VERDICT[cmp.verdict].long)}</p>
        <p class="small">${resultLine}</p>
        ${cmp.verdict !== "not_enough" ? ratioChart(cmp) : `<p class="small muted">A fair comparison needs at least 2 expected acceptances. Because so few published decisions are positive, most counsel don't reach that.</p>`}
        <details class="explain"><summary>What does this mean?</summary>
          <p>Acceptance rates depend heavily on where the claimant is from, which board member hears the case, and whether the Minister intervenes. We estimate each claim's chance of acceptance from other claims that share these features, then add these up. Published decisions are mostly negative, so treat this as a rough signal only. A ratio of 1× means this counsel's published results match what similar cases would predict. The band shows the likely range given the small numbers: a verdict appears only when the whole band sits above or below 1×.</p>
        </details>
      </section>

      <section class="panel" aria-labelledby="h-ncb">
        <h2 id="h-ncb">“No credible basis” findings</h2>
        <p class="verdict">${badge(NCB_VERDICT[ncb.verdict].cls, NCB_VERDICT[ncb.verdict].text)}</p>
        <p class="small">${claims ? `Found in <strong>${p.ncb}</strong> of ${plural(claims, "claim")}; about <strong>${num(p.expected_ncb, 1)}</strong> expected for similar cases.` : ""}</p>
        <p class="small muted">A “no credible basis” or “manifestly unfounded” finding is the harshest rejection. It takes away the right to appeal to the Refugee Appeal Division. Fewer is better.</p>
        ${p.minister_cases ? `<p class="small">The Minister intervened against the claimant in <strong>${p.minister_cases}</strong> of these claims; ${num(p.minister_accepted)} accepted.</p>` : ""}
        ${otherTypes ? `<p class="small muted">Also appeared in other proceedings: ${esc(otherTypes)}.</p>` : ""}
      </section>
    </div>

    <div class="grid-2">
      <section class="panel" aria-labelledby="h-co">
        <h2 id="h-co">Where clients came from</h2>
        ${hbars(p.countries, "claim")}
      </section>
      <section class="panel" aria-labelledby="h-yr">
        <h2 id="h-yr">Decisions per year</h2>
        ${yearChart(p)}
      </section>
    </div>

    <div class="grid-2">
      <section class="panel" aria-labelledby="h-pa">
        <h2 id="h-pa">Board members heard by most often</h2>
        ${hbars(p.panels, "claim")}
      </section>
      <section class="panel" aria-labelledby="h-jc">
        <h2 id="h-jc">Worked alongside</h2>
        ${p.joint_counsel.length
          ? `<ul class="small" style="margin:0;padding-left:18px">${p.joint_counsel.map((n) => {
              const q = DATA.profiles.find((x) => x.name === n);
              return `<li>${q ? `<a href="#/counsel/${encodeURIComponent(q.id)}">${esc(n)}</a>` : esc(n)}</li>`;
            }).join("")}</ul>`
          : `<p class="muted small">No co-counsel named in these decisions.</p>`}
        <p class="small muted" style="margin-top:12px">Before hiring, check that the representative is licensed: lawyers with their provincial law society, and immigration consultants with the College of Immigration and Citizenship Consultants.</p>
      </section>
    </div>

    <section class="panel" aria-labelledby="h-dec" style="margin-top:16px">
      <h2 id="h-dec">All published decisions</h2>
      <div class="table-tools">
        <div class="field"><label for="f-co">Country</label><select id="f-co"><option value="">All countries</option>${countryOpts}</select></div>
        <div class="field"><label for="f-res">Result</label><select id="f-res"><option value="">All results</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="split">Split</option></select></div>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>File</th><th>Country</th><th>Board member</th><th>Result</th><th>Notes</th><th><span class="sr-only">Read</span></th></tr></thead>
        <tbody id="rows"></tbody>
      </table></div>
    </section>`;

  const drawRows = () => {
    const co = document.getElementById("f-co").value, res = document.getElementById("f-res").value;
    const rows = p.cases.filter((c) => (!co || c.co === co) && (!res || c.o === res));
    const typeName = { claim: "", cessation: "Cessation", vacation: "Vacation", reopening: "Reopening", abandonment: "Abandonment", reinstatement: "Reinstatement" };
    document.getElementById("rows").innerHTML = rows.length ? rows.map((c) => `
      <tr>
        <td class="tnum">${fmtDate(c.d)}</td>
        <td class="tnum">${esc(c.c)}</td>
        <td>${esc(c.co || "—")}</td>
        <td>${esc(c.p || "—")}</td>
        <td><span class="res ${esc(c.o)}">${esc({ accepted: "Accepted", rejected: "Rejected", split: "Split", unknown: "Unclear" }[c.o] || c.o)}</span></td>
        <td>${c.t !== "claim" ? `<span class="flag">${typeName[c.t]}</span>` : ""}${c.ncb ? `<span class="flag ncb">No credible basis</span>` : ""}${c.m ? `<span class="flag">Minister intervened</span>` : ""}</td>
        <td><button type="button" class="btn-link" data-read="${esc(c.c)}">Read</button></td>
      </tr>`).join("") : `<tr><td colspan="7" class="muted">No decisions match.</td></tr>`;
    document.querySelectorAll("[data-read]").forEach((b) => b.addEventListener("click", () => openReader(b.dataset.read)));
  };
  document.getElementById("f-co").addEventListener("change", drawRows);
  document.getElementById("f-res").addEventListener("change", drawRows);
  drawRows();
  bindTips(view);
  window.scrollTo(0, 0);
}

// ---------- reader ----------
const dlg = document.getElementById("reader");
document.getElementById("reader-close").addEventListener("click", () => dlg.close());
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

async function openReader(citation) {
  const body = document.getElementById("reader-body");
  document.getElementById("reader-title").textContent = `Decision ${citation}`;
  body.innerHTML = `<p class="loading">Loading decision…</p>`;
  dlg.showModal();
  try {
    const r = await fetch(`${API}?citation=${encodeURIComponent(citation)}&doc_type=cases`);
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    const text = j.results?.[0]?.unofficial_text_en;
    body.innerHTML = text ? `<pre>${esc(text)}</pre>` : `<p>This decision's text isn't available.</p>`;
  } catch (err) {
    body.innerHTML = `<p>Couldn't load the decision (${esc(err.message)}). Check your internet connection and try again.</p>`;
  }
}

// ---------- about ----------
function renderAbout() {
  document.title = "How it works · Know Your Lawyer";
  const o = DATA.overall;
  view.innerHTML = `<article class="prose">
    <h1>How it works</h1>
    <p>People claiming refugee protection in Canada often have to choose a lawyer or consultant with little information. This site gathers what the public record says about the representatives who appear before the Refugee Protection Division (RPD) of the Immigration and Refugee Board.</p>

    <h2>Where the information comes from</h2>
    <p>${o.decisions.toLocaleString()} published RPD decisions from ${o.years[0]} to ${o.years[1]}, collected by the
      <a href="https://a2aj.ca/data/" rel="noopener">Access to Algorithmic Justice (A2AJ)</a> project directly from the Board. Claimants' names are removed in the source. Each decision's header names the board member and the claimant's counsel; the reasons give the result.</p>

    <h2>What we measure</h2>
    <ul>
      <li><strong>Experience:</strong> how many published decisions name the representative, over which years, and in which regional offices.</li>
      <li><strong>Specialization:</strong> the countries their clients came from and the board members who heard them.</li>
      <li><strong>Results compared with similar cases:</strong> each claim's chance of acceptance is estimated from other claims with the same country, board member and three-year period, and from whether the Minister intervened (never from the claim itself). We compare the counsel's actual acceptances with the total of those estimates. A verdict appears only when the 95% range is entirely above or below “as expected”.</li>
      <li><strong>“No credible basis” findings:</strong> the harshest form of rejection, compared with similar cases in the same way.</li>
    </ul>

    <h2>Important limits</h2>
    <ul>
      <li><strong>Published decisions aren't all decisions.</strong> The Board publishes a small share of its decisions, and mostly negative ones: only ${pct(o.accepted_rate)} of the claims here were accepted, while the real acceptance rate is far higher. A representative's real success rate can't be read from this data. Comparisons between representatives are fairer, but still limited.</li>
      <li><strong>Small numbers.</strong> Most representatives appear in only a few decisions. With so few acceptances in the data, only a handful have enough cases for a results comparison.</li>
      <li><strong>Names are matched automatically.</strong> We merge spellings (e.g. “I. Hamilton” and “Ian D. Hamilton”) only when one person clearly fits. Different people with the same name may be combined, and one person may appear twice.</li>
      <li><strong>A good lawyer can lose.</strong> Results depend on the facts of each claim. Lawyers who take difficult cases may show weaker numbers.</li>
      <li><strong>The data ends in ${o.years[1]}.</strong> Representatives may have changed firms, retired or become board members.</li>
    </ul>

    <h2>Before you hire anyone</h2>
    <ul>
      <li>Check that the person is licensed: lawyers with their provincial law society (for example the Law Society of Ontario directory or the Barreau du Québec), and immigration consultants on the register of the College of Immigration and Citizenship Consultants.</li>
      <li>If you can't afford a lawyer, ask your provincial legal aid office about refugee claims.</li>
      <li>Ask the representative about their experience with claims like yours.</li>
    </ul>

    <h2>About this project</h2>
    <p>A legal engineering class project. The code that extracts the data and builds these profiles is open, so every number can be checked. This site is not legal advice and doesn't recommend any representative.</p>
  </article>`;
  window.scrollTo(0, 0);
}

// ---------- start ----------
fetch("data/profiles.json")
  .then((r) => r.json())
  .then((d) => {
    DATA = d;
    BY_ID = new Map(d.profiles.map((p) => [p.id, p]));
    window.addEventListener("hashchange", route);
    route();
  })
  .catch(() => { view.innerHTML = `<p class="empty">Couldn't load the profile data. Run <code>src/profiles.py</code> and serve the <code>app/</code> folder.</p>`; });
