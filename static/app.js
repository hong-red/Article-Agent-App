/* 妙文 App —— 前端逻辑（PWA） */
const $ = (id) => document.getElementById(id);

let TOKEN = localStorage.getItem("token") || "";
let authMode = "login";

function setToken(t) { TOKEN = t; if (t) localStorage.setItem("token", t); else localStorage.removeItem("token"); }

const state = {
  step: 1, topic: "", style: "", extra: "", template: "general",
  titles: [], selectedTitle: "", title: "", contentMd: "", theme: "default",
  tone: "", addSummary: false, addGolden: false, addFollow: false, polish: true,
  contentHtml: "", articleId: null, coverUrl: "",
  selectedImages: [], localImages: [], imgResults: [],
};

/* ---------- 基础 ---------- */
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (res.status === 401) { showLogin(); throw new Error(data && data.detail || "未登录"); }
  if (!res.ok) throw new Error((data && (data.detail || data.message)) || `请求失败 (${res.status})`);
  return data;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let toastTimer = null;
function toast(msg, type = "info") {
  const t = $("toast");
  t.textContent = msg; t.className = "toast show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast hidden"; }, 3200);
}
function debounce(fn, ms) { let t = null; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ---------- 登录 / 注册 ---------- */
function showLogin() { $("view-login").classList.remove("hidden"); $("view-app").classList.add("hidden"); }
function showApp() { $("view-login").classList.add("hidden"); $("view-app").classList.remove("hidden"); }

$("tab-login").addEventListener("click", () => {
  authMode = "login";
  $("tab-login").classList.add("active"); $("tab-register").classList.remove("active");
  $("lg-invite-row").classList.add("hidden"); $("btn-auth").textContent = "登录";
});
$("tab-register").addEventListener("click", () => {
  authMode = "register";
  $("tab-register").classList.add("active"); $("tab-login").classList.remove("active");
  $("lg-invite-row").classList.remove("hidden"); $("btn-auth").textContent = "注册";
});

$("btn-auth").addEventListener("click", async () => {
  const username = $("lg-username").value.trim();
  const password = $("lg-password").value;
  const btn = $("btn-auth");
  btn.disabled = true;
  try {
    if (authMode === "register") {
      const invite = $("lg-invite").value.trim();
      await post("/api/auth/register", { username, password, invite_code: invite });
      toast("注册成功，请登录", "success");
      $("tab-login").click();
    } else {
      const r = await post("/api/auth/login", { username, password });
      setToken(r.token);
      await init();
      showApp();
      toast("欢迎，" + r.username, "success");
    }
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; }
});

$("btn-logout").addEventListener("click", async () => {
  try { await post("/api/auth/logout", {}); } catch (e) {}
  setToken("");
  showLogin();
});

/* ---------- 步骤切换 ---------- */
function goTo(n) {
  state.step = n;
  [1, 2, 3, 4].forEach((i) => {
    $("step-" + i).classList.toggle("hidden", i !== n);
    document.querySelector(`.step[data-step="${i}"]`).classList.toggle("active", i === n);
    document.querySelector(`.step[data-step="${i}"]`).classList.toggle("done", i < n);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => goTo(parseInt(b.dataset.goto))));

async function renderPreview(md, title, targetId, theme) {
  if (!md.trim()) { $(targetId).innerHTML = '<p class="muted">暂无内容</p>'; return; }
  try { const r = await post("/api/render", { content: md, title, theme: theme || "default" }); $(targetId).innerHTML = r.html; } catch (e) {}
}

/* ---------- 第 1 步 ---------- */
$("btn-gen-titles").addEventListener("click", async () => {
  const topic = $("s1-topic").value.trim();
  if (!topic) { toast("请先填写文章主题", "error"); return; }
  state.topic = topic; state.style = $("s1-style").value.trim(); state.extra = $("s1-extra").value.trim();
  state.template = $("s1-template").value; const count = parseInt($("s1-count").value);
  const btn = $("btn-gen-titles"); btn.disabled = true; btn.textContent = "生成中…";
  try {
    const r = await post("/api/generate/titles", { topic, count, style: state.style, extra: state.extra, template: state.template });
    state.titles = r.titles; renderTitles(); toast("题目已生成", "success");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "生成题目"; }
});
function renderTitles() {
  const box = $("titles-box");
  box.innerHTML = state.titles.map((t, i) => `<label class="title-opt"><input type="radio" name="title" value="${i}"><span>${escapeHtml(t)}</span></label>`).join("");
  box.querySelectorAll(".title-opt").forEach((opt) => opt.addEventListener("click", () => {
    box.querySelectorAll(".title-opt").forEach((o) => o.classList.remove("selected"));
    opt.classList.add("selected");
    state.selectedTitle = state.titles[parseInt(opt.querySelector("input").value)];
    $("btn-to-step2").disabled = false;
  }));
}
$("btn-to-step2").addEventListener("click", () => {
  state.title = state.selectedTitle; $("s2-title").value = state.title;
  $("s2-topic").innerHTML = `主题：<b>${escapeHtml(state.topic)}</b>`;
  goTo(2);
});

/* ---------- 第 2 步 ---------- */
$("btn-gen-content").addEventListener("click", async () => {
  state.title = $("s2-title").value.trim();
  if (!state.title) { toast("请先填写标题", "error"); return; }
  const btn = $("btn-gen-content"); btn.disabled = true; btn.textContent = "写作中…";
  try {
    const r = await post("/api/generate/content", { topic: state.topic, title: state.title, style: state.style, extra: state.extra, template: state.template, feedback: "", previous_content: "" });
    state.contentMd = r.content; $("s2-md").value = r.content;
    renderPreview(r.content, state.title, "s2-preview", state.theme);
    toast("正文已生成", "success");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "生成正文"; }
});
$("btn-refine").addEventListener("click", async () => {
  const feedback = $("s2-feedback").value.trim();
  if (!feedback) { toast("请先填写调试意见", "error"); return; }
  if (!state.contentMd) { toast("请先生成正文", "error"); return; }
  const btn = $("btn-refine"); btn.disabled = true; btn.textContent = "改写中…";
  try {
    const r = await post("/api/generate/content", { topic: state.topic, title: state.title, style: state.style, extra: state.extra, template: state.template, feedback, previous_content: $("s2-md").value });
    state.contentMd = r.content; $("s2-md").value = r.content; $("s2-feedback").value = "";
    renderPreview(r.content, state.title, "s2-preview", state.theme);
    toast("已按意见重新生成", "success");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "按意见重新生成"; }
});
$("s2-md").addEventListener("input", debounce(() => { state.contentMd = $("s2-md").value; renderPreview(state.contentMd, state.title, "s2-preview", state.theme); }, 500));
$("btn-to-step3").addEventListener("click", async () => {
  state.contentMd = $("s2-md").value;
  if (!state.contentMd.trim()) { toast("请先生成正文", "error"); return; }
  state.title = $("s2-title").value.trim();
  await loadLocalImages(); renderSelected(); goTo(3);
});

/* ---------- 第 3 步：选图 ---------- */
document.querySelectorAll("[data-imgtab]").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll("[data-imgtab]").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  const tab = t.dataset.imgtab;
  $("img-tab-local").classList.toggle("hidden", tab !== "local");
  $("img-tab-web").classList.toggle("hidden", tab !== "web");
}));
async function loadLocalImages() {
  try { state.localImages = await api("/api/images"); renderLocalGrid(); } catch (e) {}
}
function isImgSelected(key) { return state.selectedImages.some((s) => s.key === key); }
function renderLocalGrid() {
  const grid = $("img-local-grid");
  if (!state.localImages.length) { grid.innerHTML = '<p class="muted">还没有上传图片</p>'; return; }
  grid.innerHTML = state.localImages.map((img, i) => `
    <div class="img-card ${isImgSelected(img.url) ? "selected" : ""}">
      <div class="img-thumb"><img src="${img.url}" loading="lazy" alt=""></div>
      <button class="btn ghost small" data-luse="${i}">${isImgSelected(img.url) ? "取消" : "使用"}</button>
    </div>`).join("");
  grid.querySelectorAll("[data-luse]").forEach((b) => b.addEventListener("click", () => toggleLocal(parseInt(b.dataset.luse))));
}
function toggleLocal(i) {
  const img = state.localImages[i];
  if (isImgSelected(img.url)) state.selectedImages = state.selectedImages.filter((s) => s.key !== img.url);
  else state.selectedImages.push({ key: img.url, url: img.url, name: img.name });
  renderLocalGrid(); renderSelected();
}
function renderSelected() {
  const box = $("img-selected");
  $("img-count").textContent = state.selectedImages.length;
  box.innerHTML = state.selectedImages.length
    ? state.selectedImages.map((img, i) => `<div class="img-card"><div class="img-thumb"><img src="${img.url}" alt=""></div><button class="btn ghost small" data-rm="${i}">移除</button></div>`).join("")
    : '<p class="muted">尚未选择图片</p>';
  box.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => {
    state.selectedImages.splice(parseInt(b.dataset.rm), 1); renderSelected(); renderLocalGrid(); renderWebGrid();
  }));
}
$("btn-upload-img").addEventListener("click", async () => {
  const files = $("img-file").files;
  if (!files.length) { toast("请先选择图片", "error"); return; }
  const fd = new FormData(); for (const f of files) fd.append("files", f);
  await api("/api/images", { method: "POST", body: fd });
  $("img-file").value = ""; toast("图片已上传", "success"); await loadLocalImages();
});
$("btn-search-img").addEventListener("click", async () => {
  const q = $("img-query").value.trim();
  if (!q) { toast("请输入关键词", "error"); return; }
  $("img-web-grid").innerHTML = '<p class="muted">搜索中…</p>';
  try { state.imgResults = (await post("/api/images/search", { query: q })).results || []; renderWebGrid(); } catch (e) { toast(e.message, "error"); }
});
function renderWebGrid() {
  const grid = $("img-web-grid");
  grid.innerHTML = state.imgResults.map((img, i) => `<div class="img-card ${isImgSelected(img.url) ? "selected" : ""}"><div class="img-thumb"><img src="${escapeHtml(img.thumb || img.url)}" loading="lazy"></div><button class="btn ghost small" data-wuse="${i}">使用</button></div>`).join("");
  grid.querySelectorAll("[data-wuse]").forEach((b) => b.addEventListener("click", () => useWeb(parseInt(b.dataset.wuse))));
}
async function useWeb(i) {
  const img = state.imgResults[i];
  if (isImgSelected(img.url)) { state.selectedImages = state.selectedImages.filter((s) => s.key !== img.url); renderWebGrid(); renderSelected(); return; }
  toast("正在下载图片…", "info");
  try {
    const r = await post("/api/images/fetch", { url: img.url, thumb: img.thumb, page: img.page });
    state.selectedImages.push({ key: img.url, url: r.url, name: img.title || r.name });
    renderWebGrid(); renderSelected();
  } catch (e) { toast(e.message, "error"); }
}
function fullContentMd() {
  let md = $("s3-md").value || state.contentMd || "";
  const pending = state.selectedImages.filter((s) => !md.includes(s.url));
  if (pending.length) md = md.trimEnd() + "\n\n" + pending.map((s) => `![${s.name}](${s.url})`).join("\n");
  return md;
}
$("btn-to-step4").addEventListener("click", () => { $("s3-md").value = state.contentMd; renderPreview(fullContentMd(), state.title, "s3-preview", state.theme); goTo(4); });

