const paths = {
  plus: "M12 5v14M5 12h14",
  chat: "M21 11.5a8.3 8.3 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.3 8.3 0 0 1-3.8-.9L3 21l1.9-5.7A8.3 8.3 0 0 1 4 11.5 8.5 8.5 0 0 1 8.7 3.9a8.3 8.3 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z",
  agents:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.9M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 3H20v19H6.5A2.5 2.5 0 0 1 4 19.5v-14A2.5 2.5 0 0 1 6.5 3ZM8 7h8M8 11h5",
  settings:
    "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8ZM9 3l-.6 2.4-2.1 1.2L4 6l-2 3 1.7 1.8v2.4L2 15l2 3 2.3-.6 2.1 1.2L9 21h6l.6-2.4 2.1-1.2 2.3.6 2-3-1.7-1.8v-2.4L22 9l-2-3-2.3.6-2.1-1.2L15 3H9Z",
  search: "m21 21-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0Z",
  lock: "M5 11h14v10H5V11Zm3 0V7a4 4 0 0 1 8 0v4",
  chevron: "m7 10 5 5 5-5",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  menu: "M4 6h16M4 12h16M4 18h16",
  arrow: "M12 19V5m-6 6 6-6 6 6",
  arrowRight: "M5 12h14m-6-6 6 6-6 6",
  copy: "M9 9h12v12H9V9ZM5 15H3V3h12v2",
  refresh:
    "M3 10a9 9 0 0 1 15-6l3 3M21 3v4h-4M21 14A9 9 0 0 1 6 20l-3-3M3 21v-4h4",
  edit: "m16 3 5 5-12 12H4v-5L16 3ZM14 5l5 5",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  x: "m6 6 12 12M6 18 18 6",
  sparkles:
    "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  check: "m5 12 4 4L19 6",
  stop: "M6 6h12v12H6Z",
  clock: "M12 7v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
};
const icon = (name) =>
  `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.chat}"/></svg>`;
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  view: "chat",
  agents: [],
  conversations: [],
  settings: {},
  runs: [],
  agentId: null,
  cid: null,
  messages: [],
  controller: null,
  diaryData: [],
  diaryId: null,
  diaryAgent: "",
  draftText: "",
  diaryPeekOpen: window.matchMedia("(min-width: 1180px)").matches,
  editingAgent: null,
  clearKey: false,
};
function agentColor(agent) {
  const color = agent?.color || "#71806a";
  return color.toLowerCase() === "#7165d6" ? "#71806a" : color;
}
const avatar = (agent, extra = "") => {
  const isDefault = !agent || agent.name === "默认助手";
  return `<span class="avatar ${isDefault ? "avatar-mascot" : ""} ${extra}" style="--avatar-color:${esc(agentColor(agent))}">${isDefault ? '<img src="/assets/art/deer-companion.png" alt="" width="1280" height="1280">' : esc(agent.name.slice(0, 1))}</span>`;
};
const activeAgent = () => state.agents.find((a) => a.id === state.agentId);
const main = $("#main");
let toastTimer, diaryTimer, messageTimer, searchTimer;
const wideChat = window.matchMedia("(min-width: 1180px)");
wideChat.addEventListener("change", () => {
  document.body.classList.toggle("diary-open", state.view === "chat" && wideChat.matches && state.diaryPeekOpen);
  syncDiaryToggle();
});

