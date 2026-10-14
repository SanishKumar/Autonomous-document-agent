import { createTeamUI } from "./team.js";
import { createHandoffs } from "./handoffs.js";
import { SessionScope } from "./session-scope.mjs";
import { comparisonPicker, comparisonResult } from "./comparison.js";

const $ = (s, root = document) => root.querySelector(s);
const esc = (s = "") =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const paths = {
  home: "M3 10l9-7 9 7M5 9v12h5v-7h4v7h5V9",
  file: "M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  clock: "M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14M14 7l5 5-5 5",
  up: "M6 18L18 6M7 6h11v11",
  search: "M16 16l5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  chevron: "M9 5l7 7-7 7",
  down: "M6 9l6 6 6-6",
  check: "M5 12l4 4L19 6",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
  spark: "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6",
  edit: "M14 5l5 5M4 20l4-1L20 7a2 2 0 0 0-3-3L5 16z",
  download: "M12 3v12M7 10l5 5 5-5M4 16v5h16v-5",
  close: "M6 6l12 12M6 18L18 6",
  layers: "M12 3l10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5",
  branch: "M6 3v12a4 4 0 0 0 4 4h7M6 9h9a3 3 0 0 0 3-3V3M14 16l3 3-3 3",
  menu: "M4 6h16M4 12h16M4 18h16",
};
const icon = (name, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
const label = (value) =>
  ({
    project_plan: "Project plan",
    specification: "Specification",
    sop: "Playbook",
    proposal: "Proposal",
    report: "Report",
    needs_review: "Needs review",
    completed: "Ready",
    running: "In progress",
    queued: "Queued",
    cancelled: "Cancelled",
    failed: "Failed",
    interrupted: "Interrupted",
  })[value] || value;
const date = (value) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
const fullDate = (value) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const state = {
  session: null,
  config: null,
  documents: [],
  doc: null,
  filter: "all",
  query: "",
  page: "home",
  tab: "document",
  editing: false,
  stream: null,
  history: null,
};
let toastTimer,
  refreshTimer,
  saving = false;
let activeHash = location.hash;
let routeSequence = 0;
const sessionScope = new SessionScope();
const canEdit = () => ["owner", "editor"].includes(state.session?.user?.role);
const canReview = () => ["owner", "reviewer"].includes(state.session?.user?.role);
const briefKey = () => `briefroom-unsent-${state.session?.user?.id}`;

function clearSession() {
  sessionScope.reset();
  routeSequence += 1;
  state.stream?.close();
  clearTimeout(refreshTimer);
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  document.querySelectorAll("dialog").forEach((dialog) => (dialog.innerHTML = ""));
  state.session = null;
  state.doc = null;
  state.documents = [];
  state.history = null;
  state.config = null;
  state.editing = false;
  state.query = "";
  team.reset();
  handoffs.reset();
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `visible${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.className = ""), 4500);
}
async function api(url, options = {}) {
  const checkSession = sessionScope.capture();
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(state.session?.csrf_token ? { "X-CSRF-Token": state.session.csrf_token } : {}), ...options.headers },
  });
  checkSession();
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      body = { detail: "The workspace could not complete this request." };
    }
    checkSession();
    const error = Array.isArray(body.detail)
      ? body.detail
          .map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`)
          .join("; ")
      : body.detail;
    const failure = new Error(error || "Something went wrong. Please try again.");
    failure.status = response.status;
    if (response.status === 401 && !["/api/auth/login", "/api/auth/setup", "/api/auth/join"].includes(url)) {
      clearSession();
      team.authScreen();
    }
    throw failure;
  }
  const body = await response.json();
  checkSession();
  return body;
}
const post = (url, data = {}) =>
  api(url, { method: "POST", body: JSON.stringify(data) });
const handoffs = createHandoffs({ state, api, post, esc, icon, date: fullDate, shell, toast,
  refreshReview: () => team.loadReview(),
});
const team = createTeamUI({ state, api, post, esc, icon, date: fullDate, shell, toast,
  onSession: async (session) => { sessionScope.reset(); state.session = session; state.config = await api("/api/config"); await route(); },
  onLogout: async () => { forgetBrief(); clearSession(); state.session = await api("/api/auth/session"); team.authScreen(); },
  renderDocument: editor,
  handoffs,
});