/* ---------- 第 4 步 ---------- */
$("btn-format").addEventListener("click", async () => {
  state.contentMd = $("s3-md").value; state.title = $("s2-title").value.trim();
  if (!state.contentMd) { toast("正文为空", "error"); return; }
  const btn = $("btn-format"); btn.disabled = true; btn.textContent = "排版中…";
  try {
    const r = await post("/api/generate/format", {
      content: state.contentMd, title: state.title, theme: state.theme, tone: state.tone, template: state.template,
      add_summary: $("s3-summary").checked, add_golden: $("s3-golden").checked, add_follow: $("s3-follow").checked,
      polish: $("s3-polish").checked, images: state.selectedImages.map((s) => ({ url: s.url, alt: s.name })),
    });
    state.contentMd = r.content; state.contentHtml = r.html; state.selectedImages = [];
    $("s3-md").value = r.content; $("s3-preview").innerHTML = r.html;
    toast("格式优化完成", "success");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "格式优化"; }
});
$("s3-theme").addEventListener("change", () => { state.theme = $("s3-theme").value; renderPreview(fullContentMd(), state.title, "s3-preview", state.theme); });
$("s3-tone").addEventListener("change", () => { state.tone = $("s3-tone").value; });
$("s3-md").addEventListener("input", debounce(() => { state.contentMd = $("s3-md").value; renderPreview(fullContentMd(), state.title, "s3-preview", state.theme); }, 500));
$("s3-cover").addEventListener("change", () => { const f = $("s3-cover").files[0]; if (f) $("s3-cover-preview").innerHTML = `<img src="${URL.createObjectURL(f)}" alt="封面预览">`; });