function hydrate(root = document) {
  $$("[data-icon]", root).forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
    el.removeAttribute("data-icon");
  });
}
function toast(text) {
  const box = $("#toast");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 4400);
}
function closeSidebar() {
  document.body.classList.remove("sidebar-open", "diary-open");
  syncDiaryToggle();
}
function syncDiaryToggle() {
  const button = $(".diary-peek-toggle");
  if (button) {
    const open = document.body.classList.contains("diary-open");
    button.setAttribute("aria-expanded", String(open));
    button.setAttribute("aria-label", open ? "收起今日手记" : "查看今日手记");
    button.title = open ? "收起今日手记" : "查看今日手记";
  }
}
function closeMenus() {
  $$(".menu", main).forEach((menu) => (menu.hidden = true));
}
async function api(path, options = {}) {
  const response = await fetch("/api" + path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response
    .json()
    .catch(() => ({ detail: "服务暂时没有响应" }));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((x) => x.msg).join("；")
      : data.detail;
    throw new Error(detail || "操作未完成，请重试");
  }
  return data;
}
function today() {
  return new Date(Date.now() + (state.settings.offset_minutes ?? 480) * 60000)
    .toISOString()
    .slice(0, 10);
}
async function bootstrap() {
  const data = await api("/bootstrap");
  Object.assign(state, {
    agents: data.agents,
    conversations: data.conversations,
    settings: data.settings,
    runs: data.diary_runs,
  });
  if (!activeAgent()) state.agentId = state.agents[0]?.id;
  renderSidebar();
}
function renderSidebar() {
  $$("button[data-view], a[data-view]").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === state.view),
  );
  $("#connection-dot").classList.toggle(
    "ready",
    Boolean(state.settings.configured),
  );
  $("#connection-dot").title = state.settings.configured
    ? "模型已配置"
    : "尚未配置模型";
  $("#diary-dot").hidden = !state.runs.some((r) =>
    ["scheduled", "queued", "running"].includes(r.status),
  );
  const query = $("#search-input").value.trim().toLowerCase();
  const rows =
    query && state.searchTerm === query
      ? state.searchResults || []
      : state.conversations.filter(
          (c) => !query || c.title.toLowerCase().includes(query),
        );
  $("#history-list").innerHTML = rows.length
    ? rows
        .map(
          (c) =>
            `<button class="history-item ${state.cid === c.id ? "active" : ""}" data-action="open-chat" data-id="${c.id}" title="${esc(c.title)}">${icon("chat")}<span class="history-text">${esc(c.title)}</span></button>`,
        )
        .join("")
    : '<div class="history-empty">' +
      (query ? "没有找到这段对话" : "从一段新的交谈开始。") +
      "</div>";
}
function header(title, right = "") {
  return `<header class="topbar"><div class="topbar-left"><button class="icon-button sidebar-toggle" data-action="sidebar" aria-label="打开导航">${icon("menu")}</button><span class="topbar-title">${esc(title)}</span></div><div class="topbar-right">${right}</div></header>`;
}
function route(view) {
  if (state.controller) {
    toast("可以先停止生成，再切换页面");
    return;
  }
  clearTimeout(diaryTimer);
  clearTimeout(messageTimer);
  state.view = view;
  location.hash = view;
  closeSidebar();
  renderSidebar();
  if (view === "agents") renderAgents();
  else if (view === "diary") renderDiary();
  else if (view === "settings") renderSettings();
  else renderChat();
}
function agentMenu() {
  return `<div class="menu left" id="agent-menu" hidden>${state.agents.map((a) => `<button data-action="select-agent" data-id="${a.id}">${avatar(a)}<span>${esc(a.name)}</span></button>`).join("")}</div>`;
}
function renderChat() {
  const agent = activeAgent();
  document.body.classList.toggle("diary-open", state.diaryPeekOpen && window.matchMedia("(min-width: 1180px)").matches);
  main.dataset.view = "chat";
  main.innerHTML = `<div class="chat-workspace"><section class="conversation-pane">
    <header class="topbar">
      <div class="topbar-left">
        <button class="icon-button sidebar-toggle" data-action="sidebar" aria-label="打开导航">${icon("menu")}</button>
        <div class="popover-wrap">
          <button class="agent-switch" data-action="agent-menu" aria-label="选择智能体">
            ${avatar(agent)}<span class="switch-copy"><strong>${esc(agent?.name || "选择智能体")}</strong><small>${esc(agent?.tagline || "在这里，慢慢聊。")}</small></span>${icon("chevron")}
          </button>${agentMenu()}
        </div>
      </div>
      <div class="topbar-right"><button class="icon-button" data-action="edit-agent" data-id="${esc(agent?.id || "")}" aria-label="编辑角色设定" title="编辑角色设定">${icon("edit")}</button><button class="icon-button diary-peek-toggle" data-action="toggle-diary-peek" aria-label="查看今日手记" aria-expanded="false" aria-controls="diary-peek">${icon("book")}</button>
        <button class="model-chip" data-view="settings" title="配置模型">
          <span class="model-dot ${state.settings.configured ? "ready" : ""}"></span>${esc(state.settings.model || "连接模型")}
        </button>
        <div class="popover-wrap">
          <button class="icon-button" data-action="chat-menu" aria-label="对话选项">${icon("more")}</button>
          <div class="menu" id="chat-menu" hidden>
            <button data-action="rename-chat">${icon("edit")}重命名</button>
            <button data-action="export-chat">${icon("download")}导出对话</button>
            <button data-action="delete-chat" class="danger">${icon("trash")}移除对话</button>
          </div>
        </div>
      </div>
    </header>
    <section class="chat-scroll" id="chat-scroll" aria-label="聊天记录">
      <div class="chat-column" id="chat-column"></div>
    </section>
    <footer class="composer-area">
      <form class="composer" id="composer-form">
        <textarea id="composer-input" rows="1" maxlength="16000" aria-label="发送消息" placeholder="和${esc(agent?.name || "智能体")}说点什么…"></textarea>
        <div class="composer-bottom">
          <button type="button" class="composer-diary" data-view="diary">
            ${icon("book")}<span>${state.settings.auto_diary ? "今天的手记" : "查看日记"}</span>
          </button>
          <div class="composer-controls">
            <span class="composer-hint">${state.controller ? "正在生成…" : "Enter 发送"}</span>
            <button class="send-button" id="send-button" type="submit" aria-label="${state.controller ? "停止生成" : "发送消息"}">${icon(state.controller ? "stop" : "arrow")}</button>
          </div>
        </div>
      </form>
      <div class="composer-note">Shift + Enter 换行<span>·</span>聊天记录保存在本地</div>
    </footer></section>
      <button class="diary-scrim" data-action="toggle-diary-peek" aria-label="关闭今日手记"></button>
      <aside class="diary-peek" id="diary-peek" aria-label="今日 AI 日记">
        <div class="peek-loading"><span class="loading-spinner"></span>正在翻开手记…</div>
      </aside></div>`;
  $("#composer-input").value = state.draftText;
  $("#composer-input").addEventListener("input", (event) => {
    state.draftText = event.target.value;
    event.target.style.height = "auto";
    event.target.style.height = Math.min(event.target.scrollHeight, 180) + "px";
    updateSend();
  });
  $("#composer-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!state.controller)
        sendMessage().catch((error) => toast(error.message));
    }
  });
  renderMessages();
  syncDiaryToggle();
  updateSend();
  clearTimeout(diaryTimer);
  refreshDiaryPeek();
}