function status(doc) {
  return `<span class="status ${esc(doc.status)}">${doc.approved_version === doc.version && doc.version ? "✓ Approved" : label(doc.status)}</span>`;
}
function shell(content, breadcrumb = "Overview") {
  const active = state.page === "document" ? "library" : state.page;
  const user = state.session.user;
  $("#app").innerHTML =
    `<div class="shell"><aside class="sidebar" aria-label="Workspace navigation">
    <a class="brand" href="#/home"><span class="brand-mark">b.</span>briefroom<small>LOCAL</small></a>
    <div class="workspace-switch"><span class="workspace-avatar">${esc(team.initials(state.session.workspace_name))}</span><div><strong>${esc(state.session.workspace_name)}</strong><small>Room for your team’s best work</small></div></div>
    ${canEdit() ? `<button class="new-button" data-action="new" aria-label="New document">${icon("plus")}<span>New document</span><kbd>N</kbd></button>` : '<div class="reviewer-note">Your fresh perspective matters.<br>Open a document to review.</div>'}
    <nav class="nav">${[
      ["home", "home", "Overview"],
      ["library", "file", "All documents"],
      ["inbox", "check", "Review inbox"],
      ["templates", "grid", "Templates"],
      ["about", "branch", "How it works"],
      ["team", "shield", "Team & access"],
    ]
      .map(
        ([id, i, name]) =>
          `<button data-nav="${id}" class="${active === id ? "active" : ""}" ${active === id ? 'aria-current="page"' : ""}>${icon(i)}<span>${name}</span>${id === "library" ? `<span class="count">${state.documents.length}</span>` : ""}</button>`,
      )
      .join("")}</nav>
    <div class="nav-label">MADE FOR YOUR WORK</div><div class="collection"><span class="dot"></span>Client engagements</div><div class="collection"><span class="dot"></span>Internal operations</div>
    <div class="sidebar-bottom"><div class="local-card"><strong><span class="dot"></span>Your team’s workspace</strong><p>Saved on your workspace server.<br>You choose when to use AI.</p></div>
    <div class="profile"><span class="profile-avatar">${esc(team.initials(user.name))}</span><div><strong>${esc(user.name)}</strong><small>${esc(user.role)} · ${state.session.auth_enabled ? "Team edition" : "Local demo"}</small></div><button class="icon-button" data-action="settings" aria-label="Workspace settings">${icon("settings")}</button></div></div>
  </aside><div class="main-wrap"><header class="topbar"><div class="breadcrumb"><span>Workspace</span><span>/</span><strong>${esc(breadcrumb)}</strong></div><div class="top-actions"><button class="search-trigger" data-action="search">${icon("search")}Search documents<kbd>Ctrl K</kbd></button><span class="top-tag"><span class="dot"></span>Shared with your team</span><button class="icon-button" data-action="settings" aria-label="Settings">${icon("settings")}</button></div></header>
  <main id="main" tabindex="-1">${content}</main></div></div>`;
}
function templateCards(all = false) {
  return `<div class="templates ${all ? "template-gallery" : ""}">${state.config.templates
    .slice(0, all ? 5 : 4)
    .map(
      (t, i) =>
        `<button class="template" data-template="${t.id}"><div class="template-icon">${icon(["file", "layers", "menu", "branch", "file"][i])}</div>${icon("up", "small-arrow")}<strong>${esc(t.name)}</strong><p>${esc(t.description)}</p></button>`,
    )
    .join("")}</div>`;
}
function filteredDocuments() {
  return state.documents.filter(
    (d) =>
      (state.filter === "all" || d.status === state.filter) &&
      (d.title + " " + d.brief)
        .toLowerCase()
        .includes(state.query.toLowerCase()),
  );
}
function rows() {
  const docs = filteredDocuments();
  return docs.length
    ? `<div class="list-header"><span>DOCUMENT NAME</span><span class="type-col">TYPE</span><span>STATUS</span><span class="date-col">UPDATED</span><span></span></div>${docs.map((d) => `<a class="document-row" href="#/document/${d.id}" aria-label="Open ${esc(d.title)}"><div class="doc-name"><span class="doc-symbol">${icon("file")}</span><div><strong>${esc(d.title)}</strong><small>${d.sample ? "Sample · " : ""}${esc(d.audience || "Your workspace")}</small></div></div><span class="row-type">${esc(label(d.document_type))}</span>${status(d)}<span class="row-date">${date(d.updated_at)}</span>${icon("chevron", "row-chevron")}</a>`).join("")}`
    : `<div class="empty">${icon("search")}<h3>${state.query || state.filter !== "all" ? "Nothing here just yet" : "A fresh page awaits"}</h3><p>${state.query || state.filter !== "all" ? "Try another search or filter." : "Start with a brief, or explore one of the templates."}</p><button class="primary" data-action="${state.query || state.filter !== "all" ? "clear" : "new"}">${state.query || state.filter !== "all" ? "Clear filters" : "Create your first document"}</button></div>`;
}
function libraryBlock() {
  return `<div class="section-title"><h2>${state.page === "home" ? "Your documents" : "Document library"}</h2><span>A home for work worth sharing</span><button class="text-button" data-action="refresh">${icon("clock")}Refresh</button></div><div class="library-toolbar"><div class="filters">${[
    ["all", "All documents"],
    ["needs_review", "Needs review"],
    ["completed", "Ready"],
  ]
    .map(
      ([id, name]) =>
        `<button class="filter ${state.filter === id ? "active" : ""}" data-filter="${id}">${name}</button>`,
    )
    .join(
      "",
    )}</div><label class="library-search">${icon("search")}<input id="library-search" aria-label="Search documents" placeholder="Find a document…" value="${esc(state.query)}"></label></div><div class="document-list" id="document-list">${rows()}</div>`;
}
function home() {
  shell(`<div class="home"><div class="eyebrow">YOUR SPACE TO THINK, CREATE & DELIVER</div><section class="hero"><div><h1>Good thinking.<br><em>Great documents.</em></h1><p>From the first scattered thought to the final, considered draft.<br>Let’s make something worth sharing.</p></div><div class="hero-art" aria-hidden="true"><div class="art-orbit"></div><div class="art-orbit second"></div><div class="art-page back"><b></b><i></i><i></i><i></i></div><div class="art-page"><div class="tiny-mark"></div><b></b><i></i><i></i><i></i><i></i><i></i></div><div class="art-check">${icon("check")}</div><span class="art-spark">✧</span></div></section>
  <section class="quick-start"><div class="quick-icon">${icon("spark")}</div><div><strong>What are you working on?</strong><p>A client proposal, the next big project, or a process that needs clarity.</p></div><button class="primary" data-action="new">Start with a brief ${icon("arrow")}</button></section>
  <div class="section-title"><h2>A head start, thoughtfully made</h2><button class="text-button" data-nav="templates">All templates ${icon("arrow")}</button></div>${templateCards()}
  ${libraryBlock()}<footer class="workspace-footer"><span>${icon("shield")}A private workspace. A visible process. Your final say.</span><span>Made for work that moves things forward.</span></footer></div>`);
}
function library() {
  shell(
    `<div class="home"><div class="eyebrow">EVERY BRIEF HAS A HOME</div><section class="hero"><div><h1>Your work,<br><em>all in one place.</em></h1><p>Pick up a draft, review a decision, or revisit an earlier version.</p></div><button class="primary" data-action="new">${icon("plus")}New document</button></section>${libraryBlock()}</div>`,
    "All documents",
  );
}
function templates() {
  shell(
    `<div class="home"><div class="eyebrow">BLANK PAGE, MEET HEAD START</div><section class="hero"><div><h1>A little structure.<br><em>A lot of possibility.</em></h1><p>Each starting point gives your brief a useful shape. Make it your own.</p></div></section>${templateCards(true)}<div class="privacy-note">${icon("spark")}Templates prefill a brief. Creating a document uses your configured model; opening an existing sample does not.</div></div>`,
    "Templates",
  );
}
function about() {
  shell(
    `<div class="home"><div class="eyebrow">CLARITY, AT EVERY STEP</div><section class="hero"><div><h1>See the thinking.<br><em>Own the outcome.</em></h1><p>A document is only useful when you understand the choices behind it.</p></div></section><div class="about-grid">${[
      [
        "01",
        "Give it a real brief",
        "Describe the outcome, the audience, and the constraints. Add reference notes to keep the work close to your context.",
      ],
      [
        "02",
        "Watch the plan take shape",
        "The agent builds a plan and executes registered tools. The activity trail shows real tasks and their outcomes as they happen.",
      ],
      [
        "03",
        "Make the judgment calls",
        "Review assumptions, open questions and model feedback. Edit any section. Every save creates a version; approval is always your decision.",
      ],
      [
        "04",
        "Take the work with you",
        "Export the current version as a styled Word document. The brief, decision trail and version history stay in your local workspace.",
      ],
    ]
      .map(
        ([n, t, b]) =>
          `<div class="detail-card"><div class="about-number">${n}</div><h3>${t}</h3><p>${b}</p></div>`,
      )
      .join(
        "",
      )}</div><p class="gallery-intro">Briefroom is a shared workspace for one team. Live generation sends your brief and reference notes to the configured model provider. Sample documents are fictional and do not use a model. AI review is a useful signal, not factual verification. Your team’s discussions and approvals remain separate from model feedback.</p></div>`,
    "How it works",
  );
}

