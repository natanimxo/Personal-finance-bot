/* Expense Tracker Mini App. Plain JS, no build step.
   Every request carries Telegram's signed initData; the server derives the user from it. */
(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  // In Telegram, initData comes from telegram-web-app.js. The local preview
  // (scripts/preview_app.py) passes it in the URL hash the same way Telegram does.
  const initData = (tg && tg.initData) || new URLSearchParams(location.hash.slice(1)).get("tgWebAppData") || "";
  const insideTelegram = !!(tg && tg.initData && tg.platform && tg.platform !== "unknown");
  const screen = document.getElementById("screen");
  const tabs = document.getElementById("tabs");
  const fallbackMain = document.getElementById("fallback-main");
  const toastEl = document.getElementById("toast");

  if (insideTelegram) document.documentElement.classList.add("tg");

  const state = { me: null, period: "week", route: "home", currency: "" };  // the user's own; "" until picked

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  // Same format as the bot (app/services/money.py): "USD 1,500", "USD 1,500.50", "−USD 200",
  // or just "1,500" before the user has picked a currency.
  function money(minor, { sign = false } = {}) {
    const n = Math.abs(minor) / 100;
    const cents = Math.abs(minor) % 100 !== 0;
    const text = n.toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 });
    const prefix = sign ? (minor > 0 ? "+" : minor < 0 ? "−" : "") : (minor < 0 ? "−" : "");
    return `${prefix}${state.currency ? state.currency + " " : ""}${text}`;
  }

  function haptic(kind) {
    try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(kind); } catch (_) {}
  }

  let undoAction = null;  // id of the entry a quick add just created
  let toastTimer;
  function toast(text, kind = "") {
    toastEl.replaceChildren(document.createTextNode(text));
    if (undoAction) {
      const id = undoAction;
      undoAction = null;
      toastEl.append(h("button", { class: "toast-action", onclick: async () => {
        toastEl.hidden = true;
        try { await api(`/api/transactions/${id}`, { method: "DELETE" }); toast("Undone"); go(state.route); }
        catch (err) { toast(err.message); }
      } }, "Undo"));
    }
    toastEl.className = "toast " + kind;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastEl.hidden = true), kind === "warn" ? 5000 : 2500);
  }

  function confirmDialog(text) {
    return new Promise((resolve) => {
      if (insideTelegram && tg.showConfirm) tg.showConfirm(text, resolve);
      else resolve(window.confirm(text));
    });
  }

  function localDay(isoDate) {  // "2026-11-22" -> "Sun, Nov 22, 2026"
    const [y, m, d] = isoDate.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function categoryLabel(type, key) {
    const list = (state.me && state.me.categories[type]) || [];
    const found = list.find((c) => c.key === key);
    return found ? found.label : key;
  }

  function warningText(w) {
    if (!w) return "";
    const used = `${money(w.spent_minor)} / ${money(w.limit_minor)}`;
    return w.level === "over" ? `Over budget on ${w.label}: ${used}` : `${w.percent}% of your ${w.label} budget used (${used})`;
  }

  // ---------------------------------------------------------------- API
  class ApiError extends Error {
    constructor(status, body) {
      super((body && (body.error || (body.detail && body.detail.error))) || `Request failed (${status})`);
      this.status = status;
      this.body = body;
    }
  }

  async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(path, {
      method,
      headers: { Authorization: "tma " + initData, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  }

  // ---------------------------------------------------------------- Main / Back buttons
  let mainHandler = null;
  function setMainButton(text, handler) {
    mainHandler = handler;
    if (insideTelegram) {
      tg.MainButton.offClick(onMain);
      if (!text) return tg.MainButton.hide();
      tg.MainButton.setText(text);
      tg.MainButton.onClick(onMain);
      tg.MainButton.show();
    } else {
      fallbackMain.hidden = !text;
      fallbackMain.textContent = text || "";
      document.body.classList.toggle("has-fallback", !!text);
    }
  }
  function onMain() { if (mainHandler) mainHandler(); }
  fallbackMain.addEventListener("click", onMain);

  function setMainBusy(busy) {
    if (insideTelegram) busy ? tg.MainButton.showProgress(false) : tg.MainButton.hideProgress();
    else fallbackMain.disabled = busy;
  }

  let backHandler = null;
  function setBackButton(handler) {
    backHandler = handler;
    if (!insideTelegram) return;
    handler ? tg.BackButton.show() : tg.BackButton.hide();
  }
  if (tg && tg.BackButton) tg.BackButton.onClick(() => backHandler && backHandler());

  // ---------------------------------------------------------------- routing
  function go(route, params = {}) {
    state.route = route;
    const showTabs = !["add", "edit"].includes(route);
    tabs.hidden = !showTabs;
    document.body.classList.toggle("no-tabs", !showTabs);
    tabs.querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-current", b.dataset.route === route ? "page" : "false"));
    setMainButton(null);
    setBackButton(null);
    window.scrollTo(0, 0);
    const view = { home: viewHome, transactions: viewTransactions, add: viewEntry, edit: viewEntry,
                   budgets: viewBudgets, accounts: viewAccounts, settings: viewSettings }[route];
    render(view, params);
  }
  tabs.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-route]");
    if (b) go(b.dataset.route);
  });

  async function render(view, params) {
    screen.replaceChildren(h("div", { class: "spinner", "aria-label": "Loading" }));
    try {
      const content = await view(params);
      if (content) screen.replaceChildren(content);
    } catch (err) {
      showError(err);
    }
  }

  function showError(err) {
    console.error(err);
    tabs.hidden = true;
    setMainButton(null);
    if (err instanceof ApiError && err.status === 403 && err.body && err.body.detail && err.body.detail.error === "not_subscribed") {
      const d = err.body.detail;
      const link = d.join_link;
      const name = d.channel || "the channel";
      const days = d.days_left ? ` (${d.days_left} more day${d.days_left === 1 ? "" : "s"})` : "";
      screen.replaceChildren(h("div", { class: "state" },
        h("div", { class: "big" }, "🔒"),
        h("h1", {}, d.left ? `You left ${name}` : `This period's channel: ${name}${d.days_left ? ` — ${d.days_left} days left` : ""}`),
        h("p", {}, d.left
          ? `Rejoin to keep using the tracker. It's your channel for this period${days}. Your entries are all still here.`
          : "The tracker is free. Every 30 days there's one channel everyone needs to be in, and you only need the current one."),
        link ? h("button", { class: "btn", onclick: () => (insideTelegram ? tg.openTelegramLink(link) : window.open(link)) }, `📢 Join ${name}`) : null,
        h("p", {}, h("button", { class: "btn secondary", onclick: () => boot() }, "✅ I've joined"))));
      return;
    }
    if (err instanceof ApiError && err.status === 401) {
      screen.replaceChildren(h("div", { class: "state" },
        h("div", { class: "big" }, "📱"),
        h("h1", {}, "Open this from the bot"),
        h("p", {}, insideTelegram ? "Your session expired. Close and reopen the app." : "This app works inside Telegram: open it from the bot's menu button.")));
      return;
    }
    screen.replaceChildren(h("div", { class: "state" },
      h("div", { class: "big" }, "⚠️"),
      h("h1", {}, "Something went wrong"),
      h("p", {}, err.message || "Please try again."),
      h("button", { class: "btn", onclick: () => go(state.route) }, "Try again")));
  }

  // ---------------------------------------------------------------- Home
  async function viewHome() {
    const data = await api(`/api/summary?period=${state.period}`);
    setMainButton("Add entry", () => go("add"));

    const seg = h("div", { class: "seg", role: "group", "aria-label": "Period" },
      ["week", "month"].map((p) => h("button", {
        "aria-pressed": String(state.period === p),
        onclick: () => { state.period = p; go("home"); },
      }, p === "week" ? "This week" : "This month")));

    const net = data.net_minor;
    const stats = h("div", { class: "stats" },
      h("div", { class: "stat" }, h("div", { class: "label" }, "Income"), h("div", { class: "value amount income" }, money(data.income_minor))),
      h("div", { class: "stat" }, h("div", { class: "label" }, "Expenses"), h("div", { class: "value" }, money(data.expense_minor))),
      h("div", { class: "stat wide" },
        h("div", {}, h("div", { class: "label" }, "Net"),
          data.savings_rate !== null ? h("div", { class: "note" }, `Savings rate ${Math.round(data.savings_rate)}%`) : null),
        h("div", { class: "value amount " + (net < 0 ? "neg" : "income") }, money(net, { sign: true }))));

    const maxCat = Math.max(1, ...data.by_category.map((c) => c.total_minor));
    const spending = data.by_category.length
      ? h("div", { class: "list" }, data.by_category.map((c) => h("div", { class: "bar-row" },
          h("div", { class: "bar-head" }, h("span", {}, c.label), h("span", { class: "amount" }, money(c.total_minor))),
          h("div", { class: "track" }, h("div", { class: "fill", style: `width:${(c.total_minor / maxCat) * 100}%` })))))
      : h("div", { class: "card empty" }, "No spending in this period yet.");

    const withLimits = data.budgets.filter((b) => b.limit_minor);
    const budgetList = withLimits.length
      ? h("div", { class: "list" }, withLimits.map(budgetBar))
      : h("button", { class: "card row", onclick: () => go("budgets") },
          h("span", { class: "main" }, "Set a monthly budget"), h("span", { class: "hint" }, "›"));

    const accounts = h("div", { class: "list" }, data.accounts.filter((a) => !a.archived || a.balance_minor).map((a) => h("div", { class: "row" },
      h("span", { class: "main title" }, a.label, a.is_default ? " ⭐" : ""),
      h("span", { class: "amount " + (a.balance_minor < 0 ? "neg" : "") }, money(a.balance_minor)))));

    const quickInput = h("input", { class: "input", placeholder: "Quick add: 500 food lunch", "aria-label": "Quick add",
      enterkeyhint: "done", autocomplete: "off" });
    const quickForm = h("form", { class: "quick", onsubmit: async (e) => {
      e.preventDefault();
      const text = quickInput.value.trim();
      if (!text) return;
      try {
        const res = await api("/api/quick", { method: "POST", body: { text } });
        if (res.draft) { go("add", { draft: res.draft }); return; }
        haptic(res.warning ? "warning" : "success");
        undoAction = res.entry.id;  // set before toast() so this toast gets the Undo button
        toast(res.warning ? warningText(res.warning) : `Added ${res.entry.category_label} ${money(res.entry.amount_minor)}`, res.warning ? "warn" : "");
        go("home");
      } catch (err) { haptic("error"); toast(err.message); }
    } }, quickInput, h("button", { class: "btn", type: "submit" }, "Add"));

    return h("div", {}, seg, quickForm, stats,
      h("h2", {}, "Spending by category"), spending,
      h("h2", {}, "Budgets this month"), budgetList,
      h("h2", {}, "Account balances"), accounts);
  }

  function budgetBar(b) {
    const pct = b.limit_minor ? (b.spent_minor / b.limit_minor) * 100 : 0;
    const cls = pct > 100 ? "over" : pct >= 80 ? "warn" : "";
    return h("div", { class: "bar-row" },
      h("div", { class: "bar-head" }, h("span", {}, b.label),
        h("span", { class: "hint" }, `${money(b.spent_minor)} of ${money(b.limit_minor)}`)),
      h("div", { class: "track", role: "progressbar", "aria-valuenow": Math.round(pct), "aria-valuemin": 0, "aria-valuemax": 100 },
        h("div", { class: "fill " + cls, style: `width:${Math.min(pct, 100)}%` })));
  }

  // ---------------------------------------------------------------- Transactions
  const filters = { type: "", category: "", account: "", from: "", to: "", q: "" };

  async function viewTransactions() {
    setMainButton("Add entry", () => go("add"));
    const me = state.me;
    const list = h("div");
    const sentinel = h("div", { class: "sentinel" });
    let cursor = null, loading = false, done = false, lastDay = null, dayList = null, total = 0;

    const query = () => {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) if (v) p.set(k, v);
      if (cursor) p.set("cursor", cursor);
      return p.toString();
    };

    async function loadMore() {
      if (loading || done) return;
      loading = true;
      try {
        const data = await api(`/api/transactions?${query()}`);
        for (const e of data.items) {
          const day = localDay(e.date);
          if (day !== lastDay) {
            lastDay = day;
            dayList = h("div", { class: "list" });
            list.append(h("div", { class: "day" }, day), dayList);
          }
          dayList.append(entryRow(e));
          total++;
        }
        cursor = data.next_cursor;
        done = !cursor;
        if (done && total === 0) list.append(h("div", { class: "card empty" }, anyFilter() ? "Nothing matches these filters." : "No transactions yet."));
      } catch (err) {
        done = true;
        list.append(h("div", { class: "card empty" }, err.message));
      } finally {
        loading = false;
      }
    }

    const typeSeg = h("div", { class: "seg", role: "group", "aria-label": "Type" },
      [["", "All"], ["expense", "Expenses"], ["income", "Income"], ["transfer", "Transfers"]].map(([v, label]) => h("button", {
        "aria-pressed": String(filters.type === v),
        onclick: () => { filters.type = v; if (v && filters.category && (v === "transfer" || !me.categories[v].some((c) => c.key === filters.category))) filters.category = ""; go("transactions"); },
      }, label)));

    let timer;
    const search = h("input", { class: "input wide", type: "search", placeholder: "Search notes", value: filters.q,
      "aria-label": "Search notes",
      oninput: (e) => { clearTimeout(timer); timer = setTimeout(() => { filters.q = e.target.value.trim(); go("transactions"); }, 400); } });

    const cats = filters.type === "transfer" ? [] : filters.type ? me.categories[filters.type] : [...me.categories.expense, ...me.categories.income.filter((c) => c.key !== "other")];
    const select = (name, label, options) => h("select", { class: "input", "aria-label": label,
      onchange: (e) => { filters[name] = e.target.value; go("transactions"); } },
      h("option", { value: "" }, label), options.map((o) => h("option", { value: o.key, selected: filters[name] === o.key }, o.label)));
    const date = (name, label) => h("input", { class: "input", type: "date", value: filters[name], "aria-label": label, title: label,
      onchange: (e) => { filters[name] = e.target.value; go("transactions"); } });

    const filterBox = h("div", { class: "filters" },
      search, select("category", "All categories", cats),
      select("account", "All accounts", me.accounts.map((a) => ({ key: a.account, label: a.label }))),
      date("from", "From date"), date("to", "To date"),
      anyFilter() ? h("button", { class: "btn secondary wide", onclick: () => { Object.keys(filters).forEach((k) => (filters[k] = "")); go("transactions"); } }, "Clear filters") : null);

    const root = h("div", {}, h("h1", {}, "History"), typeSeg, filterBox, list, sentinel);
    screen.replaceChildren(root);
    await loadMore();
    const io = new IntersectionObserver((items) => { if (items[0].isIntersecting) loadMore(); }, { rootMargin: "400px" });
    io.observe(sentinel);
    return null;
  }

  function anyFilter() { return Object.values(filters).some(Boolean); }

  function entryRow(e) {
    const transfer = e.type === "transfer";
    const signed = e.type === "income" ? e.amount_minor : -e.amount_minor;
    return h("button", { class: "row", onclick: () => go("edit", { entry: e }) },
      h("span", { class: "main" },
        h("div", { class: "title" }, e.category_label),
        h("div", { class: "sub" }, [transfer ? `${e.account_label} → ${e.to_account_label}` : e.account_label, e.note].filter(Boolean).join(" · "))),
      h("span", { class: "amount " + (e.type === "income" ? "income" : "") }, transfer ? money(e.amount_minor) : money(signed, { sign: true })));
  }

  // ---------------------------------------------------------------- Add / Edit
  async function viewEntry({ entry, draft } = {}) {
    const me = state.me;
    const editing = !!entry;
    const start = entry || draft || {};
    const form = {
      type: start.type || "expense",
      category: start.category || null,
      account: start.account || me.default_account || "cash",
      note: start.note || "",
      date: start.date || todayIso(),
      to: start.to_account || null,
      repeat: "",
    };
    const lockedType = editing && (entry.type === "transfer" ? "transfer" : "money");  // can't switch in or out of transfer
    setBackButton(() => go(editing ? "transactions" : "home"));

    const amount = h("input", { class: "input amount-input", inputmode: "decimal", autocomplete: "off",
      placeholder: "0.00", "aria-label": "Amount", value: start.amount_minor ? (start.amount_minor / 100).toFixed(2) : "" });
    const catBox = h("div", { class: "chips", role: "group", "aria-label": "Category" });
    const drawCats = () => {
      catField.hidden = form.type === "transfer";
      if (form.type === "transfer") return;
      catBox.replaceChildren(...me.categories[form.type].filter((c) => !c.hidden || c.key === form.category).map((c) => h("button", {
      class: "chip", "aria-pressed": String(form.category === c.key),
      onclick: () => { form.category = c.key; drawCats(); },
    }, c.label)));
    };

    const typeSeg = h("div", { class: "seg", role: "group", "aria-label": "Type" });
    const typeOptions = [["expense", "Expense"], ["income", "Income"], ["transfer", "Transfer"]].filter(([v]) =>
      !lockedType || (lockedType === "transfer" ? v === "transfer" : v !== "transfer"));
    const drawType = () => typeSeg.replaceChildren(...typeOptions.map(([v, label]) => h("button", {
      "aria-pressed": String(form.type === v),
      onclick: () => { if (form.type !== v) { form.type = v; form.category = null; drawType(); drawCats(); drawAccounts(); drawRepeat(); } },
    }, label)));

    const accBox = h("div", { class: "chips", role: "group", "aria-label": "Account" });
    const toBox = h("div", { class: "chips", role: "group", "aria-label": "To account" });
    const accLabel = h("label", {}, "Account");
    const chipsFor = (selected, pick, exclude) => me.accounts
      .filter((a) => (!a.archived || a.account === selected) && a.account !== exclude)
      .map((a) => h("button", { class: "chip", "aria-pressed": String(selected === a.account), onclick: () => pick(a.account) },
        a.label, a.is_default && form.type !== "transfer" ? " ⭐" : ""));
    const drawAccounts = () => {
      const transfer = form.type === "transfer";
      accLabel.textContent = transfer ? "From" : "Account";
      toField.hidden = !transfer;
      if (transfer && form.to === form.account) form.to = null;
      accBox.replaceChildren(...chipsFor(form.account, (k) => { form.account = k; drawAccounts(); }));
      toBox.replaceChildren(...chipsFor(form.to, (k) => { form.to = k; drawAccounts(); }, form.account));
    };

    const counter = h("div", { class: "counter" });
    const note = h("textarea", { class: "input", rows: 2, maxlength: 200, placeholder: "Optional", "aria-label": "Note",
      oninput: () => (counter.textContent = `${note.value.length} / 200`) });
    note.value = form.note;
    counter.textContent = `${note.value.length} / 200`;

    const dateInput = h("input", { class: "input", type: "date", value: form.date, max: todayIso(), "aria-label": "Date",
      onchange: (e) => (form.date = e.target.value || todayIso()) });

    const repeatBox = h("div", { class: "seg", role: "group", "aria-label": "Repeat" });
    const drawRepeat = () => {
      repeatField.hidden = editing || form.type === "transfer";
      repeatBox.replaceChildren(...[["", "Once"], ["weekly", "Weekly"], ["monthly", "Monthly"]].map(([v, label]) => h("button", {
        "aria-pressed": String(form.repeat === v), onclick: () => { form.repeat = v; drawRepeat(); },
      }, label)));
    };
    const repeatField = h("div", { class: "field" }, h("label", {}, "Repeat"), repeatBox);
    const catField = h("div", { class: "field" }, h("label", {}, "Category"), catBox);
    const toField = h("div", { class: "field" }, h("label", {}, "To"), toBox);
    drawType(); drawCats(); drawAccounts(); drawRepeat();

    async function save() {
      const transfer = form.type === "transfer";
      if (!amount.value.trim()) { toast("Type an amount first."); amount.focus(); return; }
      if (transfer && !form.to) { toast("Pick the account the money goes to."); return; }
      if (!transfer && !form.category) { toast("Pick a category."); return; }
      const body = transfer
        ? { amount: amount.value.trim(), account: form.account, to_account: form.to, note: note.value, date: form.date }
        : { amount: amount.value.trim(), type: form.type, category: form.category, account: form.account,
            note: note.value, date: form.date, ...(!editing && form.repeat ? { repeat: form.repeat } : {}) };
      setMainBusy(true);
      try {
        const res = editing
          ? await api(`/api/transactions/${entry.id}`, { method: "PATCH", body })
          : transfer
            ? await api("/api/transfers", { method: "POST", body: { amount: body.amount, from_account: form.account,
                                                                      to_account: form.to, note: body.note, date: body.date } })
            : await api("/api/transactions", { method: "POST", body });
        haptic(res.warning ? "warning" : "success");
        if (res.warning) toast(warningText(res.warning), "warn");
        else toast(editing ? "Saved" : res.recurring ? `Added, repeats ${res.recurring.frequency === "weekly" ? "every week" : "every month"}` : "Added");
        go(editing ? "transactions" : "home");
      } catch (err) {
        haptic("error");
        toast(err.message);
      } finally {
        setMainBusy(false);
      }
    }
    setMainButton(editing ? "Save changes" : "Save", save);

    async function remove() {
      if (!(await confirmDialog("Delete this entry? This can't be undone."))) return;
      try {
        await api(`/api/transactions/${entry.id}`, { method: "DELETE" });
        haptic("success");
        toast("Deleted");
        go("transactions");
      } catch (err) { toast(err.message); }
    }

    const view = h("div", {},
      h("h1", {}, editing ? "Edit entry" : "New entry"),
      typeSeg,
      h("div", { class: "field" }, h("label", {}, "Amount", state.currency ? ` (${state.currency})` : ""), amount),
      catField,
      h("div", { class: "field" }, accLabel, accBox),
      toField,
      h("div", { class: "field" }, h("label", {}, "Date"), dateInput),
      repeatField,
      h("div", { class: "field" }, h("label", {}, "Note"), note, counter),
      editing ? h("p", { class: "hint" }, `Logged ${new Date(entry.created_at).toLocaleString()}`) : null,
      editing ? h("button", { class: "btn danger", onclick: remove }, "Delete entry") : null);
    if (!editing && !draft) setTimeout(() => amount.focus(), 50);
    if (draft) toast("Pick a category to finish.");
    return view;
  }

  // ---------------------------------------------------------------- Budgets
  async function viewBudgets() {
    const data = await api("/api/budgets");
    const list = h("div", { class: "list" });
    let open = null;

    function draw() {
      list.replaceChildren(...data.budgets.map((b) => {
        const head = h("button", { class: "row", onclick: () => { open = open === b.category ? null : b.category; draw(); } },
          h("span", { class: "main" },
            h("div", { class: "title" }, b.label),
            h("div", { class: "sub" }, b.limit_minor ? `${money(b.spent_minor)} of ${money(b.limit_minor)} this month` : `No limit · ${money(b.spent_minor)} spent this month`)),
          h("span", { class: "hint" }, open === b.category ? "▴" : "▾"));
        const parts = [head];
        if (b.limit_minor) parts.push(h("div", { style: "padding:0 16px 12px" }, budgetBar(b).lastChild));
        if (open === b.category) {
          const input = h("input", { class: "input", inputmode: "decimal", placeholder: "Monthly limit",
            value: b.limit_minor ? (b.limit_minor / 100).toFixed(2) : "", "aria-label": `Monthly limit for ${b.label}` });
          const save = async (limit) => {
            try {
              const res = await api("/api/budgets", { method: "PUT", body: { category: b.category, limit } });
              data.budgets = res.budgets;
              open = null;
              haptic("success");
              toast(limit ? "Budget saved" : "Budget removed");
              draw();
            } catch (err) { toast(err.message); }
          };
          parts.push(h("div", { class: "inline-edit" }, input,
            h("button", { class: "btn", onclick: () => save(input.value.trim() || null) }, "Save"),
            b.limit_minor ? h("button", { class: "btn secondary", onclick: () => save(null) }, "Remove") : null));
          setTimeout(() => input.focus(), 30);
        }
        return h("div", {}, ...parts);
      }));
    }
    draw();
    return h("div", {}, h("h1", {}, "Budgets"),
      h("p", { class: "hint" }, "Monthly limits per category. You're warned at 80% and when you go over."), list);
  }

  // ---------------------------------------------------------------- Accounts
  async function viewAccounts() {
    let data = await api("/api/accounts");
    const root = h("div");
    let editing = null;  // key of the account being renamed

    async function change(request, done) {
      try {
        data = await request();
        state.me.accounts = data.accounts;
        state.me.default_account = data.default_account;
        editing = null;
        haptic("success");
        if (done) toast(done);
        draw();
      } catch (err) { haptic("error"); toast(err.message); }
    }

    function accountRow(a) {
      if (editing === a.account) {
        const input = h("input", { class: "input", value: a.label, maxlength: 30, "aria-label": "Account name" });
        setTimeout(() => input.focus(), 30);
        return h("div", { class: "row" }, h("div", { class: "inline-edit", style: "padding:0;flex:1" }, input,
          h("button", { class: "btn", onclick: () => change(() => api(`/api/accounts/${a.account}`, { method: "PATCH", body: { name: input.value } }), "Renamed") }, "Save"),
          h("button", { class: "btn secondary", onclick: () => { editing = null; draw(); } }, "✕")));
      }
      const actions = a.archived
        ? [h("button", { class: "btn secondary", onclick: () => change(() => api(`/api/accounts/${a.account}`, { method: "PATCH", body: { archived: false } }), "Restored") }, "Restore")]
        : [
            a.is_default ? null : h("button", { class: "chip", title: "Make default", "aria-label": `Make ${a.label} the default`,
              onclick: () => change(() => api("/api/accounts", { method: "PUT", body: { default_account: a.account } }), "Default set") }, "⭐"),
            h("button", { class: "chip", "aria-label": `Rename ${a.label}`, onclick: () => { editing = a.account; draw(); } }, "✏️"),
            h("button", { class: "chip", "aria-label": `Archive ${a.label}`, onclick: async () => {
              if (await confirmDialog(`Archive ${a.label}? It disappears from pickers; its history and balance stay.`))
                change(() => api(`/api/accounts/${a.account}`, { method: "PATCH", body: { archived: true } }), "Archived");
            } }, "🗄️"),
          ];
      return h("div", { class: "row" },
        h("span", { class: "main" },
          h("div", { class: "title" }, a.label, a.is_default ? " ⭐" : ""),
          h("div", { class: "sub amount " + (a.balance_minor < 0 ? "neg" : "") }, money(a.balance_minor))),
        ...actions);
    }

    function draw() {
      const active = data.accounts.filter((a) => !a.archived);
      const archived = data.accounts.filter((a) => a.archived);
      const newName = h("input", { class: "input", placeholder: "New account, e.g. Savings", maxlength: 30, "aria-label": "New account name" });
      root.replaceChildren(
        h("h1", {}, "Accounts"),
        h("p", { class: "hint" }, "Balance = income minus expenses, plus transfers in, minus transfers out. ⭐ is where new entries go."),
        h("div", { class: "list" }, active.map(accountRow)),
        h("form", { class: "quick", onsubmit: (e) => { e.preventDefault(); if (newName.value.trim()) change(() => api("/api/accounts", { method: "POST", body: { name: newName.value } }), "Account added"); } },
          newName, h("button", { class: "btn", type: "submit" }, "Add")),
        archived.length ? h("h2", {}, "Archived") : null,
        archived.length ? h("div", { class: "list" }, archived.map(accountRow)) : null);
    }
    draw();
    return root;
  }

  // ---------------------------------------------------------------- Settings
  // Every IANA zone the phone knows, for the timezone picker (older webviews: a short list).
  function allZones(current) {
    let zones = [];
    try { zones = Intl.supportedValuesOf("timeZone"); } catch (_) { zones = []; }
    if (!zones.length) zones = ["UTC", "Europe/London", "Europe/Berlin", "Africa/Lagos", "Africa/Nairobi", "Asia/Dubai",
      "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney", "America/New_York", "America/Chicago",
      "America/Los_Angeles", "America/Sao_Paulo"];
    if (!zones.includes("UTC")) zones = ["UTC", ...zones];
    return current && !zones.includes(current) ? [current, ...zones] : zones;
  }

  function phoneZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (_) { return ""; }
  }

  async function viewSettings() {
    const s = state.me.settings;
    const recurringList = h("div", { class: "list" });
    const loadRecurring = async () => {
      const { recurring } = await api("/api/recurring");
      recurringList.replaceChildren(...(recurring.length ? recurring.map((r) => h("div", { class: "row" },
        h("span", { class: "main" },
          h("div", { class: "title" }, `${r.category_label} · ${money(r.type === "income" ? r.amount_minor : -r.amount_minor, { sign: true })}`),
          h("div", { class: "sub" }, [r.frequency === "weekly" ? "Every week" : "Every month", `next ${localDay(r.next_date)}`, r.note].filter(Boolean).join(" · "))),
        h("button", { class: "btn secondary", "aria-label": "Stop repeating", onclick: async () => {
          if (!(await confirmDialog("Stop repeating this? Entries already logged stay."))) return;
          try { await api(`/api/recurring/${r.id}`, { method: "DELETE" }); toast("Stopped"); loadRecurring(); }
          catch (err) { toast(err.message); }
        } }, "Stop"))) : [h("div", { class: "empty" }, "Nothing repeats yet. Pick Weekly or Monthly when you add an entry.")]));
    };
    loadRecurring().catch((err) => recurringList.replaceChildren(h("div", { class: "empty" }, err.message)));

    // Categories: add, rename, hide / show, per type. Hidden ones keep their past entries in summaries.
    const categoryBox = h("div");
    let catType = "expense", renaming = null;
    const saveCats = async (request, done) => {
      try {
        const res = await request();
        state.me.categories = res.categories;
        renaming = null;
        haptic("success");
        toast(done);
        drawCategories();
      } catch (err) { haptic("error"); toast(err.message); }
    };
    function drawCategories() {
      const list = state.me.categories[catType];
      const rows = list.map((c) => {
        if (renaming === c.key) {
          const input = h("input", { class: "input", value: c.label, maxlength: 30, "aria-label": "Category name" });
          setTimeout(() => input.focus(), 30);
          return h("div", { class: "row" }, h("div", { class: "inline-edit", style: "padding:0;flex:1" }, input,
            h("button", { class: "btn", onclick: () => saveCats(() => api(`/api/categories/${catType}/${c.key}`, { method: "PATCH", body: { name: input.value } }), "Renamed") }, "Save"),
            h("button", { class: "btn secondary", onclick: () => { renaming = null; drawCategories(); } }, "✕")));
        }
        return h("div", { class: "row" },
          h("span", { class: "main title" + (c.hidden ? " hint" : "") }, c.label, c.hidden ? " (hidden)" : ""),
          c.hidden ? null : h("button", { class: "chip", "aria-label": `Rename ${c.label}`, onclick: () => { renaming = c.key; drawCategories(); } }, "✏️"),
          h("button", { class: "chip", "aria-label": c.hidden ? `Show ${c.label}` : `Hide ${c.label}`,
            onclick: () => saveCats(() => api(`/api/categories/${catType}/${c.key}`, { method: "PATCH", body: { hidden: !c.hidden } }), c.hidden ? "Visible again" : "Hidden") },
            c.hidden ? "👁️" : "🙈"));
      });
      const newName = h("input", { class: "input", placeholder: catType === "expense" ? "New category, e.g. 🏠 Rent" : "New category, e.g. 🏦 Interest", maxlength: 30, "aria-label": "New category name" });
      categoryBox.replaceChildren(
        h("div", { class: "seg", role: "group", "aria-label": "Category type", style: "margin-bottom:8px" },
          [["expense", "Expenses"], ["income", "Income"]].map(([v, label]) => h("button", {
            "aria-pressed": String(catType === v), onclick: () => { catType = v; renaming = null; drawCategories(); } }, label))),
        h("div", { class: "list" }, rows),
        h("form", { class: "quick", onsubmit: (e) => { e.preventDefault(); if (newName.value.trim()) saveCats(() => api("/api/categories", { method: "POST", body: { type: catType, name: newName.value } }), "Category added"); } },
          newName, h("button", { class: "btn", type: "submit" }, "Add")));
    }
    drawCategories();
    const common = state.me.currencies || [];
    const options = !s.currency ? ["", ...common] : common.includes(s.currency) ? common : [s.currency, ...common];
    const currency = h("select", { class: "input", "aria-label": "Currency", onchange: (e) => e.target.value && update({ currency: e.target.value }) },
      options.map((c) => h("option", { value: c, selected: c === (s.currency || "") }, c || "Pick…")));
    const zone = h("select", { class: "input", "aria-label": "Timezone", onchange: (e) => update({ timezone: e.target.value }) },
      allZones(s.timezone).map((z) => h("option", { value: z, selected: z === s.timezone }, z.replace(/_/g, " "))));
    const recap = h("input", { type: "checkbox", checked: s.recap_enabled, onchange: (e) => update({ recap_enabled: e.target.checked }) });
    const monthly = h("input", { type: "checkbox", checked: s.monthly_recap_enabled, onchange: (e) => update({ monthly_recap_enabled: e.target.checked }) });

    async function update(change) {
      try {
        const res = await api("/api/settings", { method: "PUT", body: change });
        state.me.settings = res.settings;
        state.currency = res.settings.currency || "";
        haptic("success");
        toast("Saved");
      } catch (err) { toast(err.message); go("settings"); }
    }

    return h("div", {}, h("h1", {}, "Settings"),
      h("div", { class: "list" },
        h("label", { class: "row" }, h("span", { class: "main" }, "Currency"), h("span", { style: "width:120px" }, currency)),
        h("label", { class: "row" }, h("span", { class: "main" }, h("div", {}, "Timezone"),
          h("div", { class: "sub" }, "When your week and month start, and when recaps arrive")),
          h("span", { style: "width:170px" }, zone)),
        h("label", { class: "row" }, h("span", { class: "main" }, h("div", {}, "Weekly recap"),
          h("div", { class: "sub" }, "Every Monday at 08:00 your time, compared with the week before")),
          h("span", { class: "switch" }, recap, h("span", {}))),
        h("label", { class: "row" }, h("span", { class: "main" }, h("div", {}, "Monthly recap"),
          h("div", { class: "sub" }, "On the 1st at 08:00, for the month that just ended")),
          h("span", { class: "switch" }, monthly, h("span", {})))),
      h("h2", {}, "Categories"),
      categoryBox,
      h("h2", {}, "Recurring"),
      recurringList,
      h("h2", {}, "Data"),
      h("div", { class: "list" }, h("div", { class: "row" }, h("span", { class: "main" }, h("div", {}, "Export CSV"),
        h("div", { class: "sub" }, "All your entries, sent to your Telegram chat")),
        h("button", { class: "btn secondary", onclick: async (e) => {
          e.target.disabled = true;
          try { await api("/api/export", { method: "POST" }); haptic("success"); toast("Sent to your Telegram chat"); }
          catch (err) { toast(err.message); }
          finally { e.target.disabled = false; }
        } }, "📤 Export"))),
      h("p", { class: "hint center", style: "margin-top:24px" }, `Signed in as ${state.me.user.first_name || "you"}`));
  }

  // ---------------------------------------------------------------- start
  async function boot() {
    if (tg) { tg.ready(); tg.expand(); }
    screen.replaceChildren(h("div", { class: "spinner" }));
    try {
      state.me = await api("/api/me");
      // First visit from the app: take the phone's own timezone (changeable in Settings).
      if (!state.me.settings.timezone && phoneZone()) {
        try { state.me.settings = (await api("/api/settings", { method: "PUT", body: { timezone: phoneZone() } })).settings; }
        catch (_) { /* an unknown zone: the user picks one in Settings */ }
      }
      state.currency = state.me.settings.currency || "";
      if (!state.me.settings.currency) {
        go("settings");
        toast("Pick your currency to get started");
        return;
      }
      go("home");
    } catch (err) {
      showError(err);
    }
  }
  boot();
})();