async function refreshDiaryPeek() {
  const aid = state.agentId;
  const container = $("#diary-peek");
  if (!container || !aid || state.view !== "chat") return;
  const dateText = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
  }).format(new Date(today() + "T12:00:00"));
  try {
    const data = await api("/diaries?agent_id=" + encodeURIComponent(aid));
    if (state.view !== "chat" || state.agentId !== aid || !$("#diary-peek"))
      return;
    const entry = data.entries.find((d) => d.day === today());
    const job = data.runs.find((r) => r.agent_id === aid && r.day === today());
    const running = job && ["queued", "running"].includes(job.status);
    const scheduled = job?.status === "scheduled";
    $("#diary-peek").innerHTML = `
      <header class="peek-header"><h2>${icon("book")}我们的日记</h2><button class="peek-date" data-view="diary">${esc(dateText)}${icon("chevron")}</button><button class="icon-button peek-close" data-action="toggle-diary-peek" aria-label="关闭今日手记">${icon("x")}</button></header>
      <div class="peek-content">
        ${
          entry
            ? `
          <article class="peek-page">
            <div class="peek-page-heading"><span class="eyebrow">今天，值得记住的几句话</span><h3>${esc(entry.title)}</h3></div>
            <div class="prose peek-prose">${entry.html}</div>
            <div class="peek-signature">— ${esc(entry.agent_name)}</div>
          </article>
          <div class="peek-entry-info">${icon("chat")}来自 ${entry.source_count} 条对话<span>${scheduled ? "稍后合并更新" : running ? "正在更新…" : "已整理"}</span></div>
          <button class="button peek-open" data-action="open-diary" data-id="${entry.id}">翻开完整日记${icon("arrowRight")}</button>
        `
            : `
          <div class="peek-page peek-empty">
            <span class="eyebrow">${esc(dateText)} · 今日手记</span>
            <h3>还没落笔</h3>
            <p>${state.settings.auto_diary ? `聊完一阵以后，值得记住的话<br>会留在这一页。` : "开启自动日记后，<br>今天的聊天会整理在这里。"}</p>
            <span class="peek-paper-mark" aria-hidden="true">${icon("edit")}</span>
          </div>
          <div class="peek-empty-status">${running ? '<span class="loading-spinner"></span>正在记下今天的回忆…' : scheduled ? icon("clock") + "等这段聊天告一段落再记" : job?.status === "failed" ? esc(job.error) : state.settings.auto_diary ? icon("check") + "自动日记已开启" : icon("book") + "自动日记已关闭"}</div>
          <button class="button peek-open" data-action="focus-composer">回去聊聊${icon("arrowRight")}</button>
        `
        }
        <div class="diary-keepsakes" aria-hidden="true">
          <figure class="room-polaroid"><img src="/assets/art/study-room.png" alt="" width="1536" height="1024"><figcaption>收集一点日常的光</figcaption></figure>
          <div class="companion-sticker"><span>慢慢来，<br>我在听。</span><img src="/assets/art/deer-companion.png" alt="" width="1280" height="1280"></div>
        </div>
      </div>
      <footer class="peek-footer">${icon("lock")}只记录实际聊过的事</footer>`;
    if (running || scheduled) {
      clearTimeout(diaryTimer);
      diaryTimer = setTimeout(() => {
        if (state.view === "chat") refreshDiaryPeek();
      }, scheduled ? 30000 : 3000);
    }
  } catch (error) {
    if (state.view === "chat" && state.agentId === aid && $("#diary-peek")) {
      $("#diary-peek").innerHTML =
        `<div class="peek-loading"><p>手记暂时没能打开</p><button class="button" data-view="diary">去日记页查看</button></div>`;
    }
  }
}