function field(path, text, tag = "p", attrs = "") {
  return `<${tag} ${state.editing ? `contenteditable="true" spellcheck="true" data-edit="${path}" role="textbox" aria-label="${esc(path.replaceAll(".", " "))}"` : ""} ${attrs}>${esc(text)}</${tag}>`;
}
function paper() {
  const d = state.doc,
    a = d.artifact,
    draft = a.draft;
  return `<article class="paper"><div class="paper-kicker"><span>BRIEFROOM / ${esc(label(d.document_type))}</span><span>VERSION ${d.version}</span></div>${field("title", d.title, "h1")}<div class="subtitle">Prepared for ${esc(d.audience)} · ${date(d.created_at)}</div><div class="paper-rule"></div><h2>Executive summary</h2><div class="summary-block">${field("draft.executive_summary", draft.executive_summary)}</div>
  ${draft.sections.map((s, i) => `${field(`draft.sections.${i}.heading`, s.heading, "h2")}${s.paragraphs.map((p, j) => field(`draft.sections.${i}.paragraphs.${j}`, p)).join("")}${s.bullets.length ? `<ul>${s.bullets.map((p, j) => field(`draft.sections.${i}.bullets.${j}`, p, "li")).join("")}</ul>` : ""}${s.numbered_items.length ? `<ol>${s.numbered_items.map((p, j) => field(`draft.sections.${i}.numbered_items.${j}`, p, "li")).join("")}</ol>` : ""}${s.table ? `<table><thead><tr>${s.table.headers.map((h, j) => field(`draft.sections.${i}.table.headers.${j}`, h, "th", 'scope="col"')).join("")}</tr></thead><tbody>${s.table.rows.map((r, j) => `<tr>${r.map((c, k) => field(`draft.sections.${i}.table.rows.${j}.${k}`, c, "td")).join("")}</tr>`).join("")}</tbody></table>` : ""}`).join("")}
  <h2>Closing note</h2>${field("draft.conclusion", draft.conclusion)}<div class="paper-foot">${d.sample ? "Fictional sample · Proposed targets require validation" : "Review assumptions and evidence before external use"} · ${esc(d.id.slice(0, 8))}</div></article>`;
}
function progress() {
  return (state.doc.tasks || [])
    .map(
      (t, i) =>
        `<div class="progress-item"><span class="step-marker ${t.status}">${t.status === "completed" ? icon("check") : i + 1}</span><div><strong>${esc(t.description)}</strong><small>${label(t.status)}${t.duration_ms !== undefined ? " · " + (t.duration_ms / 1000).toFixed(1) + "s" : ""}</small></div></div>`,
    )
    .join("");
}
function inspector() {
  const d = state.doc,
    a = d.artifact;
  const score = d.result?.quality_score;
  return `<aside class="inspector"><section class="inspector-card"><h3>${icon("shield")}Review & readiness</h3>${d.sample ? "<p>This is a curated example, so it has no AI review score.</p>" : `<div class="score">${score ?? "—"}<span> / 10 · model review</span></div><p>${d.version > 1 ? "This score belongs to the original generated draft. Your edits need a fresh human review." : a.review?.passed ? "The automated review passed. Check the evidence before sharing." : "Some issues still need your attention. Review the decision trail before sharing."}</p>`}<div class="score-note">${d.approved_version === d.version ? `${esc(d.approved_by?.name || "A reviewer")} approved version ${d.version}.` : "Team approval is separate from the AI review."}</div><button class="text-button" data-tab="review">Open team review ${icon("arrow")}</button></section><section class="inspector-card"><h3>${icon("branch")}Assumptions to check</h3><ul>${a.assumptions.map((s) => `<li>${esc(s)}</li>`).join("") || "<li>No assumptions recorded.</li>"}</ul><button class="text-button" data-tab="decisions">See decision trail ${icon("arrow")}</button></section><section class="inspector-card"><h3>${icon("layers")}Made to be yours</h3><p>Edit the document directly, keep a version history, and export your current draft to Word.</p><div class="score-note">${d.sample ? "Opening, editing and exporting this sample uses no API credits." : "Editing and exporting use no additional model calls."}</div></section></aside>`;
}
function editor() {
  const d = state.doc,
    busy = ["queued", "running"].includes(d.status);
  shell(
    `<div class="editor-toolbar"><div><h1>${esc(d.title)}</h1><div class="editor-meta">${status(d)}<span>${esc(label(d.document_type))}</span><span>${d.version ? "v" + d.version : "Preparing"} · ${date(d.created_at)}</span></div></div><div class="editor-buttons">${d.artifact ? (state.editing ? `<button class="secondary" data-action="discard">Discard</button><button class="primary" data-action="save">${icon("check")}Save version</button>` : `${canEdit() ? `<button class="secondary" data-action="edit">${icon("edit")}Edit draft</button>` : ""}${canReview() ? `<button class="secondary" ${d.approved_version === d.version ? 'data-action="approve"' : 'data-tab="review"'}>${icon("check")}${d.approved_version === d.version ? "Unapprove" : "Review"}</button>` : ""}<a class="primary" href="/api/documents/${d.id}/export">${icon("download")}Export Word</a>`) : canEdit() ? busy ? `<button class="secondary danger" data-action="cancel">Cancel run</button>` : `<button class="primary" data-action="retry">Try a new run ${icon("arrow")}</button>` : ""}</div></div>
  ${d.sample ? '<div class="sample-banner">Sample document · Fictional content to explore the workspace. No model was called.</div>' : ""}${state.editing ? '<div class="edit-banner">Editing draft · Click any text or table cell. Save creates a new version and clears the previous approval.</div>' : ""}
  <div class="editor-tabs">${[
    ["document", "file", "Document"],
    ["review", "shield", "Team review"],
    ["decisions", "branch", "Decision trail"],
    ["activity", "clock", "Activity & versions"],
  ]
    .map(
      ([id, i, t]) =>
        `<button data-tab="${id}" class="${state.tab === id ? "active" : ""}">${icon(i)}${t}</button>`,
    )
    .join("")}</div><div id="editor-content">${editorContent(busy)}</div>`,
    d.title,
  );
  if (state.tab === "review") {
    $(".review-columns > aside")?.insertAdjacentHTML("afterbegin", handoffs.panel());
  }
}
function editorContent(busy) {
  const d = state.doc;
  if (state.tab === "review") return team.reviewContent();
  if (state.tab === "decisions") return decisions();
  if (state.tab === "activity") return activity();
  if (d.artifact)
    return `<div class="editor-layout">${paper()}${inspector()}</div>`;
  return `<section class="status-view">${busy ? '<div class="spinner" aria-label="Run in progress"></div>' : icon("file")}<h1>${busy ? (d.plan ? "Your brief is taking shape." : "First, a plan.") : d.status === "cancelled" ? "Cancelled. Your brief is safe." : "This run needs another look."}</h1><p>${busy ? "You can leave this page. The run continues, and its progress is saved in your workspace." : esc(d.error || "No document was produced. Your original brief is preserved.")}</p>${d.tasks.length ? progress() : busy ? '<p class="muted">Waiting for the planner…</p>' : ""}${!busy ? '<button class="secondary" data-action="retry">Open the original brief</button>' : ""}</section>`;
}
function decisions() {
  const d = state.doc,
    a = d.artifact,
    plan = a?.plan || d.plan;
  return `<div class="detail-panel"><h2>A clear record of the choices.</h2><div class="detail-card"><h3>Your original brief</h3><p>${esc(d.brief)}</p></div>${d.context ? `<div class="detail-card"><h3>Your reference notes</h3><p>${esc(d.context)}</p><p class="muted">User-provided context; not independently verified.</p></div>` : ""}${
    plan
      ? [
          ["Assumptions", a?.assumptions || plan.assumptions],
          [
            "Decisions",
            [
              ...plan.decisions,
              ...(a?.resolution?.decisions || []).map(
                (r) => `${r.issue} — ${r.decision} ${r.impact}`,
              ),
            ],
          ],
          [
            "Open questions",
            d.result?.missing_information || plan.missing_information,
          ],
          ["Constraints", d.result?.constraints || plan.constraints],
          ["Deferred scope", a?.resolution?.deferred_items || []],
          [
            "Review feedback",
            [
              ...(a?.review?.missing_items || []),
              ...(a?.review?.contradictions || []),
            ],
          ],
          [
            "Run notes",
            [
              ...(a?.warnings || []),
              ...(d.result?.plan_source === "fallback"
                ? [
                    "The planner returned invalid output. A bounded fallback plan was used; document content was still generated by the model.",
                  ]
                : []),
            ],
          ],
        ]
          .filter(([, items]) => items.length)
          .map(
            ([title, items]) =>
              `<div class="detail-card"><h3>${title}</h3><ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>`,
          )
          .join("")
      : '<div class="detail-card"><p>The plan and its decisions will appear here as the run progresses.</p></div>'
  }</div>`;
}
function activity() {
  const d = state.doc;
  return `<div class="detail-panel"><h2>Every step. Every version.</h2>${d.tasks.length ? `<div class="detail-card"><h3>Execution plan</h3>${progress()}</div>` : ""}<div id="history-content">${state.history ? historyContent() : '<p class="muted">Loading history…</p>'}</div></div>`;
}
function historyContent() {
  return `<div class="detail-card"><h3>Document versions</h3>${state.history.versions.map((v) => `<div class="version-row"><div><strong>Version ${v.number}${v.number === state.doc.version ? " · Current" : ""}</strong><small>${esc(v.note)} · ${v.author ? esc(v.author.name) + " · " : ""}${fullDate(v.at)}</small></div>${canEdit() && v.number !== state.doc.version ? `<button class="secondary" data-restore="${v.number}">Restore as new version</button>` : ""}</div>`).join('<hr class="version-divider">') || "<p>Versions appear when a draft is saved.</p>"}</div><div class="detail-card"><h3>Activity trail</h3>${state.history.events.map((e) => `<div class="event-row"><time>${fullDate(e.at)}</time><span>${esc(e.kind.replaceAll("_", " "))}${e.data.actor ? " · " + esc(e.data.actor.name) : ""}${e.data.entry ? " · " + esc(e.data.entry.tool.replaceAll("_", " ")) : ""}${e.data.note ? " · " + esc(e.data.note) : ""}</span></div>`).join("")}</div>`;
}