/* ---------- 保存 / 推送 ---------- */
async function saveArticle() {
  const body = { topic: state.topic, title: state.title || $("s2-title").value.trim(), content_md: fullContentMd(), content_html: "", theme: state.theme, cover: "" };
  if (!body.title) throw new Error("缺少文章标题");
  if (!body.content_md.trim()) throw new Error("正文为空");
  let r;
  if (state.articleId) r = await api(`/api/articles/${state.articleId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  else r = await post("/api/articles", body);
  state.articleId = r.id; return r.id;
}
async function uploadCoverIfNeeded(id) {
  const f = $("s3-cover").files[0];
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  await api(`/api/articles/${id}/cover`, { method: "POST", body: fd });
}
$("btn-save").addEventListener("click", async () => {
  try { const id = await saveArticle(); await uploadCoverIfNeeded(id); toast("已保存", "success"); } catch (e) { toast(e.message, "error"); }
});
$("btn-push").addEventListener("click", async () => {
  const btn = $("btn-push"); btn.disabled = true; btn.textContent = "推送中…";
  try {
    if (!state.articleId) { await saveArticle(); await uploadCoverIfNeeded(state.articleId); }
    await post(`/api/articles/${state.articleId}/push`, {});
    toast("已推送到公众号草稿箱", "success");
  } catch (e) { toast(e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "推送到草稿箱"; }
});

/* ---------- 设置 / 导出 ---------- */
$("btn-settings").addEventListener("click", () => openModal("modal-settings"));
$("btn-library").addEventListener("click", async () => { openModal("modal-library"); await loadLibrary(); });
function openModal(id) { $(id).classList.remove("hidden"); }
function closeModal(id) { $(id).classList.add("hidden"); }
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => closeModal(b.dataset.close)));
document.querySelectorAll(".modal-mask").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); }));

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    $("cfg-model").value = s.deepseek_model || "deepseek-chat";
    $("cfg-appid").value = s.wechat_appid || "";
    $("cfg-author").value = s.wechat_author || "";
    $("cfg-source-url").value = s.wechat_source_url || "";
    if (s.deepseek_api_key_set) $("cfg-key").placeholder = "已设置（留空则不修改）";
    if (s.wechat_appsecret_set) $("cfg-secret").placeholder = "已设置（留空则不修改）";
  } catch (e) {}
}
$("btn-save-config").addEventListener("click", async () => {
  const body = { deepseek_model: $("cfg-model").value, wechat_appid: $("cfg-appid").value.trim(), wechat_author: $("cfg-author").value.trim(), wechat_source_url: $("cfg-source-url").value.trim() };
  if ($("cfg-key").value.trim()) body.deepseek_api_key = $("cfg-key").value.trim();
  if ($("cfg-secret").value.trim()) body.wechat_appsecret = $("cfg-secret").value.trim();
  try { await post("/api/settings", body); toast("设置已保存", "success"); closeModal("modal-settings"); } catch (e) { toast(e.message, "error"); }
});
$("btn-export").addEventListener("click", async () => {
  try {
    const data = await api("/api/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `妙文数据_${data.username || "user"}.json`;
    a.click(); URL.revokeObjectURL(a.href);
    toast("数据已导出", "success");
  } catch (e) { toast(e.message, "error"); }
});

/* ---------- 本地库 ---------- */
async function loadLibrary() {
  const list = $("library-list");
  list.innerHTML = '<p class="muted">加载中…</p>';
  try {
    const items = await api("/api/articles");
    if (!items.length) { list.innerHTML = '<p class="muted">暂无保存的文章</p>'; return; }
    list.innerHTML = items.map((a) => `
      <div class="lib-item"><div class="meta">
        <div class="title">${escapeHtml(a.title)}</div>
        <div class="sub">${escapeHtml(a.topic)} · ${a.updated_at || ""} <span class="badge ${a.status === "pushed" ? "pushed" : ""}">${a.status === "pushed" ? "已推送" : "草稿"}</span></div>
      </div>
      <div class="ops"><button class="btn ghost small" data-load="${a.id}">载入</button><button class="btn ghost small" data-del="${a.id}">删除</button></div></div>`).join("");
    list.querySelectorAll("[data-load]").forEach((b) => b.addEventListener("click", () => loadArticle(parseInt(b.dataset.load))));
    list.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => delArticle(parseInt(b.dataset.del))));
  } catch (e) { list.innerHTML = `<p class="muted">加载失败：${escapeHtml(e.message)}</p>`; }
}
async function loadArticle(id) {
  try {
    const a = await api(`/api/articles/${id}`);
    state.articleId = a.id; state.topic = a.topic; state.title = a.title; state.contentMd = a.content_md; state.theme = a.theme;
    $("s1-topic").value = a.topic; $("s2-title").value = a.title; $("s2-md").value = a.content_md; $("s3-md").value = a.content_md; $("s3-theme").value = a.theme;
    renderPreview(a.content_md, a.title, "s3-preview", a.theme); state.selectedImages = [];
    closeModal("modal-library"); goTo(4); toast("已载入文章", "success");
  } catch (e) { toast(e.message, "error"); }
}
async function delArticle(id) {
  if (!confirm("确定删除这篇文章？")) return;
  try { await api(`/api/articles/${id}`, { method: "DELETE" }); if (state.articleId === id) state.articleId = null; toast("已删除", "success"); await loadLibrary(); } catch (e) { toast(e.message, "error"); }
}

/* ---------- 工具 ---------- */
function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

/* ---------- 初始化 ---------- */
async function init() {
  try {
    const info = await api("/api/info");
    $("free-until").textContent = info.free_until || "2026-12";
  } catch (e) {}
  try {
    const me = await api("/api/auth/me");
    showApp();
    await loadSettings();
    try { const themes = await api("/api/themes"); $("s3-theme").innerHTML = themes.map((t) => `<option value="${t.key}">${t.name}</option>`).join(""); } catch (e) {}
    try { const tpls = await api("/api/templates"); $("s1-template").innerHTML = tpls.map((t) => `<option value="${t.key}">${t.name}</option>`).join(""); if (tpls.length) state.template = tpls[0].key; } catch (e) {}
  } catch (e) { showLogin(); }
}

if ("serviceWorker" in navigator) { navigator.serviceWorker.register("sw.js").catch(() => {}); }
init();