function updateSend() {
  const button = $("#send-button");
  if (button)
    button.disabled = !state.controller && !$("#composer-input").value.trim();
}
function renderMessages() {
  const root = $("#chat-column");
  if (!root) return;
  const agent = activeAgent();
  root.classList.toggle("has-messages", Boolean(state.messages.length));
  if (!state.messages.length) {
    const date = new Intl.DateTimeFormat("zh-CN", {
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(new Date(today() + "T12:00:00"));
    root.innerHTML = `
      <div class="chat-empty">
        <div class="room-welcome">
          <time class="chat-date" datetime="${today()}">${esc(date)}</time>
          <div class="welcome-note">
            ${avatar(agent)}<div><h1>${esc(agent?.greeting || "这会儿，想聊点什么？")}</h1><p>${esc(agent?.tagline || "随便聊聊也行。")}</p></div>
          </div>
        </div>
        <div class="welcome-sheet">
          <div class="welcome-sheet-heading"><span class="eyebrow">新的一页</span><h2>不用想好开场白。</h2><p>刚发生的小事，没想明白的念头，都可以。</p></div>
        </div>
      </div>`;
    $("#chat-scroll").style.display = "flex";
    root.style.width = "100%";
    root.style.height = "100%";
    return;
  }
  $("#chat-scroll").style.display = "block";
  root.style.height = "auto";
  const lastUser = [...state.messages].reverse().find((m) => m.role === "user");
  root.innerHTML = state.messages
    .map((m, index) => {
      if (m.role === "user")
        return `<article class="message user" id="message-${esc(m.id)}"><div><div class="user-text">${esc(m.content)}</div>${m.error ? `<div class="message-status">${esc(m.error)}${lastUser?.id === m.id && m.status === "failed" ? `<button data-action="retry" data-id="${m.id}">重试</button>` : ""}</div>` : ""}</div></article>`;
      const last = index === state.messages.length - 1;
      return `<article class="message assistant" id="message-${esc(m.id)}">${avatar(agent)}<div class="message-body"><div class="message-author">${esc(agent?.name || "智能体")}</div><div class="prose ${m.streaming ? "stream-text" : ""}">${m.streaming ? (m.content ? esc(m.content) : '<div class="typing"><i></i><i></i><i></i></div>') : m.html || esc(m.content)}</div>${!m.streaming ? `<div class="message-actions"><button data-action="copy-message" data-id="${m.id}" aria-label="复制回复" title="复制">${icon("copy")}</button>${last && m.reply_to ? `<button data-action="regenerate" data-id="${m.reply_to}" aria-label="重新生成回复" title="重新生成">${icon("refresh")}</button>` : ""}</div>` : ""}</div></article>`;
    })
    .join("");
  $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight;
}
async function openConversation(cid) {
  if (state.controller) {
    toast("请先停止当前生成");
    return;
  }
  const data = await api("/conversations/" + cid);
  state.cid = cid;
  state.agentId = data.conversation.agent_id;
  state.messages = data.messages;
  state.draftText = "";
  state.view = "chat";
  location.hash = "chat";
  const url = new URL(location);
  url.searchParams.set("letter", cid);
  history.replaceState(null, "", url);
  closeSidebar();
  renderSidebar();
  renderChat();
  if (data.messages.some((m) => ["pending", "processing"].includes(m.status))) {
    clearTimeout(messageTimer);
    messageTimer = setTimeout(
      () => openConversation(cid).catch((e) => toast(e.message)),
      2000,
    );
  }
}
function newChat(aid = state.agentId) {
  if (state.controller) {
    toast("请先停止生成");
    return;
  }
  state.agentId = aid;
  state.cid = null;
  state.messages = [];
  state.draftText = "";
  const url = new URL(location);
  url.searchParams.delete("letter");
  history.replaceState(null, "", url);
  route("chat");
}
async function sendMessage(text) {
  const content = (text ?? $("#composer-input")?.value ?? "").trim();
  if (!content || state.controller) return;
  if (!state.settings.configured) {
    state.draftText = content;
    toast("先在设置里连接一个模型，就可以开始聊天");
    route("settings");
    return;
  }
  if (!state.cid) {
    const conv = await api("/conversations", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.agentId }),
    });
    state.cid = conv.id;
    state.messages = [];
  }
  state.draftText = "";
  await consumeStream(
    "/conversations/" + state.cid + "/messages/stream",
    { content },
    true,
    content,
  );
}
async function stopGeneration() {
  if (!state.controller || state.stopping) return;
  state.stopping = true;
  const controller = state.controller;
  try {
    await api("/conversations/" + state.cid + "/stop", { method: "POST" });
  } finally {
    controller.abort();
    state.stopping = false;
  }
}
async function consumeStream(path, body, newUser = false, content = "") {
  const cid = state.cid;
  const controller = new AbortController();
  state.controller = controller;
  if (newUser)
    state.messages.push({
      id: "pending-user",
      role: "user",
      content,
      status: "pending",
    });
  else if (path.endsWith("/regenerate"))
    state.messages = state.messages.filter(
      (m, index) =>
        !(index === state.messages.length - 1 && m.role === "assistant"),
    );
  const partial = {
    id: "streaming-reply",
    role: "assistant",
    content: "",
    streaming: true,
  };
  state.messages.push(partial);
  renderChat();
  let serverError = "";
  try {
    const response = await fetch("/api" + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(
        typeof data.detail === "string" ? data.detail : "发送未完成，请重试",
      );
    }
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = frame
          .split("\n")
          .find((x) => x.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = frame
          .split("\n")
          .filter((x) => x.startsWith("data:"))
          .map((x) => x.slice(5).trim())
          .join("\n");
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (kind === "token") {
          partial.content += data.text;
          const element = $("#message-streaming-reply .prose");
          if (element) {
            element.textContent = partial.content;
            $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight;
          }
        }
        if (kind === "meta" && newUser) {
          const pending = state.messages.find((m) => m.id === "pending-user");
          if (pending) pending.id = data.user_id;
        }
        if (kind === "error") serverError = data.message;
      }
    }
    if (serverError) toast(serverError);
  } catch (error) {
    if (error.name !== "AbortError") toast(error.message);
    else toast("已停止生成");
  } finally {
    state.controller = null;
    await bootstrap();
    await openConversation(cid);
  }
}
function renderAgents() {
  main.dataset.view = "agents";
  main.innerHTML =
    header("智能体") +
    `
    <section class="page-scroll">
      <div class="page-content">
        <div class="page-heading">
          <div><span class="eyebrow">角色书架</span><h1>想和谁聊聊？</h1><p>名字之外，也给它一点脾气和偏好。</p></div>
          <button class="button primary" data-action="create-agent">${icon("plus")}创建智能体</button>
        </div>
        <div class="agent-grid">
          ${state.agents
            .map(
              (a) => `
            <article class="agent-card" style="--avatar-color:${esc(agentColor(a))}">
              <div class="agent-card-top">${avatar(a)}<button class="icon-button" data-action="edit-agent" data-id="${a.id}" aria-label="编辑${esc(a.name)}">${icon("edit")}</button></div>
              <h3>${esc(a.name)}</h3><p>${esc(a.tagline || "你的自定义智能体")}</p>
              <div class="agent-card-footer"><small>${a.starters.length ? a.starters.length + " 个开场建议" : "随时开始对话"}</small><button data-action="chat-agent" data-id="${a.id}">开始聊天${icon("arrowRight")}</button></div>
            </article>`,
            )
            .join("")}
          <button class="create-card" data-action="create-agent">
            <span class="create-card-symbol">${icon("plus")}</span>
            <strong>再认识一个新角色</strong><span>自己写，或说个想法让 AI 起草</span>
          </button>
        </div>
        <div class="agents-footnote">${icon("lock")}每个智能体拥有独立的对话和日记。</div>
      </div>
    </section>`;
}
function openAgentEditor(aid = null) {
  state.designNonce = Symbol();
  state.editingAgent = aid;
  const a = state.agents.find((x) => x.id === aid) || {
    name: "",
    tagline: "",
    instructions: "",
    greeting: "",
    starters: [],
    color: "#71806a",
  };
  const form = $("#agent-form");
  ["name", "tagline", "instructions", "greeting", "color"].forEach(
    (key) => (form.elements[key].value = a[key]),
  );
  form.elements.starters.value = a.starters.join("\n");
  $("#agent-error").textContent = "";
  $("#agent-description").value = aid
    ? ("打磨这个已有角色，保留身份、关系和具体偏好，写出有辨识度的说话习惯与对白样例。\n名字：" + a.name + "\n介绍：" + a.tagline + "\n已有设定：\n" + a.instructions).slice(0, 6000)
    : "";
  $("#agent-dialog-title").textContent = aid ? "编辑智能体" : "创建智能体";
  $("#save-agent").textContent = aid ? "保存修改" : "创建智能体";
  $("#save-agent").disabled = false;
  $("#design-agent").disabled = false;
  $("#design-agent").innerHTML = icon("sparkles") + (aid ? "打磨现有设定" : "生成设定");
  $("#archive-agent").hidden = !aid;
  $("#design-panel").hidden = true;
  $$("[data-design]").forEach((b) =>
    b.classList.toggle("active", b.dataset.design === "manual"),
  );
  $("#agent-dialog").showModal();
}
async function designAgent() {
  const description = $("#agent-description").value.trim();
  if (description.length < 5) {
    toast("再多描述一点你想要的智能体吧");
    return;
  }
  const nonce = state.designNonce;
  const button = $("#design-agent");
  button.disabled = true;
  $("#save-agent").disabled = true;
  button.innerHTML = '<span class="loading-spinner"></span>正在构思…';
  $("#agent-error").textContent = "";
  try {
    const draft = await api("/agents/design", {
      method: "POST",
      body: JSON.stringify({ description }),
    });
    if (state.designNonce !== nonce || !$("#agent-dialog").open) return;
    const form = $("#agent-form");
    ["name", "tagline", "instructions", "greeting", "color"].forEach(
      (key) => (form.elements[key].value = draft[key]),
    );
    form.elements.starters.value = draft.starters.join("\n");
    toast("设定写好了，你可以继续调整");
  } catch (error) {
    if (state.designNonce === nonce)
      $("#agent-error").textContent = error.message;
  } finally {
    if (state.designNonce === nonce) {
      button.disabled = false;
      button.innerHTML = icon("sparkles") + (state.editingAgent ? "打磨现有设定" : "生成设定");
      $("#save-agent").disabled = false;
    }
  }
}
async function saveAgent(event) {
  event.preventDefault();
  const form = event.target;
  const draft = Object.fromEntries(new FormData(form));
  draft.starters = draft.starters
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 4);
  const button = $("#save-agent");
  button.disabled = true;
  try {
    await api(
      "/agents" + (state.editingAgent ? "/" + state.editingAgent : ""),
      {
        method: state.editingAgent ? "PUT" : "POST",
        body: JSON.stringify(draft),
      },
    );
    $("#agent-dialog").close();
    await bootstrap();
    route("agents");
    toast("智能体已保存");
  } catch (error) {
    $("#agent-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
function renderSettings() {
  const s = state.settings;
  state.clearKey = false;
  main.dataset.view = "settings";
  main.innerHTML =
    header("设置") +
    `
    <section class="page-scroll">
      <div class="page-content settings-content">
        <div class="page-heading">
          <div><span class="eyebrow">让 Cijora 更合你的习惯</span><h1>连接与偏好</h1><p>连接常用的模型，调整回复方式与日记记录。</p></div>
        </div>
        <form id="settings-form">
          <div class="settings-layout">
            <div class="settings-main">
              <section class="settings-card">
                <div class="section-heading"><span class="section-symbol">${icon("settings")}</span><div><h2>模型连接</h2><p>支持 OpenAI 兼容接口和本地模型。</p></div></div>
                <label>服务商<select name="provider">
                  <option value="custom">自定义兼容接口</option><option value="zhipu">智谱</option><option value="deepseek">DeepSeek</option><option value="dashscope">通义千问</option><option value="openai">OpenAI</option><option value="local">本地服务</option>
                </select></label>
                <label>API 地址<input name="base_url" required type="url" value="${esc(s.base_url)}" placeholder="https://example.com/v1"></label>
                <label>模型名称<input name="model" value="${esc(s.model)}" required placeholder="填写服务商提供的模型名称"></label>
                <label>API Key<div class="key-row"><input name="api_key" type="password" autocomplete="off" placeholder="${s.has_api_key ? "已保存，留空则保留" : "本地免密服务可以留空"}"><button type="button" data-action="clear-key" ${s.has_api_key ? "" : "hidden"}>清除已存密钥</button></div></label>
                <div class="field-footnote">${icon("lock")}密钥在本机加密保存，页面不会读回密钥。</div>
              </section>
              <details class="settings-card preferences-card">
                <summary><span>${icon("edit")}回复偏好</span>${icon("chevron")}</summary>
                <p class="settings-description">通常保留默认值即可。</p>
                <div class="form-grid"><label>创造性<input name="temperature" type="number" min="0" max="2" step="0.1" value="${s.temperature ?? 0.7}"></label><label>最大回复长度<input name="max_tokens" type="number" min="128" max="16384" step="128" value="${s.max_tokens ?? 2048}"></label></div>
                <label id="chat-thinking-option" hidden><span class="thinking-choice"><input type="checkbox" name="chat_thinking" ${s.chat_thinking ? "checked" : ""}>聊天时开启深度思考</span><small>官方 Flash 可选。日常聊天默认关闭；开启后创造性参数不生效。</small></label>
              </details>
            </div>
            <aside class="settings-card journal-settings">
              <figure class="settings-journal-art"><img src="/assets/art/deer-companion.png" alt="" width="1254" height="1254"></figure>
              <div class="journal-settings-copy"><span class="eyebrow">THE DAILY PAGES</span><h2>让今天，有迹可循。</h2><p>停聊 10 分钟后合并记下这段回忆，同一天最多每小时自动更新一次。手动整理不受等待限制。</p>
                <div class="switch-row"><span>自动整理日记</span><label class="toggle"><input type="checkbox" name="auto_diary" ${s.auto_diary ? "checked" : ""} aria-label="空闲后自动整理共同回忆"><span></span></label></div>
                <label>日记日期时区<select name="offset_minutes"><option value="480">中国标准时间 · UTC+8</option><option value="0">协调世界时 · UTC</option></select></label>
                <p class="settings-detail">应用重新打开时，会补齐今天和昨天未完成的记录。</p>
              </div>
            </aside>
          </div>
          <div class="settings-actions"><button class="button primary" type="submit" id="save-settings">保存设置</button><button class="button" type="button" id="test-settings" data-action="test-settings">测试连接</button><span class="settings-result" id="settings-result" role="status"></span></div>
          <p class="settings-footnote">角色设计与日记整理会使用当前模型，产生相应的模型调用。</p>
        </form>
      </div>
    </section>`;
  const form = $("#settings-form");
  form.elements.provider.value = s.provider || "custom";
  form.elements.offset_minutes.value = String(s.offset_minutes ?? 480);
  const syncThinkingOption = () => {
    let official = false;
    try { official = new URL(form.elements.base_url.value).hostname === "api.deepseek.com"; } catch {}
    $("#chat-thinking-option").hidden = !(official && form.elements.model.value.trim() === "deepseek-flash");
  };
  form.elements.base_url.addEventListener("input", syncThinkingOption);
  form.elements.model.addEventListener("input", syncThinkingOption);
  syncThinkingOption();
  form.elements.provider.addEventListener("change", () => {
    const preset = {
      zhipu: ["https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"],
      deepseek: ["https://api.deepseek.com", "deepseek-flash"],
      dashscope: ["https://dashscope.aliyuncs.com/compatible-mode/v1", ""],
      openai: ["https://api.openai.com/v1", ""],
      local: ["http://127.0.0.1:11434/v1", ""],
    }[form.elements.provider.value];
    if (preset) {
      form.elements.base_url.value = preset[0];
      form.elements.model.value = preset[1];
    }
    syncThinkingOption();
  });
}
function settingsDraft() {
  const form = $("#settings-form");
  return {
    provider: form.elements.provider.value,
    base_url: form.elements.base_url.value.trim(),
    model: form.elements.model.value.trim(),
    api_key: form.elements.api_key.value.trim() || null,
    clear_api_key: state.clearKey,
    temperature: Number(form.elements.temperature.value),
    chat_thinking: form.elements.chat_thinking.checked,
    max_tokens: Number(form.elements.max_tokens.value),
    auto_diary: form.elements.auto_diary.checked,
    offset_minutes: Number(form.elements.offset_minutes.value),
  };
}
async function saveSettings(event) {
  event.preventDefault();
  const button = $("#save-settings");
  button.disabled = true;
  try {
    state.settings = await api("/settings", {
      method: "PUT",
      body: JSON.stringify(settingsDraft()),
    });
    renderSidebar();
    renderSettings();
    toast("设置已保存");
  } catch (error) {
    settingsResult(error.message, false);
  } finally {
    const b = $("#save-settings");
    if (b) b.disabled = false;
  }
}
function settingsResult(text, success) {
  const el = $("#settings-result");
  if (el) {
    el.textContent = text;
    el.className = "settings-result " + (success ? "success" : "error");
  }
}
async function testSettings() {
  const button = $("#test-settings");
  button.disabled = true;
  settingsResult("正在连接…", true);
  try {
    const result = await api("/settings/test", {
      method: "POST",
      body: JSON.stringify(settingsDraft()),
    });
    settingsResult(
      "连接成功 · " + (result.elapsed_ms / 1000).toFixed(1) + " 秒",
      true,
    );
  } catch (error) {
    settingsResult(error.message, false);
  } finally {
    button.disabled = false;
  }
}
async function renderDiary() {
  main.innerHTML =
    header("日记") +
    '<div class="boot-state"><span class="loading-spinner"></span>正在翻开日记…</div>';
  try {
    const data = await api(
      "/diaries" +
        (state.diaryAgent
          ? "?agent_id=" + encodeURIComponent(state.diaryAgent)
          : ""),
    );
    if (state.view !== "diary") return;
    state.diaryData = data.entries;
    state.runs = data.runs;
    if (!data.entries.find((d) => d.id === state.diaryId))
      state.diaryId = data.entries[0]?.id;
    paintDiary();
  } catch (error) {
    toast(error.message);
  }
}
function paintDiary() {
  const entries = state.diaryData;
  const entry = entries.find((d) => d.id === state.diaryId) || entries[0];
  if (entry) state.diaryId = entry.id;
  const running = state.runs.filter((r) =>
    ["queued", "running"].includes(r.status),
  );
  const scheduled = state.runs.filter((r) => r.status === "scheduled");
  const failed = state.runs.find(
    (r) =>
      r.status === "failed" &&
      (!state.diaryAgent || r.agent_id === state.diaryAgent),
  );
  main.dataset.view = "diary";
  main.innerHTML =
    header("日记") +
    `
    <section class="page-scroll"><div class="page-content">
      <div class="page-heading"><div><span class="eyebrow">聊过的点滴，都有一页位置</span><h1>我们的日记</h1><p>记下我们聊过的话、一起想过的事。每一页都能回到原对话。</p></div><span class="page-heading-symbol">${icon("book")}</span></div>
      <div class="diary-toolbar">
        <select id="diary-agent-filter" aria-label="按智能体查看日记"><option value="">所有智能体</option>${state.agents.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("")}</select>
        <input type="date" id="diary-day" value="${today()}" max="${today()}" aria-label="日记日期">
        <button class="button" data-action="generate-diary">${icon("edit")}整理这一天</button>
      </div>
      ${running.length ? `<div class="diary-status"><span class="loading-spinner"></span>正在记下我们聊过的一个片段…</div>` : scheduled.length ? `<div class="diary-status">${icon("clock")}等这段聊天告一段落再一起记，停聊 10 分钟后整理，最多每小时自动更新一次。</div>` : failed ? `<div class="diary-status error">上一次整理未完成：${esc(failed.error)}</div>` : ""}
      <div class="diary-layout">
      ${
        entries.length
          ? `
        <div class="diary-list"><div class="diary-list-heading">日常手记<span>${entries.length} 篇</span></div>
          ${entries.map((d) => `<button class="diary-item ${d.id === state.diaryId ? "active" : ""}" data-action="select-diary" data-id="${d.id}"><time>${esc(d.day)}</time><strong>${esc(d.title)}</strong><p>${esc(d.summary)}</p><small>${esc(d.agent_name)}</small></button>`).join("")}
        </div>
        <article class="diary-paper">
          <div class="diary-meta">${icon("clock")}${esc(entry.day)}<span>·</span>${esc(entry.agent_name)}</div>
          <h2>${esc(entry.title)}</h2><div class="prose">${entry.html}</div>
          <div class="diary-tags">${entry.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
          <div class="diary-article-tools"><a href="/api/diaries/${entry.id}/export">${icon("download")}导出</a><button data-action="regenerate-diary" data-id="${entry.id}">${icon("refresh")}重新整理</button><button data-action="diary-sources" data-id="${entry.id}">${icon("chat")}查看对话来源 · ${entry.source_count}</button><button class="danger" data-action="delete-diary" data-id="${entry.id}">${icon("trash")}删除日记</button></div>
          <div class="source-list" id="source-list" hidden></div>
        </article>
      `
          : `
        <div class="diary-empty">
          <figure><img src="/assets/art/deer-companion.png" alt="" width="1254" height="1254"></figure>
          <div class="diary-empty-copy"><span class="eyebrow">第一篇日记，留给今天</span><h2>还没开始写。</h2><p>聊过的小事、互相打趣的话、说定的事，<br>以后可以在这里重新翻到。</p><button class="button primary" data-view="chat">从一段对话开始${icon("arrowRight")}</button></div>
        </div>
      `
      }
      </div>
    </div></section>`;
  $("#diary-agent-filter").value = state.diaryAgent;
  $("#diary-agent-filter").addEventListener("change", (event) => {
    state.diaryAgent = event.target.value;
    renderDiary();
  });
  if (running.length || scheduled.length) {
    clearTimeout(diaryTimer);
    diaryTimer = setTimeout(() => {
      if (state.view === "diary") refreshDiaries();
    }, running.length ? 2500 : 30000);
  }
}
async function refreshDiaries() {
  const data = await api(
    "/diaries" + (state.diaryAgent ? "?agent_id=" + state.diaryAgent : ""),
  );
  if (state.view !== "diary") return;
  state.diaryData = data.entries;
  state.runs = data.runs;
  if (!data.entries.some((d) => d.id === state.diaryId))
    state.diaryId = data.entries[0]?.id;
  paintDiary();
  renderSidebar();
}
async function generateDiary(entry = null) {
  const aid =
    entry?.agent_id || $("#diary-agent-filter").value || state.agentId;
  const day = entry?.day || $("#diary-day").value;
  if (!day) return;
  await api("/diaries/generate", {
    method: "POST",
    body: JSON.stringify({ agent_id: aid, day }),
  });
  toast("已开始整理，稍后会自动出现在这里");
  await refreshDiaries();
}
async function showSources(id) {
  const box = $("#source-list");
  if (!box.hidden) {
    box.hidden = true;
    return;
  }
  const sources = await api("/diaries/" + id + "/sources");
  box.innerHTML =
    sources
      .map(
        (m) =>
          `<button class="source-item" data-action="source-chat" data-id="${m.conversation_id}" data-message="${m.id}"><small>${esc(m.conversation_title)} · ${m.role === "user" ? "你" : "智能体"}</small><p>${esc(m.content.slice(0, 180))}${m.content.length > 180 ? "…" : ""}</p></button>`,
      )
      .join("") || '<p class="settings-footnote">原对话已移出列表。</p>';
  box.hidden = false;
}
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.append(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    textarea.remove();
    toast(ok ? "已复制" : "请选中文字后复制");
  }
}
function download(name, text) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

async function action(name, element) {
  const id = element.dataset.id;
  if (name === "toggle-diary-peek") {
    document.body.classList.remove("sidebar-open");
    document.body.classList.toggle("diary-open");
    state.diaryPeekOpen = document.body.classList.contains("diary-open");
    syncDiaryToggle();
    if (document.body.classList.contains("diary-open")) $(".peek-close")?.focus();
    else $(".diary-peek-toggle")?.focus();
    return;
  }
  if (name === "focus-composer") {
    if (!wideChat.matches) document.body.classList.remove("diary-open");
    syncDiaryToggle();
    $("#composer-input")?.focus();
    return;
  }
  if (name === "open-diary") {
    state.diaryId = id;
    route("diary");
    return;
  }

  if (name === "sidebar") {
    document.body.classList.toggle("sidebar-open");
    return;
  }
  if (name === "agent-menu") {
    $("#agent-menu").hidden = !$("#agent-menu").hidden;
    return;
  }
  if (name === "chat-menu") {
    $("#chat-menu").hidden = !$("#chat-menu").hidden;
    return;
  }
  if (name === "open-chat") return openConversation(id);
  if (name === "select-agent" || name === "chat-agent") {
    closeMenus();
    newChat(id);
    return;
  }
  if (name === "create-agent") {
    openAgentEditor();
    return;
  }
  if (name === "edit-agent") {
    openAgentEditor(id);
    return;
  }
  if (name === "clear-key") {
    state.clearKey = !state.clearKey;
    element.textContent = state.clearKey ? "撤销清除" : "清除已存密钥";
    return;
  }
  if (name === "test-settings") return testSettings();
  if (name === "select-diary") {
    state.diaryId = id;
    paintDiary();
    return;
  }
  if (name === "generate-diary") return generateDiary();
  if (name === "regenerate-diary")
    return generateDiary(state.diaryData.find((d) => d.id === id));
  if (name === "diary-sources") return showSources(id);
  if (name === "delete-diary") {
    if (!confirm("删除这篇日记？删除后不会自动重建，聊天记录会保留。")) return;
    await api("/diaries/" + id, { method: "DELETE" });
    state.diaryId = null;
    await renderDiary();
    toast("日记已删除");
    return;
  }
  if (name === "source-chat") {
    await openConversation(id);
    document
      .getElementById("message-" + element.dataset.message)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
    return;
  }
  if (name === "copy-message")
    return copyText(state.messages.find((m) => m.id === id)?.content || "");
  if (name === "retry" || name === "regenerate") {
    if (state.controller) return;
    return consumeStream(
      "/conversations/" +
        state.cid +
        "/messages/" +
        id +
        "/" +
        (name === "retry" ? "retry" : "regenerate"),
      {},
      false,
    );
  }
  if (name === "rename-chat") {
    if (!state.cid) {
      toast("发送第一条消息后，就可以为对话命名");
      return;
    }
    $("#rename-form").elements.title.value =
      state.conversations.find((c) => c.id === state.cid)?.title || "";
    $("#rename-dialog").showModal();
    closeMenus();
    return;
  }
  if (name === "export-chat") {
    if (!state.messages.length) {
      toast("还没有可以导出的内容");
      return;
    }
    download(
      "对话.md",
      state.messages
        .map(
          (m) =>
            "## " +
            (m.role === "user" ? "你" : activeAgent()?.name || "智能体") +
            "\n\n" +
            m.content,
        )
        .join("\n\n"),
    );
    return;
  }
  if (name === "delete-chat") {
    if (!state.cid) return;
    if (!confirm("从列表中移除这段对话？")) return;
    await api("/conversations/" + state.cid, { method: "DELETE" });
    await bootstrap();
    newChat();
    toast("对话已移出列表");
  }
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("diary-open")) {
    state.diaryPeekOpen = false;
    closeSidebar();
    $(".diary-peek-toggle")?.focus();
  }
});
document.addEventListener("click", (event) => {
  const nav = event.target.closest("button[data-view], a[data-view]");
  if (nav) {
    event.preventDefault();
    route(nav.dataset.view);
    return;
  }
  const el = event.target.closest("[data-action]");
  if (el) action(el.dataset.action, el).catch((error) => toast(error.message));
  if (!event.target.closest(".popover-wrap")) closeMenus();
  const mode = event.target.closest("[data-design]");
  if (mode) {
    $("#design-panel").hidden = mode.dataset.design !== "ai";
    $$("[data-design]").forEach((b) =>
      b.classList.toggle("active", b === mode),
    );
  }
  if (event.target.closest(".dialog-close"))
    event.target.closest("dialog").close();
});
document.addEventListener("submit", (event) => {
  if (event.target.id === "composer-form") {
    event.preventDefault();
    if (state.controller) stopGeneration().catch((e) => toast(e.message));
    else sendMessage().catch((e) => toast(e.message));
  }
  if (event.target.id === "settings-form") saveSettings(event);
});
$("#agent-form").addEventListener("submit", saveAgent);
$("#design-agent").addEventListener("click", designAgent);
$("#archive-agent").addEventListener("click", async () => {
  if (!confirm("归档这个智能体？已有对话与日记会保留。")) return;
  try {
    await api("/agents/" + state.editingAgent, { method: "DELETE" });
    $("#agent-dialog").close();
    await bootstrap();
    route("agents");
    toast("智能体已归档");
  } catch (e) {
    $("#agent-error").textContent = e.message;
  }
});
$("#rename-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/conversations/" + state.cid, {
      method: "PATCH",
      body: JSON.stringify({ title: event.target.elements.title.value.trim() }),
    });
    $("#rename-dialog").close();
    await bootstrap();
  } catch (e) {
    toast(e.message);
  }
});
$("#new-chat").addEventListener("click", () => newChat());
$("#scrim").addEventListener("click", closeSidebar);
$("#search-toggle").addEventListener("click", () => {
  const label = $("#history-search");
  label.hidden = !label.hidden;
  if (!label.hidden) $("#search-input").focus();
  else {
    $("#search-input").value = "";
    renderSidebar();
  }
});
$("#search-input").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const query = $("#search-input").value.trim();
    try {
      const rows = await api("/conversations?q=" + encodeURIComponent(query));
      if ($("#search-input").value.trim() !== query) return;
      state.searchTerm = query.toLowerCase();
      state.searchResults = rows;
      renderSidebar();
    } catch (e) {
      toast(e.message);
    }
  }, 220);
});
window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (
    ["chat", "agents", "diary", "settings"].includes(view) &&
    view !== state.view
  )
    route(view);
});