async function loadDocuments() {
  state.documents = (await api("/api/documents")).documents;
}
async function route() {
  const sequence = ++routeSequence;
  if (!state.session?.user || location.hash.startsWith("#/join/")) { team.authScreen(); return; }
  state.stream?.close();
  state.stream = null;
  clearTimeout(refreshTimer);
  state.history = null;
  if (state.editing) {
    state.editing = false;
  }
  const [, page = "home", id, tab] = location.hash.split("/");
  state.page = page;
  try {
    if (!state.config) state.config = await api("/api/config");
    if (sequence !== routeSequence) return;
    if (page === "document" && id) {
      await loadDocuments();
      const doc = await api("/api/documents/" + encodeURIComponent(id));
      if (sequence !== routeSequence) return;
      state.doc = doc;
      state.tab = tab === "review" ? "review" : "document";
      editor();
      if (state.tab === "review") await team.loadReview();
      if (sequence !== routeSequence) return;
      watch();
    } else {
      await loadDocuments();
      if (sequence !== routeSequence) return;
      await (({ home, library, templates, about, team: team.page, inbox: handoffs.inbox })[page] || home)();
    }
    activeHash = location.hash;
    window.scrollTo(0, 0);
  } catch (e) {
    if (sequence !== routeSequence) return;
    if (e.status === 401 || e.name === "StaleSessionError") return;
    shell(
      `<div class="empty"><h3>We couldn’t open this page.</h3><p>${esc(e.message)}</p><a class="primary" href="#/home">Back to workspace</a></div>`,
    );
  }
}
function navigate(page) {
  if (state.editing && !confirm("Discard your unsaved edits?")) return;
  state.editing = false;
  location.hash = "/" + page;
}
function watch() {
  if (!["queued", "running"].includes(state.doc.status)) return;
  const id = state.doc.id;
  state.stream = new EventSource(`/api/documents/${id}/events`);
  state.stream.onmessage = () => {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => refreshDocument(id), 120);
  };
  state.stream.addEventListener("done", () => {
    state.stream?.close();
    refreshDocument(id);
    loadDocuments().catch(() => {});
  });
  state.stream.addEventListener("auth_expired", () => { clearSession(); team.authScreen(); });
  state.stream.onerror = () => {
    api("/api/auth/session").then((session) => {
      if (!session.user) { clearSession(); team.authScreen(); }
    }).catch(() => {});
  };
}
async function refreshDocument(id) {
  if (state.doc?.id !== id || state.editing || state.page !== "document")
    return;
  try {
    const doc = await api("/api/documents/" + id);
    if (state.doc?.id !== id || state.editing || state.page !== "document") return;
    state.doc = doc;
    editor();
    if (state.tab === "activity") await loadHistory();
  } catch (e) {
    toast(e.message, true);
  }
}
async function loadHistory(more = false) {
  const id = state.doc.id;
  const previous = state.history;
  const cursor = more ? previous?.next_cursor : null;
  if (more && cursor == null) return;
  const history = await api(`/api/documents/${id}/history${cursor != null ? `?after=${cursor}` : ""}`);
  if (state.doc?.id !== id || state.page !== "document") return;
  if (more && state.history !== previous) return;
  if (more) history.events = [...previous.events, ...history.events];
  state.history = history;
  if ($("#history-content")) {
    $("#history-content").innerHTML = historyContent();
    $("#history-content").insertAdjacentHTML("afterbegin", comparisonPicker(history.versions));
    if (history.next_cursor != null) {
      $("#history-content").insertAdjacentHTML("beforeend", '<button class="secondary" data-action="more-history">Load more activity</button>');
    }
  }
}

function openComposer(template = "proposal", existing = null) {
  if (!canEdit()) { toast("Your reviewer role can discuss and approve documents. An editor or owner can create drafts."); return; }
  if (state.editing) {
    toast("Save or discard your edits before starting another brief.");
    return;
  }
  const t =
    state.config.templates.find((t) => t.id === template) ||
    state.config.templates[0];
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(briefKey()) || "null");
  } catch {}
  const values = existing ||
    saved || {
      title: "",
      request: t.prompt,
      audience: "Client stakeholders",
      context: "",
      document_type: t.id,
    };
  $("#composer").innerHTML =
    `<form id="brief-form"><div class="dialog-head"><div><div class="eyebrow">A LITTLE CONTEXT GOES A LONG WAY</div><h2 id="composer-title">What should we make?</h2><p>Start with the outcome. We’ll help give it shape.</p></div><button type="button" class="icon-button" data-close="composer" aria-label="Close new document">${icon("close")}</button></div><div class="dialog-body"><div class="field"><label for="brief-title">Working title</label><input id="brief-title" name="title" placeholder="e.g. A better client onboarding experience" value="${esc(values.title)}" maxlength="180" required></div><div class="form-grid"><div class="field"><label for="brief-type">Document type</label><select id="brief-type" name="document_type">${state.config.templates.map((t) => `<option value="${t.id}" ${values.document_type === t.id ? "selected" : ""}>${t.name}</option>`).join("")}</select></div><div class="field"><label for="brief-audience">Who is it for?</label><input id="brief-audience" name="audience" value="${esc(values.audience)}" minlength="2" maxlength="200" required></div></div><div class="field"><label for="brief-request">The brief</label><textarea id="brief-request" name="request" minlength="10" maxlength="5000" required placeholder="Describe the outcome, constraints and what a good document should include…">${esc(values.request || values.brief || "")}</textarea><small>Specific context produces useful work. Include deadlines, constraints, and what needs a decision.</small></div><div class="field"><details ${values.context ? "open" : ""}><summary>Add reference notes <span class="muted">(optional)</span></summary><textarea class="context" name="context" aria-label="Reference notes" maxlength="12000" placeholder="Paste your notes, requirements, or meeting context. These will be treated as unverified reference material.">${esc(values.context)}</textarea></details></div><div class="privacy-note">${icon("shield")}<span>Creating uses <strong>${esc(state.config.provider)}</strong> with your configured model. Your brief and notes will be sent to that provider. Opening sample documents, editing and exporting use no API credits.</span></div><p id="brief-error" class="form-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="secondary" data-close="composer">Keep as a draft</button><button type="submit" class="primary" id="create-submit">Create with ${esc(state.config.provider)} ${icon("arrow")}</button></div></form>`;
  $("#composer").showModal();
  $("#brief-title").focus();
  let submissionKey = crypto.randomUUID();
  const keepBrief = () => {
    try {
      localStorage.setItem(
        briefKey(),
        JSON.stringify(Object.fromEntries(new FormData($("#brief-form")))),
      );
    } catch {
      toast(
        "Browser draft storage is unavailable. Keep this dialog open until you are ready.",
      );
    }
  };
  keepBrief();
  $("#brief-form").addEventListener("input", () => {
    submissionKey = crypto.randomUUID();
    keepBrief();
  });
  $("#brief-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#create-submit");
    button.disabled = true;
    $("#brief-error").textContent = "";
    try {
      const data = {
        ...Object.fromEntries(new FormData(event.target)),
        idempotency_key: submissionKey,
      };
      const doc = await post("/api/jobs", data);
      forgetBrief();
      $("#composer").close();
      state.documents.unshift(doc);
      navigate("document/" + doc.id);
      toast("Your brief is queued. You can follow every step here.");
    } catch (e) {
      $("#brief-error").textContent = e.message;
      button.disabled = false;
    }
  });
}
function forgetBrief() {
  try {
    localStorage.removeItem(briefKey());
  } catch {}
}
function settings() {
  $("#settings").innerHTML =
    `<div class="dialog-head"><div><div class="eyebrow">YOUR WORKSPACE</div><h2 id="settings-title">Simple, by design.</h2></div><button class="icon-button" data-close="settings" aria-label="Close settings">${icon("close")}</button></div><div class="dialog-body"><div class="settings-line"><span>Storage</span><strong>Server-side SQLite + Word files</strong></div><div class="settings-line"><span>Provider</span><strong>${esc(state.config.provider)}</strong></div><div class="settings-line"><span>Model</span><strong>${esc(state.config.model)}</strong></div><div class="settings-line"><span>Concurrent runs</span><strong>${state.config.max_concurrent_jobs}</strong></div><div class="settings-line"><span>Workspace</span><strong>${esc(state.session.workspace_name)}</strong></div><p class="settings-foot">Provider credentials are kept in the server’s environment configuration, never in this page. All active members share this workspace. Remote access requires HTTPS; this local preview is not a publicly hosted service.</p><a class="secondary" href="/docs" target="_blank" rel="noopener">Explore the API ${icon("up")}</a>${team.accountSettings()}</div>`;
  $("#settings").showModal();
}
async function saveDraft() {
  if (saving) return;
  saving = true;
  try {
    const payload = {
      title: state.doc.title,
      draft: structuredClone(state.doc.artifact.draft),
      expected_version: state.doc.version,
      note: "Edited in workspace",
    };
    document.querySelectorAll("[data-edit]").forEach((node) => {
      const path = node.dataset.edit.split(".");
      let target = payload;
      for (const part of path.slice(0, -1)) target = target[part];
      target[path.at(-1)] = node.innerText.trim();
    });
    state.doc = await api(`/api/documents/${state.doc.id}/draft`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.editing = false;
    await loadDocuments();
    editor();
    toast(
      "Version " +
        state.doc.version +
        " saved. Your previous draft is preserved.",
    );
  } finally {
    saving = false;
  }
}

document.addEventListener("click", async (event) => {
  if (event.target.closest(".skip-link")) {
    event.preventDefault();
    $("#main")?.focus();
    return;
  }
  const link = event.target.closest('a[href^="#/"]');
  if (link && state.editing) {
    event.preventDefault();
    navigate(link.getAttribute("href").slice(2));
    return;
  }
  const target = event.target.closest(
    "[data-action],[data-nav],[data-template],[data-close],[data-filter],[data-tab],[data-restore]",
  );
  if (!target) return;
  try {
    if (target.dataset.action === "compare-versions") {
      const id = state.doc.id;
      const output = $("#comparison-result");
      const from = $("#compare-from").value;
      const to = $("#compare-to").value;
      target.disabled = true;
      output.textContent = "Comparing saved drafts…";
      try {
        const result = await api(`/api/documents/${id}/compare?from_version=${from}&to_version=${to}`);
        if (state.doc?.id === id && output === $("#comparison-result")) output.innerHTML = comparisonResult(result, esc);
      } catch (error) {
        if (output === $("#comparison-result")) output.textContent = "Comparison could not be loaded. Please try again.";
        throw error;
      } finally { target.disabled = false; }
      return;
    }
    if (target.dataset.action === "more-history") {
      target.disabled = true;
      try { await loadHistory(true); } finally { target.disabled = false; }
      return;
    }
    if (target.dataset.nav) {
      navigate(target.dataset.nav);
      return;
    }
    if (target.dataset.close) {
      $("#" + target.dataset.close).close();
      return;
    }
    if (target.dataset.template) {
      let previous = null;
      try {
        previous = JSON.parse(
          localStorage.getItem(briefKey()) || "null",
        );
      } catch {}
      if (
        previous?.title &&
        !confirm("Replace the unsent brief with this template?")
      )
        return;
      forgetBrief();
      openComposer(target.dataset.template);
      return;
    }
    if (target.dataset.filter) {
      state.filter = target.dataset.filter;
      (state.page === "home" ? home : library)();
      return;
    }
    if (target.dataset.tab) {
      if (state.editing) {
        toast("Save or discard your edits before switching tabs.");
        return;
      }
      state.tab = target.dataset.tab;
      editor();
      if (state.tab === "activity") await loadHistory();
      if (state.tab === "review") await team.loadReview();
      return;
    }
    if (target.dataset.restore) {
      if (
        !confirm(
          `Restore version ${target.dataset.restore} as a new version? Your current version will be kept.`,
        )
      )
        return;
      state.doc = await post(
        `/api/documents/${state.doc.id}/versions/${target.dataset.restore}/restore`,
        { expected_version: state.doc.version },
      );
      state.history = null;
      editor();
      await loadHistory();
      toast("Earlier draft restored as version " + state.doc.version + ".");
      return;
    }
    const action = target.dataset.action;
    if (action === "new") openComposer();
    if (action === "settings") settings();
    if (action === "search") {
      if (!["home", "library"].includes(state.page)) {
        navigate("library");
        setTimeout(() => $("#library-search")?.focus(), 200);
      } else $("#library-search")?.focus();
    }
    if (action === "refresh") {
      await loadDocuments();
      (state.page === "home" ? home : library)();
      toast("Workspace is up to date.");
    }
    if (action === "clear") {
      state.query = "";
      state.filter = "all";
      (state.page === "home" ? home : library)();
    }
    if (action === "edit") {
      if (!canEdit()) return;
      state.editing = true;
      state.tab = "document";
      editor();
      $(".paper [contenteditable]")?.focus();
    }
    if (action === "discard") {
      state.editing = false;
      editor();
    }
    if (action === "save") {
      target.disabled = true;
      try {
        await saveDraft();
      } finally {
        target.disabled = false;
      }
    }
    if (action === "approve") {
      state.doc = await post(`/api/documents/${state.doc.id}/approval`, {
        expected_version: state.doc.version,
        approved: state.doc.approved_version !== state.doc.version,
      });
      editor();
      toast(
        state.doc.approved_version
          ? "You approved this version."
          : "Approval withdrawn.",
      );
      if (state.tab === "review") await team.loadReview();
    }
    if (action === "cancel") {
      if (
        confirm(
          "Cancel this run? A request already sent to the provider may still use tokens.",
        )
      ) {
        await post(`/api/documents/${state.doc.id}/cancel`);
        state.stream?.close();
        await refreshDocument(state.doc.id);
      }
    }
    if (action === "retry")
      openComposer(state.doc.document_type, {
        ...state.doc,
        request: state.doc.brief,
      });
  } catch (e) {
    toast(e.message, true);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "library-search") {
    state.query = event.target.value;
    $("#document-list").innerHTML = rows();
  }
});
document.addEventListener("paste", (event) => {
  if (event.target.isContentEditable) {
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    document.execCommand("insertText", false, text);
  }
});
document.addEventListener("keydown", (event) => {
  if (!state.session?.user) return;
  if ((event.ctrlKey || event.metaKey) && event.key === "k") {
    event.preventDefault();
    navigate("library");
    setTimeout(() => $("#library-search")?.focus(), 200);
  }
  if (
    event.key.toLowerCase() === "n" &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !event.target.closest("input,textarea,select,[contenteditable],dialog")
  ) {
    event.preventDefault();
    openComposer();
  }
  if ((event.ctrlKey || event.metaKey) && event.key === "s" && state.editing) {
    event.preventDefault();
    saveDraft().catch((e) => toast(e.message, true));
  }
});
window.addEventListener("beforeunload", (event) => {
  if (state.editing) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("hashchange", () => {
  if (state.editing && !confirm("Discard your unsaved edits?")) {
    history.replaceState(null, "", activeHash || "#/home");
    return;
  }
  route();
});
async function start() {
  try {
    state.session = await api("/api/auth/session");
    if (!state.session.user || location.hash.startsWith("#/join/")) { team.authScreen(); return; }
    state.config = await api("/api/config");
    await route();
  } catch (e) {
    if (e.status === 401 || e.name === "StaleSessionError") return;
    $("#app").innerHTML =
      `<div class="empty"><span class="brand-mark">b.</span><h3>Your workspace isn’t available yet.</h3><p>${esc(e.message)}</p><p>Start the Python server, then reload this page.</p></div>`;
  }
}
start();