async function start() {
  hydrate();
  try {
    const params = new URLSearchParams(location.search);
    const book = params.get("book");
    const session = await api("/session", {
      method: "POST",
      body: JSON.stringify({
        book: /^[a-f0-9]{32}$/.test(book || "") ? book : null,
      }),
    });
    const url = new URL(location);
    url.searchParams.set("book", session.book);
    history.replaceState(null, "", url);
    await bootstrap();
    state.agentId = state.agents[0]?.id;
    const desired = location.hash.slice(1);
    const letter = params.get("letter");
    if (
      letter &&
      state.conversations.some((c) => c.id === letter) &&
      (!desired || desired === "chat")
    )
      await openConversation(letter);
    else {
      if (letter && !state.conversations.some((c) => c.id === letter)) {
        url.searchParams.delete("letter");
        history.replaceState(null, "", url);
      }
      route(
        ["chat", "agents", "diary", "settings"].includes(desired)
          ? desired
          : "chat",
      );
    }
  } catch (error) {
    main.innerHTML = `<div class="empty-page">${icon("chat")}<h3>暂时没能打开空间</h3><p>${esc(error.message)}</p><button class="button" data-action="reload">重新打开</button></div>`;
    $('[data-action="reload"]').addEventListener("click", () =>
      location.reload(),
    );
  }
}
start();
