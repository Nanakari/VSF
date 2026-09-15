const pageHtml = "<!doctype html>\n<html lang=\"zh-CN\">\n  <head>\n    <meta charset=\"utf-8\">\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n    <meta name=\"theme-color\" content=\"#080d19\">\n    <meta name=\"description\" content=\"从 VTuber 歌回时间轴中检索歌曲、艺人和 YouTube 时间点。\">\n    <title>VTuber Song Finder</title>\n    <link rel=\"icon\" type=\"image/svg+xml\" href=\"./favicon.svg\">\n    <link rel=\"stylesheet\" href=\"./styles.css\">\n    <script src=\"./app.js\" defer></script>\n  </head>\n  <body>\n    <div class=\"ambient ambient-a\" aria-hidden=\"true\"></div>\n    <div class=\"ambient ambient-b\" aria-hidden=\"true\"></div>\n    <main class=\"shell\">\n      <header class=\"topbar\">\n        <a class=\"brand\" href=\"./\" aria-label=\"回到首页\">\n          <span class=\"brand-mark\" aria-hidden=\"true\">VSF</span>\n          <span>\n            <span class=\"brand-name\">VTuber Song Finder</span>\n            <span class=\"brand-note\">歌回时间轴检索库</span>\n          </span>\n        </a>\n        <div class=\"topbar-side\">\n          <span class=\"data-status\"><span class=\"status-dot\" aria-hidden=\"true\"></span><span id=\"data-status\">载入数据中</span></span>\n        </div>\n      </header>\n\n      <section class=\"search-panel\" aria-labelledby=\"search-title\">\n        <div class=\"search-panel-heading\">\n          <div>\n            <p class=\"eyebrow\">SEARCH THE ARCHIVE</p>\n            <h1 id=\"search-title\">找到那首歌出现的时间点</h1>\n          </div>\n          <p class=\"search-help\">按频道、歌曲或艺人组合检索，打开后会直接跳到 YouTube 对应时间。</p>\n        </div>\n        <form id=\"search-form\" class=\"searchbar\">\n          <label class=\"field field-channel\">\n            <span>频道</span>\n            <input id=\"channel-input\" name=\"channel\" autocomplete=\"off\" placeholder=\"Shairu / MunMosh\">\n          </label>\n          <label class=\"field field-song\">\n            <span>歌曲</span>\n            <input id=\"song-input\" name=\"song\" autocomplete=\"off\" placeholder=\"KING / 怪物 / Stellar Stellar\">\n          </label>\n          <label class=\"field field-artist\">\n            <span>艺人 / 作者</span>\n            <input id=\"artist-input\" name=\"artist\" autocomplete=\"off\" placeholder=\"YOASOBI / Ado / 米津玄師\">\n          </label>\n          <button class=\"search-button\" type=\"submit\"><span>搜索</span><span class=\"button-arrow\" aria-hidden=\"true\">↗</span></button>\n        </form>\n        <div class=\"quick-row\">\n          <span id=\"stats-summary\">准备载入数据库统计…</span>\n          <button id=\"clear-search\" class=\"clear-button\" type=\"button\" hidden>清除条件</button>\n        </div>\n      </section>\n\n      <section id=\"loading-state\" class=\"state-card\" aria-live=\"polite\">\n        <span class=\"loading-orb\" aria-hidden=\"true\"></span>\n        <div><strong>正在载入歌单索引</strong><span>很快就好。</span></div>\n      </section>\n\n      <section id=\"error-state\" class=\"state-card state-error\" aria-live=\"polite\" hidden>\n        <div><strong>数据暂时无法载入</strong><span>请刷新页面后再试。</span></div>\n        <button id=\"retry-button\" class=\"secondary-button\" type=\"button\">重新载入</button>\n      </section>\n\n      <div id=\"content\" hidden>\n        <section id=\"home-view\" class=\"content-section\" aria-labelledby=\"channels-title\">\n          <div class=\"section-heading\">\n            <div>\n              <p class=\"eyebrow\">CHANNELS</p>\n              <h2 id=\"channels-title\">按频道浏览</h2>\n            </div>\n            <span class=\"section-note\">选择一个频道，直接查看它的歌曲目录</span>\n          </div>\n          <div id=\"channel-grid\" class=\"channel-grid\"></div>\n        </section>\n\n        <section id=\"results-view\" class=\"content-section\" aria-labelledby=\"results-title\" hidden>\n          <div class=\"section-heading results-heading\">\n            <div>\n              <p class=\"eyebrow\">MATCHES</p>\n              <h2 id=\"results-title\">搜索结果</h2>\n            </div>\n            <span id=\"result-summary\" class=\"section-note\"></span>\n          </div>\n          <div id=\"results-list\" class=\"results-list\" aria-live=\"polite\"></div>\n          <div id=\"results-empty\" class=\"empty-state\" hidden>\n            <span class=\"empty-glyph\" aria-hidden=\"true\">⌕</span>\n            <h3>没有找到匹配条目</h3>\n            <p>可以换一种歌曲或作者写法，或者先清除一个筛选条件。</p>\n          </div>\n          <nav id=\"results-pager\" class=\"pager\" aria-label=\"搜索结果分页\" hidden>\n            <button id=\"results-prev\" class=\"pager-button\" type=\"button\">← 上一页</button>\n            <span id=\"results-page-label\"></span>\n            <button id=\"results-next\" class=\"pager-button\" type=\"button\">下一页 →</button>\n          </nav>\n        </section>\n      </div>\n\n      <footer class=\"footer\">\n        <span>时间点来自公开视频评论区中的歌单与时间轴。</span>\n        <span id=\"updated-at\"></span>\n      </footer>\n    </main>\n  </body>\n</html>\n";
const stylesCss = ":root {\n  color-scheme: dark;\n  --bg: #080d19;\n  --bg-deep: #050810;\n  --surface: rgba(15, 25, 44, 0.88);\n  --surface-strong: #111d32;\n  --surface-soft: rgba(20, 35, 59, 0.72);\n  --line: #243653;\n  --line-bright: #385477;\n  --text: #f1f6ff;\n  --muted: #9aabc3;\n  --muted-strong: #c4d1e3;\n  --mint: #61e4c5;\n  --mint-deep: #25b995;\n  --orange: #ffb45c;\n  --purple: #a894ff;\n  --danger: #ff877d;\n  --shadow: 0 22px 70px rgba(0, 0, 0, 0.32);\n}\n\n* { box-sizing: border-box; }\n\n/* Keep the HTML hidden state authoritative even when a component sets\n   display: flex for its normal state. */\n[hidden] { display: none !important; }\n\nhtml { min-width: 320px; background: var(--bg); }\n\nbody {\n  min-height: 100vh;\n  margin: 0;\n  overflow-x: hidden;\n  background:\n    radial-gradient(circle at 4% 0%, rgba(83, 117, 208, 0.18), transparent 31rem),\n    radial-gradient(circle at 96% 14%, rgba(48, 196, 165, 0.11), transparent 28rem),\n    linear-gradient(180deg, var(--bg) 0%, var(--bg-deep) 100%);\n  color: var(--text);\n  font-family: \"Segoe UI\", \"Noto Sans SC\", \"Noto Sans JP\", \"Microsoft YaHei\", sans-serif;\n  font-size: 16px;\n  line-height: 1.5;\n}\n\nbutton, input { font: inherit; }\nbutton, a { -webkit-tap-highlight-color: transparent; }\na { color: inherit; }\n\n.ambient {\n  position: fixed;\n  z-index: -1;\n  width: 24rem;\n  height: 24rem;\n  border: 1px solid rgba(97, 228, 197, 0.08);\n  border-radius: 50%;\n  pointer-events: none;\n}\n.ambient-a { top: 12rem; left: -18rem; }\n.ambient-b { right: -19rem; bottom: 3rem; border-color: rgba(168, 148, 255, 0.09); }\n\n.shell { width: min(1220px, calc(100% - 40px)); margin: 0 auto; padding: 28px 0 42px; }\n\n.topbar {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 20px;\n  margin-bottom: 30px;\n}\n\n.brand { display: inline-flex; align-items: center; gap: 12px; text-decoration: none; }\n.brand-mark {\n  display: inline-grid;\n  place-items: center;\n  width: 45px;\n  height: 45px;\n  border: 1px solid rgba(97, 228, 197, 0.42);\n  border-radius: 13px;\n  background: rgba(97, 228, 197, 0.1);\n  color: var(--mint);\n  font-size: 12px;\n  font-weight: 800;\n  letter-spacing: 0.08em;\n}\n.brand-name, .brand-note { display: block; }\n.brand-name { font-size: 17px; font-weight: 800; letter-spacing: 0.01em; }\n.brand-note { margin-top: 1px; color: var(--muted); font-size: 13px; }\n.data-status { display: inline-flex; align-items: center; gap: 8px; color: var(--muted-strong); font-size: 13px; }\n.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--mint); box-shadow: 0 0 0 4px rgba(97, 228, 197, 0.1); }\n\n.search-panel {\n  padding: 26px;\n  border: 1px solid var(--line);\n  border-radius: 22px;\n  background: linear-gradient(135deg, rgba(21, 35, 59, 0.94), rgba(12, 20, 36, 0.91));\n  box-shadow: var(--shadow);\n}\n.search-panel-heading { display: flex; align-items: end; justify-content: space-between; gap: 28px; margin-bottom: 22px; }\n.eyebrow { margin: 0 0 6px; color: var(--mint); font-size: 12px; font-weight: 800; letter-spacing: 0.18em; }\nh1, h2, h3, p { margin: 0; }\nh1 { font-size: clamp(24px, 3vw, 34px); line-height: 1.2; letter-spacing: -0.025em; }\n.search-help { max-width: 32rem; color: var(--muted); font-size: 15px; }\n.searchbar { display: grid; grid-template-columns: minmax(150px, 0.9fr) minmax(190px, 1.3fr) minmax(190px, 1.25fr) 120px; gap: 12px; align-items: end; }\n.field { display: grid; gap: 7px; color: var(--muted-strong); font-size: 14px; font-weight: 700; }\n.field input {\n  width: 100%;\n  height: 46px;\n  padding: 0 13px;\n  border: 1px solid var(--line-bright);\n  border-radius: 11px;\n  outline: 0;\n  background: rgba(6, 12, 24, 0.74);\n  color: var(--text);\n  transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;\n}\n.field input::placeholder { color: #6e809b; }\n.field input:focus { border-color: var(--mint); background: rgba(6, 12, 24, 0.94); box-shadow: 0 0 0 3px rgba(97, 228, 197, 0.14); }\n.search-button {\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  gap: 9px;\n  height: 46px;\n  border: 1px solid var(--mint);\n  border-radius: 11px;\n  background: var(--mint);\n  color: #08221e;\n  font-weight: 800;\n  cursor: pointer;\n  transition: transform 150ms ease, background 150ms ease;\n}\n.search-button:hover { background: #7be9d0; transform: translateY(-1px); }\n.button-arrow { font-size: 19px; line-height: 1; }\n.quick-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 17px; color: var(--muted); font-size: 13px; }\n.clear-button { padding: 0; border: 0; background: transparent; color: var(--mint); font-size: 13px; cursor: pointer; }\n.clear-button:hover { color: #a8f4e0; text-decoration: underline; }\n\n.state-card { display: flex; align-items: center; gap: 14px; margin-top: 26px; padding: 20px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); color: var(--muted-strong); }\n.state-card strong, .state-card span { display: block; }\n.state-card strong { color: var(--text); }\n.state-card span { margin-top: 3px; color: var(--muted); }\n.state-error { justify-content: space-between; border-color: rgba(255, 135, 125, 0.42); }\n.loading-orb { width: 14px; height: 14px; margin-left: 2px; border: 2px solid rgba(97, 228, 197, 0.28); border-top-color: var(--mint); border-radius: 50%; animation: spin 800ms linear infinite; }\n@keyframes spin { to { transform: rotate(360deg); } }\n\n.content-section { margin-top: 34px; }\n.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 14px; }\nh2 { font-size: 22px; line-height: 1.25; }\n.section-note { color: var(--muted); font-size: 14px; }\n.channel-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }\n.channel-card { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 13px; min-height: 104px; padding: 18px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); text-decoration: none; transition: border-color 160ms ease, background 160ms ease, transform 160ms ease; }\n.channel-card:hover { border-color: var(--mint-deep); background: var(--surface-soft); transform: translateY(-2px); }\n.channel-accent { display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(168, 148, 255, 0.13); color: var(--purple); font-size: 19px; }\n.channel-card-body { min-width: 0; }\n.channel-title, .channel-count { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.channel-title { font-size: 16px; }\n.channel-count { margin-top: 4px; color: var(--muted); font-size: 13px; }\n.channel-arrow { color: var(--mint); font-size: 20px; }\n\n.results-list { display: grid; gap: 10px; }\n.song-group { overflow: hidden; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }\n.song-summary { display: grid; grid-template-columns: 38px minmax(0, 1fr) minmax(110px, 220px) 24px; align-items: center; gap: 12px; padding: 15px 17px; cursor: pointer; list-style: none; }\n.song-summary::-webkit-details-marker, .channel-summary::-webkit-details-marker { display: none; }\n.song-group[open] > .song-summary { border-bottom: 1px solid var(--line); background: rgba(28, 45, 75, 0.46); }\n.song-icon { display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(255, 180, 92, 0.12); color: var(--orange); font-size: 19px; }\n.song-main { min-width: 0; }\n.song-title, .song-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.song-title { font-size: 17px; }\n.song-meta { margin-top: 3px; color: var(--muted); font-size: 13px; font-weight: 400; }\n.song-artist { overflow: hidden; color: var(--muted-strong); font-size: 14px; text-align: right; text-overflow: ellipsis; white-space: nowrap; }\n.song-chevron, .channel-chevron { color: var(--mint); font-size: 25px; line-height: 1; transition: transform 150ms ease; }\n.song-group[open] .song-chevron, .channel-block[open] .channel-chevron { transform: rotate(90deg); }\n.song-body { background: rgba(8, 14, 26, 0.35); }\n.channel-block { border-bottom: 1px solid rgba(36, 54, 83, 0.72); }\n.channel-block:last-child { border-bottom: 0; }\n.channel-summary { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 7px; padding: 11px 18px 11px 28px; color: var(--muted-strong); cursor: pointer; list-style: none; }\n.channel-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.channel-entry-count { color: var(--muted); font-size: 13px; }\n.entry-pager { padding: 0 18px 14px 58px; }\n.entry-list { display: grid; overflow: hidden; border: 1px solid rgba(56, 84, 119, 0.65); border-radius: 10px; }\n.entry-state { padding: 18px 12px; color: var(--muted); text-align: center; }\n.entry-row { display: grid; grid-template-columns: 80px minmax(0, 1fr) 104px; align-items: center; gap: 13px; min-height: 45px; padding: 9px 12px; border-bottom: 1px solid rgba(36, 54, 83, 0.72); background: rgba(15, 25, 44, 0.52); }\n.entry-row:last-child { border-bottom: 0; }\n.timestamp { color: var(--orange); font-variant-numeric: tabular-nums; font-weight: 800; text-decoration: none; }\n.timestamp:hover { color: #ffd08f; text-decoration: underline; }\n.entry-video { overflow: hidden; color: var(--muted-strong); text-overflow: ellipsis; white-space: nowrap; }\n.entry-date { color: var(--muted); font-size: 13px; text-align: right; }\n.entry-controls { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 10px; color: var(--muted); font-size: 13px; }\n.entry-button, .pager-button, .secondary-button { border: 1px solid var(--line-bright); border-radius: 9px; background: transparent; color: var(--mint); cursor: pointer; }\n.entry-button { padding: 5px 10px; font-size: 13px; }\n.entry-button:hover:not(:disabled), .pager-button:hover:not(:disabled), .secondary-button:hover { border-color: var(--mint); background: rgba(97, 228, 197, 0.08); }\nbutton:disabled { cursor: default; opacity: 0.4; }\n.empty-state { padding: 50px 20px; border: 1px dashed var(--line-bright); border-radius: 16px; text-align: center; color: var(--muted); }\n.empty-glyph { display: block; margin-bottom: 7px; color: var(--mint); font-size: 32px; }\n.empty-state h3 { color: var(--text); font-size: 18px; }\n.empty-state p { margin-top: 6px; }\n.pager { display: flex; align-items: center; justify-content: center; gap: 15px; margin-top: 18px; color: var(--muted); font-size: 14px; }\n.pager-button { padding: 8px 13px; }\n.secondary-button { padding: 8px 13px; }\n\n.footer { display: flex; justify-content: space-between; gap: 20px; margin-top: 40px; padding-top: 17px; border-top: 1px solid rgba(36, 54, 83, 0.62); color: var(--muted); font-size: 13px; }\n\n@media (max-width: 900px) {\n  .search-panel-heading { align-items: start; flex-direction: column; gap: 11px; }\n  .searchbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n  .search-button { grid-column: 2; }\n  .channel-grid { grid-template-columns: 1fr; }\n}\n\n@media (max-width: 620px) {\n  .shell { width: min(100% - 24px, 1220px); padding-top: 18px; }\n  .topbar { align-items: start; flex-direction: column; margin-bottom: 22px; }\n  .topbar-side { padding-left: 57px; }\n  .search-panel { padding: 19px; border-radius: 17px; }\n  .searchbar { grid-template-columns: 1fr; }\n  .search-button { grid-column: auto; }\n  .quick-row, .section-heading, .footer { align-items: start; flex-direction: column; }\n  .song-summary { grid-template-columns: 34px minmax(0, 1fr) 20px; gap: 9px; padding: 13px; }\n  .song-artist { grid-column: 2; grid-row: 2; text-align: left; }\n  .song-chevron { grid-column: 3; grid-row: 1 / span 2; }\n  .channel-summary { padding-left: 16px; }\n  .entry-pager { padding: 0 12px 12px 16px; }\n  .entry-row { grid-template-columns: 70px minmax(0, 1fr); gap: 8px; }\n  .entry-date { grid-column: 2; text-align: left; }\n  .footer { gap: 6px; }\n}\n";
const clientJs = "(() => {\n  const pageSize = 20;\n  const entryPageSize = 10;\n  const state = {\n    overview: null,\n    page: 1,\n    pageCount: 1,\n    total: 0,\n    matches: [],\n    requestId: 0,\n  };\n\n  const elements = {\n    content: document.querySelector(\"#content\"),\n    loading: document.querySelector(\"#loading-state\"),\n    error: document.querySelector(\"#error-state\"),\n    dataStatus: document.querySelector(\"#data-status\"),\n    statsSummary: document.querySelector(\"#stats-summary\"),\n    updatedAt: document.querySelector(\"#updated-at\"),\n    form: document.querySelector(\"#search-form\"),\n    channelInput: document.querySelector(\"#channel-input\"),\n    songInput: document.querySelector(\"#song-input\"),\n    artistInput: document.querySelector(\"#artist-input\"),\n    clearSearch: document.querySelector(\"#clear-search\"),\n    homeView: document.querySelector(\"#home-view\"),\n    resultsView: document.querySelector(\"#results-view\"),\n    channelGrid: document.querySelector(\"#channel-grid\"),\n    resultSummary: document.querySelector(\"#result-summary\"),\n    resultsList: document.querySelector(\"#results-list\"),\n    resultsEmpty: document.querySelector(\"#results-empty\"),\n    resultsEmptyTitle: document.querySelector(\"#results-empty h3\"),\n    resultsEmptyText: document.querySelector(\"#results-empty p\"),\n    resultsPager: document.querySelector(\"#results-pager\"),\n    resultsPrev: document.querySelector(\"#results-prev\"),\n    resultsNext: document.querySelector(\"#results-next\"),\n    resultsPageLabel: document.querySelector(\"#results-page-label\"),\n    retryButton: document.querySelector(\"#retry-button\"),\n  };\n\n  const text = (value) => String(value ?? \"\");\n  const formatNumber = (value) => new Intl.NumberFormat(\"zh-CN\").format(Number(value || 0));\n  const formatDate = (value) => {\n    if (!value) return \"日期未知\";\n    const date = new Date(value);\n    if (Number.isNaN(date.getTime())) return text(value).slice(0, 10);\n    return new Intl.DateTimeFormat(\"zh-CN\", { year: \"numeric\", month: \"2-digit\", day: \"2-digit\" }).format(date);\n  };\n\n  function createElement(tag, className, content) {\n    const element = document.createElement(tag);\n    if (className) element.className = className;\n    if (content !== undefined) element.textContent = text(content);\n    return element;\n  }\n\n  function getQueries() {\n    const params = new URLSearchParams(window.location.search);\n    return {\n      channel: params.get(\"channel\") || \"\",\n      song: params.get(\"song\") || \"\",\n      artist: params.get(\"artist\") || \"\",\n    };\n  }\n\n  function setQueries(queries, replace = false) {\n    const params = new URLSearchParams();\n    [\"channel\", \"song\", \"artist\"].forEach((key) => {\n      if (text(queries[key]).trim()) params.set(key, text(queries[key]).trim());\n    });\n    const url = params.toString() ? `${window.location.pathname}?${params}` : window.location.pathname;\n    window.history[replace ? \"replaceState\" : \"pushState\"]({}, \"\", url);\n  }\n\n  function renderSearchInputs(queries) {\n    elements.channelInput.value = queries.channel;\n    elements.songInput.value = queries.song;\n    elements.artistInput.value = queries.artist;\n    elements.clearSearch.hidden = !Object.values(queries).some((value) => value.trim());\n  }\n\n  function renderStats() {\n    const stats = state.overview?.stats || {};\n    elements.statsSummary.textContent = `共 ${formatNumber(stats.channels)} 个频道 · ${formatNumber(stats.videos)} 个视频 · ${formatNumber(stats.songs)} 首歌曲 · ${formatNumber(stats.entries)} 个时间点`;\n    elements.dataStatus.textContent = `${formatNumber(stats.entries)} 个时间点已就绪`;\n    const updatedAt = state.overview?.updatedAt ? new Date(state.overview.updatedAt) : null;\n    if (updatedAt && !Number.isNaN(updatedAt.getTime())) {\n      elements.updatedAt.textContent = `数据库更新于 ${new Intl.DateTimeFormat(\"zh-CN\", { year: \"numeric\", month: \"2-digit\", day: \"2-digit\" }).format(updatedAt)}`;\n    }\n  }\n\n  function renderChannels() {\n    elements.channelGrid.replaceChildren();\n    (state.overview?.channels || []).forEach((channel) => {\n      const link = createElement(\"a\", \"channel-card\");\n      const accent = createElement(\"span\", \"channel-accent\", \"◒\");\n      const body = createElement(\"span\", \"channel-card-body\");\n      body.append(createElement(\"strong\", \"channel-title\", channel.channel_title));\n      body.append(createElement(\"span\", \"channel-count\", `${formatNumber(channel.song_count)} 首歌曲 · ${formatNumber(channel.entry_count)} 个时间点`));\n      const arrow = createElement(\"span\", \"channel-arrow\", \"↗\");\n      link.append(accent, body, arrow);\n      link.href = `?channel=${encodeURIComponent(channel.channel_title)}`;\n      elements.channelGrid.append(link);\n    });\n  }\n\n  function makeEntryPager(groupKey, channel, artistQuery = \"\") {\n    const wrapper = createElement(\"div\", \"entry-pager\");\n    const list = createElement(\"div\", \"entry-list\");\n    const controls = createElement(\"div\", \"entry-controls\");\n    const previous = createElement(\"button\", \"entry-button\", \"上一页\");\n    const label = createElement(\"span\", \"entry-page-label\");\n    const next = createElement(\"button\", \"entry-button\", \"下一页\");\n    let currentPage = 1;\n    let pageCount = Math.max(1, Math.ceil(Number(channel.entryCount || 0) / entryPageSize));\n    let entries = [];\n    let loading = false;\n    let loaded = false;\n    let requestId = 0;\n\n    const render = (message = \"\") => {\n      list.replaceChildren();\n      if (message) {\n        list.append(createElement(\"div\", \"entry-state\", message));\n      } else if (entries.length === 0) {\n        list.append(createElement(\"div\", \"entry-state\", \"暂无时间点\"));\n      } else {\n        entries.forEach((entry) => {\n          const row = createElement(\"div\", \"entry-row\");\n          const time = createElement(\"a\", \"timestamp\", entry.timestampText || \"打开\");\n          time.href = entry.jumpUrl;\n          time.target = \"_blank\";\n          time.rel = \"noopener noreferrer\";\n          const video = createElement(\"span\", \"entry-video\", entry.videoTitle || \"未命名视频\");\n          const date = createElement(\"time\", \"entry-date\", formatDate(entry.publishedAt));\n          row.append(time, video, date);\n          list.append(row);\n        });\n      }\n      controls.hidden = pageCount <= 1;\n      previous.disabled = loading || currentPage <= 1;\n      next.disabled = loading || currentPage >= pageCount;\n      label.textContent = `第 ${currentPage} / ${pageCount} 页`;\n    };\n\n    const loadPage = async (page) => {\n      const currentRequest = ++requestId;\n      loading = true;\n      currentPage = page;\n      render(\"正在载入时间点…\");\n      const params = new URLSearchParams({\n        groupKey,\n        channelId: channel.id,\n        page: String(page),\n        pageSize: String(entryPageSize),\n      });\n      if (artistQuery.trim()) params.set(\"artist\", artistQuery.trim());\n      try {\n        const payload = await requestJson(`/api/entries?${params}`);\n        if (currentRequest !== requestId) return;\n        entries = Array.isArray(payload.entries) ? payload.entries : [];\n        currentPage = Math.max(1, Number(payload.page || page));\n        pageCount = Math.max(1, Number(payload.pageCount || 1));\n        loaded = true;\n        loading = false;\n        render();\n      } catch (error) {\n        if (currentRequest !== requestId) return;\n        console.error(error);\n        loading = false;\n        render(\"时间点载入失败，请稍后重试。\");\n      }\n    };\n\n    const loadIfNeeded = () => {\n      if (!loaded && !loading && Number(channel.entryCount || 0) > 0) {\n        void loadPage(currentPage);\n      }\n    };\n\n    previous.addEventListener(\"click\", () => {\n      if (!loading && currentPage > 1) {\n        void loadPage(currentPage - 1);\n      }\n    });\n    next.addEventListener(\"click\", () => {\n      if (!loading && currentPage < pageCount) {\n        void loadPage(currentPage + 1);\n      }\n    });\n    controls.append(previous, label, next);\n    wrapper.append(list, controls);\n    render();\n    return { element: wrapper, loadIfNeeded };\n  }\n\n  function renderGroup(group, shouldOpen, artistQuery = \"\") {\n    const details = createElement(\"details\", \"song-group\");\n    details.open = shouldOpen;\n    const summary = createElement(\"summary\", \"song-summary\");\n    const icon = createElement(\"span\", \"song-icon\", \"♪\");\n    const main = createElement(\"span\", \"song-main\");\n    main.append(createElement(\"strong\", \"song-title\", group.songTitle));\n    main.append(createElement(\"span\", \"song-meta\", `${formatNumber(group.entryCount)} 个时间点 · ${formatNumber(group.channelCount)} 个频道`));\n    const artist = createElement(\"span\", \"song-artist\", group.artist || \"作者未知\");\n    const chevron = createElement(\"span\", \"song-chevron\", \"›\");\n    summary.append(icon, main, artist, chevron);\n\n    const body = createElement(\"div\", \"song-body\");\n    (group.channels || []).forEach((channel) => {\n      const channelBlock = createElement(\"details\", \"channel-block\");\n      channelBlock.open = group.channels.length === 1;\n      const channelSummary = createElement(\"summary\", \"channel-summary\");\n      channelSummary.append(createElement(\"span\", \"channel-chevron\", \"›\"));\n      channelSummary.append(createElement(\"strong\", \"channel-name\", channel.title));\n      channelSummary.append(createElement(\"span\", \"channel-entry-count\", `${formatNumber(channel.entryCount)} 个时间点`));\n      const pager = makeEntryPager(group.id, channel, artistQuery);\n      channelBlock.append(channelSummary, pager.element);\n      channelBlock.addEventListener(\"toggle\", () => {\n        if (channelBlock.open) pager.loadIfNeeded();\n      });\n      if (channelBlock.open) pager.loadIfNeeded();\n      body.append(channelBlock);\n    });\n    details.append(summary, body);\n    return details;\n  }\n\n  function setEmptyState(title, message, hidden) {\n    elements.resultsEmptyTitle.textContent = title;\n    elements.resultsEmptyText.textContent = message;\n    elements.resultsEmpty.hidden = hidden;\n  }\n\n  function renderResults() {\n    const queries = getQueries();\n    elements.resultsList.replaceChildren();\n    state.matches.forEach((group) => elements.resultsList.append(renderGroup(group, state.total === 1, queries.artist)));\n    elements.resultSummary.textContent = state.total ? `${formatNumber(state.total)} 首匹配歌曲` : \"没有匹配歌曲\";\n    setEmptyState(\"没有找到匹配条目\", \"可以换一种歌曲或作者写法，或者先清除一个筛选条件。\", state.total !== 0);\n    elements.resultsPager.hidden = state.total === 0 || state.pageCount <= 1;\n    elements.resultsPrev.disabled = state.page <= 1;\n    elements.resultsNext.disabled = state.page >= state.pageCount;\n    elements.resultsPageLabel.textContent = `第 ${state.page} / ${state.pageCount} 页`;\n  }\n\n  async function requestJson(url) {\n    const response = await fetch(url, { cache: \"no-store\", headers: { Accept: \"application/json\" } });\n    const payload = await response.json().catch(() => ({}));\n    if (!response.ok) throw new Error(payload.message || `请求失败（${response.status}）`);\n    return payload;\n  }\n\n  async function refreshResults(queries) {\n    const requestId = ++state.requestId;\n    const params = new URLSearchParams();\n    Object.entries(queries).forEach(([key, value]) => {\n      if (value.trim()) params.set(key, value.trim());\n    });\n    params.set(\"page\", String(state.page));\n    params.set(\"pageSize\", String(pageSize));\n    elements.resultSummary.textContent = \"正在查询数据库…\";\n    elements.resultsList.replaceChildren();\n    setEmptyState(\"正在查询\", \"正在从实时数据库读取歌曲和时间点。\", false);\n    elements.resultsPager.hidden = true;\n    try {\n      const payload = await requestJson(`/api/search?${params}`);\n      if (requestId !== state.requestId) return;\n      state.matches = Array.isArray(payload.groups) ? payload.groups : [];\n      state.page = Math.max(1, Number(payload.page || state.page));\n      state.pageCount = Math.max(1, Number(payload.pageCount || 1));\n      state.total = Math.max(0, Number(payload.total || 0));\n      renderResults();\n    } catch (error) {\n      if (requestId !== state.requestId) return;\n      console.error(error);\n      state.matches = [];\n      state.total = 0;\n      state.pageCount = 1;\n      elements.resultSummary.textContent = \"查询失败\";\n      setEmptyState(\"数据库暂时无法查询\", \"请稍后重试；如果问题持续存在，请刷新页面。\", false);\n    }\n  }\n\n  async function render() {\n    const queries = getQueries();\n    renderSearchInputs(queries);\n    const hasSearch = Object.values(queries).some((value) => value.trim());\n    elements.homeView.hidden = hasSearch;\n    elements.resultsView.hidden = !hasSearch;\n    if (hasSearch) await refreshResults(queries);\n  }\n\n  function showLoadedState() {\n    elements.loading.hidden = true;\n    elements.error.hidden = true;\n    elements.content.hidden = false;\n    renderStats();\n    renderChannels();\n  }\n\n  async function loadOverview() {\n    elements.loading.hidden = false;\n    elements.error.hidden = true;\n    elements.content.hidden = true;\n    elements.dataStatus.textContent = \"载入数据库中\";\n    try {\n      state.overview = await requestJson(\"/api/overview\");\n      showLoadedState();\n      await render();\n    } catch (error) {\n      console.error(error);\n      elements.loading.hidden = true;\n      elements.error.hidden = false;\n      elements.content.hidden = true;\n      elements.dataStatus.textContent = \"载入失败\";\n    }\n  }\n\n  elements.form.addEventListener(\"submit\", (event) => {\n    event.preventDefault();\n    state.page = 1;\n    setQueries({\n      channel: elements.channelInput.value,\n      song: elements.songInput.value,\n      artist: elements.artistInput.value,\n    });\n    void render();\n  });\n  elements.clearSearch.addEventListener(\"click\", () => {\n    state.page = 1;\n    setQueries({ channel: \"\", song: \"\", artist: \"\" });\n    void render();\n    elements.channelInput.focus();\n  });\n  elements.resultsPrev.addEventListener(\"click\", () => {\n    if (state.page > 1) {\n      state.page -= 1;\n      void refreshResults(getQueries());\n      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: \"smooth\" });\n    }\n  });\n  elements.resultsNext.addEventListener(\"click\", () => {\n    if (state.page < state.pageCount) {\n      state.page += 1;\n      void refreshResults(getQueries());\n      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: \"smooth\" });\n    }\n  });\n  window.addEventListener(\"popstate\", () => {\n    state.page = 1;\n    void render();\n  });\n  elements.retryButton.addEventListener(\"click\", () => void loadOverview());\n\n  if (typeof document.modelContext?.registerTool === \"function\") {\n    const lifecycle = new AbortController();\n    Promise.resolve(document.modelContext.registerTool({\n      name: \"search_vtuber_songs\",\n      title: \"Search VTuber songs\",\n      description: \"Search the live VTuber Song Finder database by channel, song title, or artist and update the page to show matching songs.\",\n      inputSchema: {\n        type: \"object\",\n        properties: {\n          channel: { type: \"string\", description: \"Optional channel name or channel ID.\" },\n          song: { type: \"string\", description: \"Optional song title or keyword.\" },\n          artist: { type: \"string\", description: \"Optional artist or author name.\" },\n        },\n        additionalProperties: false,\n      },\n      annotations: { readOnlyHint: true, untrustedContentHint: true },\n      async execute(input) {\n        if (!state.overview) return { ok: false, message: \"The database is still loading.\" };\n        const value = input && typeof input === \"object\" ? input : {};\n        const queries = {\n          channel: text(value.channel),\n          song: text(value.song),\n          artist: text(value.artist),\n        };\n        state.page = 1;\n        setQueries(queries);\n        await render();\n        return {\n          ok: true,\n          matchCount: state.total,\n          page: state.page,\n          query: queries,\n          songs: state.matches.slice(0, 5).map((group) => ({ title: group.songTitle, artist: group.artist, entryCount: group.entryCount })),\n        };\n      },\n    }, { signal: lifecycle.signal })).catch((error) => console.warn(\"WebMCP registration failed\", error));\n    window.addEventListener(\"pagehide\", () => lifecycle.abort(), { once: true });\n  }\n\n  void loadOverview();\n})();\n";
const faviconSvg = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\">\n  <rect width=\"64\" height=\"64\" rx=\"16\" fill=\"#0b1324\"/>\n  <path d=\"M14 18h9l9 25 9-25h9L36 48h-8L14 18Z\" fill=\"#61e4c5\"/>\n  <circle cx=\"50\" cy=\"18\" r=\"5\" fill=\"#ffb45c\"/>\n</svg>\n";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

// The suffix keeps the versioned staging schema separate from the original
// shared staging tables.  Every row also carries its snapshot version so two
// imports can safely coexist while one of them is being superseded.
const SNAPSHOT_STAGING_TABLES = Object.freeze({
  channels: "snapshot_channels_v2",
  videos: "snapshot_videos_v2",
  song_groups: "snapshot_song_groups_v2",
  songs: "snapshot_songs_v2",
  song_entries: "snapshot_song_entries_v2",
});
const SEED_TABLES = new Set(Object.keys(SNAPSHOT_STAGING_TABLES));

function snapshotExpectedTables(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("snapshot tables must be an object");
  }
  const expected = {};
  for (const table of SEED_TABLES) {
    const count = value[table];
    if (!Number.isSafeInteger(count) || count < 0) {
      throw new Error(`invalid row count for ${table}`);
    }
    expected[table] = count;
  }
  return expected;
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: JSON_HEADERS,
  });
}

function textResponse(value, contentType, cacheControl = "no-store") {
  return new Response(value, {
    headers: {
      "content-type": contentType,
      "cache-control": cacheControl,
    },
  });
}

function requestText(value, maxLength = 120) {
  return String(value ?? "").trim().slice(0, maxLength);
}

function foldSearchText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replaceAll("ß", "ss")
    .replaceAll("ς", "σ");
}

function likeValue(value) {
  return `%${String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("%", "\\%")
    .replaceAll("_", "\\_")}%`;
}

function normalizeSearchText(value) {
  return foldSearchText(
    String(value ?? "")
      .replace(/\u3000/g, " ")
      .replace(/\s+/gu, " ")
      .trim(),
  );
}

function compactKey(value) {
  return normalizeSearchText(value).replace(/[^\p{L}\p{N}]+/gu, "");
}

function isShortAsciiKey(value) {
  return value.length <= 4 && /^[A-Za-z0-9]+$/u.test(value);
}

function compareText(left, right) {
  // Python's ``casefold`` ordering is a code-point ordering, while
  // ``localeCompare`` varies with the Worker locale.  Keep the comparison
  // deterministic across local Node tests and Cloudflare Workers.
  const fold = foldSearchText;
  const a = fold(left);
  const b = fold(right);
  return a < b ? -1 : a > b ? 1 : 0;
}

function levenshteinAtMost(left, right, maxDistance = 2) {
  if (Math.abs(left.length - right.length) > maxDistance) return maxDistance + 1;
  if (left.length > right.length) return levenshteinAtMost(right, left, maxDistance);
  let previous = Array.from({ length: left.length + 1 }, (_, index) => index);
  for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
    const current = [rightIndex];
    let rowMin = current[0];
    for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
      const value = Math.min(
        current[leftIndex - 1] + 1,
        previous[leftIndex] + 1,
        previous[leftIndex - 1] + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      );
      current.push(value);
      rowMin = Math.min(rowMin, value);
    }
    if (rowMin > maxDistance) return maxDistance + 1;
    previous = current;
  }
  return previous[previous.length - 1];
}

function similarSongKey(left, right) {
  if (left === right) return true;
  if (Math.min(left.length, right.length) < 6) return false;
  const distance = levenshteinAtMost(left, right, 2);
  return distance <= 1 || (distance <= 2 && Math.min(left.length, right.length) >= 9);
}

function titleKeys(row) {
  const keys = new Set(compactTitleAliases(row));
  const titleKey = compactKey(row.song_title);
  if (titleKey) keys.add(titleKey);
  return [...keys];
}

function normalizedTitleKeys(row) {
  const searchText = String(row.title_search ?? "");
  try {
    const payload = JSON.parse(searchText);
    if (Array.isArray(payload?.normalized)) {
      return payload.normalized.map((value) => normalizeSearchText(value)).filter(Boolean);
    }
  } catch (_) {
    const aliases = searchText.match(/\^([^\^]+)\^/gu) || [];
    if (aliases.length > 0) return aliases.map((token) => token.slice(1, -1));
  }
  const fallback = normalizeSearchText(row.song_title);
  return fallback ? [fallback] : [];
}

function compactTitleAliases(row) {
  const searchText = String(row.title_search ?? "");
  try {
    const payload = JSON.parse(searchText);
    if (Array.isArray(payload?.compact)) {
      return payload.compact.map((value) => compactKey(value)).filter(Boolean);
    }
  } catch (_) {
    const aliases = searchText.match(/~([^~]+)~/gu) || [];
    if (aliases.length > 0) return aliases.map((token) => token.slice(1, -1));
  }
  return [];
}

function realTitleText(row) {
  return normalizedTitleKeys(row).join(" ");
}

function songMatches(row, search) {
  if (!search.song) return true;
  const queryKey = search.songKey;
  if (!queryKey) return normalizedTitleKeys(row).some((title) => title.includes(search.song));
  if (isShortAsciiKey(queryKey)) {
    return titleKeys(row).some((titleKey) => (
      titleKey === queryKey
      || titleKey.startsWith(queryKey)
      || similarSongKey(titleKey, queryKey)
    ));
  }
  if (normalizedTitleKeys(row).some((title) => title.includes(search.song))) return true;
  return titleKeys(row).some((titleKey) => (
    titleKey === queryKey
    || titleKey.startsWith(queryKey)
    || titleKey.includes(queryKey)
    || queryKey.includes(titleKey)
    || similarSongKey(titleKey, queryKey)
  ));
}

function songRelevance(row, search) {
  if (!search.song) return 5;
  const queryKey = search.songKey;
  if (!queryKey) return normalizedSearchInRow(row, search.song) ? 4 : 5;
  const keys = titleKeys(row);
  if (keys.includes(queryKey)) return 0;
  if (keys.some((key) => key.startsWith(queryKey))) return 1;
  if (keys.some((key) => key.includes(queryKey))) return 2;
  if (keys.some((key) => similarSongKey(key, queryKey))) return 3;
  return normalizedSearchInRow(row, search.song) ? 4 : 5;
}

function normalizedSearchInRow(row, query) {
  return realTitleText(row).includes(query);
}

function artistKeysFromText(value) {
  return String(value ?? "")
    .split(/\s*(?:\/|／|\||｜|&|＆|×|\+|w\s*\/|feat\.?|ft\.?|with|and)\s*/iu)
    .map((part) => compactKey(part))
    .filter(Boolean);
}

function artistMatches(row, search, scoped = false) {
  if (!search.artist) return true;
  const source = scoped
    ? row.scope_artist
    : row.artist_search || row.artist;
  const keys = [...new Set(
    String(source ?? "")
      .split(/\s+/u)
      .flatMap((part) => artistKeysFromText(part)),
  )];
  if (keys.includes(search.artist)) return true;
  if (isShortAsciiKey(search.artist)) return false;
  return keys.some((key) => search.artist.includes(key) || key.includes(search.artist));
}

function toCount(value) {
  return Number(value || 0);
}

async function queryOverview(env) {
  const [channelsCount, videosCount, songsCount, entriesCount, channelsResult, updatedResult] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS count FROM channels"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM videos"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM songs"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM song_entries"),
    env.DB.prepare(`
      SELECT
        c.channel_id,
        c.channel_title,
        COALESCE(video_counts.video_count, 0) AS video_count,
        COALESCE(song_counts.song_count, 0) AS song_count,
        COALESCE(entry_counts.entry_count, 0) AS entry_count
      FROM channels c
      LEFT JOIN (
        SELECT channel_id, COUNT(*) AS video_count
        FROM videos
        GROUP BY channel_id
      ) video_counts ON video_counts.channel_id = c.channel_id
      LEFT JOIN (
        SELECT channel_id, COUNT(*) AS song_count
        FROM songs
        GROUP BY channel_id
      ) song_counts ON song_counts.channel_id = c.channel_id
      LEFT JOIN (
        SELECT v.channel_id, COUNT(e.id) AS entry_count
        FROM song_entries e
        JOIN videos v ON v.video_id = e.video_id
        GROUP BY v.channel_id
      ) entry_counts ON entry_counts.channel_id = c.channel_id
      ORDER BY c.channel_title
    `),
    env.DB.prepare("SELECT MAX(indexed_at) AS updated_at FROM videos"),
  ]);

  return {
    stats: {
      channels: toCount(channelsCount.results?.[0]?.count),
      videos: toCount(videosCount.results?.[0]?.count),
      songs: toCount(songsCount.results?.[0]?.count),
      entries: toCount(entriesCount.results?.[0]?.count),
    },
    channels: (channelsResult.results || []).map((row) => ({
      channel_id: row.channel_id,
      channel_title: row.channel_title,
      video_count: toCount(row.video_count),
      song_count: toCount(row.song_count),
      entry_count: toCount(row.entry_count),
    })),
    updatedAt: updatedResult.results?.[0]?.updated_at || null,
  };
}

function buildSearch(query) {
  const song = normalizeSearchText(requestText(query.get("song")));
  const songKey = compactKey(song);
  const artistInput = requestText(query.get("artist"));
  const artist = compactKey(artistInput);
  const channel = requestText(query.get("channel"));
  const where = [];
  const params = [];

  if (artistInput && !artist) {
    where.push("0 = 1");
  }

  return {
    song,
    songKey,
    artist,
    artistInput,
    channel,
    whereSql: where.length ? `WHERE ${where.join(" AND ")}` : "",
    params,
  };
}

async function searchGroups(env, url) {
  const search = buildSearch(url.searchParams);
  const rawPage = Number.parseInt(url.searchParams.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(url.searchParams.get("pageSize") || "20", 10);
  const pageSize = Math.min(50, Math.max(1, Number.isFinite(rawPageSize) ? rawPageSize : 20));

  const aggregate = Boolean(search.channel || search.artist);
  const groupRows = aggregate
    ? (await env.DB.prepare(`
        SELECT
          g.group_key,
          g.song_title,
          g.artist,
          g.title_search,
          g.artist_search,
          scope_c.channel_id,
          scope_c.channel_title,
          scope_s.id AS song_id,
          scope_s.artist AS scope_artist,
          COUNT(scope_e.id) AS entry_count
        FROM song_groups g
        JOIN song_entries scope_e ON scope_e.group_key = g.group_key
        JOIN songs scope_s ON scope_s.id = scope_e.song_id
        JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
        JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
        ${search.whereSql}
        ${search.channel ? `${search.whereSql ? "AND" : "WHERE"} (scope_c.channel_title LIKE ? ESCAPE '\\' OR scope_c.channel_id = ?)` : ""}
        GROUP BY g.group_key, g.song_title, g.artist, g.title_search, g.artist_search,
                 scope_c.channel_id, scope_c.channel_title, scope_s.id, scope_s.artist
      `).bind(
        ...search.params,
        ...(search.channel ? [likeValue(search.channel), search.channel] : []),
      ).all()).results || []
    : (await env.DB.prepare(`
      SELECT g.group_key, g.song_title, g.artist, g.title_search,
               g.entry_count, g.channel_count
        FROM song_groups g
        ${search.whereSql}
      `).bind(...search.params).all()).results || [];

  const groupsByKey = new Map();
  for (const row of groupRows) {
    if (!songMatches(row, search)) continue;
    // Aggregate rows are split by song so author filtering can happen in JS
    // against the real D1 ``songs.artist`` column.  This keeps unknown-author
    // entries from leaking into a matched channel and avoids the nonexistent
    // per-song artist-search column.
    if (aggregate && search.artist && !artistMatches(row, search, true)) continue;
    const scopedKey = search.channel
      ? `${row.group_key}\u0000${row.channel_id || ""}`
      : row.group_key;
    let group = groupsByKey.get(scopedKey);
    if (!group) {
      group = {
        id: row.group_key,
        songTitle: row.song_title,
        artist: row.artist || "",
        channelCount: 0,
        entryCount: 0,
        channels: [],
        scopedChannelId: search.channel ? row.channel_id || "" : "",
        channelTitle: search.channel ? row.channel_title || "" : "",
        searchRow: row,
        scopedChannels: new Map(),
      };
      groupsByKey.set(scopedKey, group);
    }
    group.entryCount += toCount(row.entry_count);
    const channelKey = row.channel_id || "";
    if (aggregate) {
      const scopedChannel = group.scopedChannels.get(channelKey) || {
        id: channelKey,
        title: row.channel_title || "",
        entryCount: 0,
      };
      scopedChannel.entryCount += toCount(row.entry_count);
      group.scopedChannels.set(channelKey, scopedChannel);
    }
  }
  const groups = [...groupsByKey.values()];
  for (const group of groups) {
    group.channelCount = aggregate
      ? group.scopedChannels.size
      : toCount(group.searchRow.channel_count);
    delete group.scopedChannels;
  }

  groups.sort((left, right) => {
    if (search.song) {
      return songRelevance(left.searchRow, search)
        - songRelevance(right.searchRow, search)
        || compareText(left.songTitle, right.songTitle)
        || compareText(left.artist, right.artist)
        || compareText(left.channelTitle, right.channelTitle)
        || compareText(left.id, right.id);
    }
    if (search.artist) {
      return compareText(left.songTitle, right.songTitle)
        || compareText(left.artist, right.artist)
        || compareText(left.channelTitle, right.channelTitle)
        || (right.entryCount - left.entryCount)
        || compareText(left.id, right.id);
    }
    return (right.entryCount - left.entryCount)
      || compareText(left.channelTitle, right.channelTitle)
      || compareText(left.songTitle, right.songTitle)
      || compareText(left.artist, right.artist)
      || compareText(left.id, right.id);
  });

  const total = groups.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(rawPage) ? rawPage : 1));
  const offset = (page - 1) * pageSize;
  const pagedGroups = groups.slice(offset, offset + pageSize);

  if (pagedGroups.length === 0) {
    return { groups: pagedGroups, total, page, pageCount, pageSize };
  }

  const groupKeys = pagedGroups.map((group) => group.id);
  const placeholders = groupKeys.map(() => "?").join(",");
  const channelWhere = [`scope_e.group_key IN (${placeholders})`];
  const channelParams = [...groupKeys];
  if (search.channel) {
    channelWhere.push("(scope_c.channel_title LIKE ? ESCAPE '\\' OR scope_c.channel_id = ?)");
    channelParams.push(likeValue(search.channel), search.channel);
  }
  const channelRows = (await env.DB.prepare(`
    SELECT
      scope_e.group_key,
      scope_c.channel_id,
      scope_c.channel_title,
      scope_s.id AS song_id,
      scope_s.artist AS scope_artist,
      COUNT(scope_e.id) AS entry_count
    FROM song_entries scope_e
    JOIN songs scope_s ON scope_s.id = scope_e.song_id
    JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
    JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
    WHERE ${channelWhere.join(" AND ")}
    GROUP BY scope_e.group_key, scope_c.channel_id, scope_c.channel_title,
             scope_s.id, scope_s.artist
    ORDER BY scope_e.group_key, scope_c.channel_title
  `).bind(...channelParams).all()).results || [];

  const groupsByScopedKey = new Map(
    pagedGroups.map((group) => [
      `${group.id}\u0000${group.scopedChannelId}`,
      group,
    ]),
  );
  for (const row of channelRows) {
    if (search.artist && !artistMatches(row, search, true)) continue;
    const group = groupsByScopedKey.get(
      `${row.group_key}\u0000${search.channel ? row.channel_id : ""}`,
    );
    if (!group) continue;
    const existing = group.channels.find((channel) => channel.id === row.channel_id);
    if (existing) {
      existing.entryCount += toCount(row.entry_count);
    } else {
      group.channels.push({
        id: row.channel_id,
        title: row.channel_title,
        entryCount: toCount(row.entry_count),
        entries: [],
      });
    }
  }

  for (const group of pagedGroups) {
    group.channels.sort((left, right) => right.entryCount - left.entryCount || compareText(left.title, right.title));
    if (aggregate) {
      group.channelCount = group.channels.length;
      group.entryCount = group.channels.reduce((sum, channel) => sum + channel.entryCount, 0);
    }
    delete group.scopedChannelId;
    delete group.channelTitle;
    delete group.searchRow;
  }

  return { groups: pagedGroups, total, page, pageCount, pageSize };
}

async function searchEntries(env, url) {
  const groupKey = requestText(url.searchParams.get("groupKey"), 240);
  const channelId = requestText(url.searchParams.get("channelId"), 120);
  const artistInput = requestText(url.searchParams.get("artist"));
  const artist = compactKey(artistInput);
  const rawPage = Number.parseInt(url.searchParams.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(url.searchParams.get("pageSize") || "10", 10);
  const pageSize = Math.min(50, Math.max(1, Number.isFinite(rawPageSize) ? rawPageSize : 10));

  if (!groupKey) return { ok: false, message: "缺少歌曲分组。" };

  let songIds = null;
  if (artistInput && !artist) {
    songIds = [];
  } else if (artist) {
    // D1's ``songs`` table contains the source artist text but deliberately
    // has no derived per-song artist-search column.  Fetch only the small song metadata set,
    // filter it with the shared JS matcher, then use the accepted IDs for the
    // count and paged entry query.
    const songRows = (await env.DB.prepare(
      "SELECT id, artist FROM songs WHERE group_key = ?",
    ).bind(groupKey).all()).results || [];
    songIds = songRows
      .filter((row) => artistMatches({ scope_artist: row.artist }, { artist }, true))
      .map((row) => Number(row.id))
      .filter((id) => Number.isSafeInteger(id));
  }

  const where = ["e.group_key = ?"];
  const params = [groupKey];
  if (channelId) {
    where.push("c.channel_id = ?");
    params.push(channelId);
  }
  if (songIds !== null) {
    if (songIds.length === 0) {
      return {
        ok: true,
        groupKey,
        channelId,
        total: 0,
        page: 1,
        pageCount: 1,
        pageSize,
        entries: [],
      };
    }
    // Keep this to one D1 bind even when a merged group has many per-channel
    // song rows; D1 rejects requests that exceed its bind-variable limit.
    where.push("e.song_id IN (SELECT value FROM json_each(?))");
    params.push(JSON.stringify(songIds));
  }
  const whereSql = where.join(" AND ");
  const countResult = await env.DB.prepare(`
    SELECT COUNT(*) AS count
    FROM song_entries e
    JOIN videos v ON v.video_id = e.video_id
    JOIN channels c ON c.channel_id = v.channel_id
    WHERE ${whereSql}
  `).bind(...params).first();
  const total = toCount(countResult?.count);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(rawPage) ? rawPage : 1));
  const offset = (page - 1) * pageSize;
  const entries = total === 0
    ? []
    : (await env.DB.prepare(`
        SELECT
          v.title AS video_title,
          v.published_at,
          e.timestamp_text,
          e.jump_url,
          e.seconds
        FROM song_entries e
        JOIN videos v ON v.video_id = e.video_id
        JOIN channels c ON c.channel_id = v.channel_id
        WHERE ${whereSql}
        ORDER BY v.published_at DESC, e.seconds ASC, e.id ASC
        LIMIT ? OFFSET ?
      `).bind(...params, pageSize, offset).all()).results || [];

  return {
    ok: true,
    groupKey,
    channelId,
    total,
    page,
    pageCount,
    pageSize,
    entries: entries.map((row) => ({
      videoTitle: row.video_title || "",
      publishedAt: row.published_at,
      timestampText: row.timestamp_text || "",
      jumpUrl: row.jump_url || "",
    })),
  };
}

function requireSeedToken(request, env) {
  const configured = String(env.SEED_TOKEN || "");
  const supplied = request.headers.get("x-seed-token") || "";
  return Boolean(configured) && supplied === configured;
}

function required(row, key) {
  return row[key] !== undefined && row[key] !== null;
}

function seedStatements(table, rows, env, version, targetTable = SNAPSHOT_STAGING_TABLES[table]) {
  const statements = [];
  for (const row of rows) {
    if (table === "channels" && required(row, "channel_id") && required(row, "channel_title")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, channel_id, channel_title)
        SELECT ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, channel_id) DO UPDATE SET
          channel_title = excluded.channel_title
      `).bind(version, row.channel_id, row.channel_title, version));
    } else if (table === "videos" && required(row, "video_id") && required(row, "channel_id") && required(row, "title") && required(row, "url") && required(row, "indexed_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, video_id, channel_id, title, published_at, url, indexed_at)
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, video_id) DO UPDATE SET
          channel_id = excluded.channel_id,
          title = excluded.title,
          published_at = excluded.published_at,
          url = excluded.url,
          indexed_at = excluded.indexed_at
      `).bind(version, row.video_id, row.channel_id, row.title, row.published_at ?? null, row.url, row.indexed_at, version));
    } else if (table === "song_groups" && required(row, "group_key") && required(row, "song_title") && required(row, "title_search") && required(row, "artist_search") && required(row, "entry_count") && required(row, "channel_count")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, group_key) DO UPDATE SET
          song_title = excluded.song_title,
          artist = excluded.artist,
          title_search = excluded.title_search,
          artist_search = excluded.artist_search,
          entry_count = excluded.entry_count,
          channel_count = excluded.channel_count
      `).bind(version, row.group_key, row.song_title, row.artist ?? "", row.title_search, row.artist_search, row.entry_count, row.channel_count, version));
    } else if (table === "songs" && required(row, "id") && required(row, "channel_id") && required(row, "canonical_song_title") && required(row, "normalized_song_title") && required(row, "group_key") && required(row, "created_at") && required(row, "updated_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, id) DO UPDATE SET
          channel_id = excluded.channel_id,
          canonical_song_title = excluded.canonical_song_title,
          normalized_song_title = excluded.normalized_song_title,
          artist = excluded.artist,
          group_key = excluded.group_key,
          created_at = excluded.created_at,
          updated_at = excluded.updated_at
      `).bind(version, row.id, row.channel_id, row.canonical_song_title, row.normalized_song_title, row.artist ?? "", row.group_key, row.created_at, row.updated_at, version));
    } else if (table === "song_entries" && required(row, "id") && required(row, "song_id") && required(row, "group_key") && required(row, "video_id") && required(row, "timestamp_text") && required(row, "seconds") && required(row, "raw_song_title") && required(row, "normalized_song_title") && required(row, "source_comment") && required(row, "jump_url") && required(row, "created_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, id) DO UPDATE SET
          song_id = excluded.song_id,
          group_key = excluded.group_key,
          video_id = excluded.video_id,
          timestamp_text = excluded.timestamp_text,
          seconds = excluded.seconds,
          raw_song_title = excluded.raw_song_title,
          normalized_song_title = excluded.normalized_song_title,
          source_comment = excluded.source_comment,
          jump_url = excluded.jump_url,
          created_at = excluded.created_at
      `).bind(version, row.id, row.song_id, row.group_key, row.video_id, row.timestamp_text, row.seconds, row.raw_song_title, row.normalized_song_title, row.source_comment, row.jump_url, row.created_at, version));
    } else {
      throw new Error(`invalid ${table} row`);
    }
  }
  return statements;
}

function snapshotSchemaStatements(env) {
  return [
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS dataset_meta (
        id INTEGER PRIMARY KEY DEFAULT 1,
        version TEXT NOT NULL,
        status TEXT NOT NULL,
        expected_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_channels_v2 (
        snapshot_version TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        channel_title TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, channel_id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_videos_v2 (
        snapshot_version TEXT NOT NULL,
        video_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT,
        url TEXT NOT NULL,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, video_id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_groups_v2 (
        snapshot_version TEXT NOT NULL,
        group_key TEXT NOT NULL,
        song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        title_search TEXT NOT NULL,
        artist_search TEXT NOT NULL,
        entry_count INTEGER NOT NULL,
        channel_count INTEGER NOT NULL,
        PRIMARY KEY (snapshot_version, group_key)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_songs_v2 (
        snapshot_version TEXT NOT NULL,
        id INTEGER NOT NULL,
        channel_id TEXT NOT NULL,
        canonical_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        group_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_entries_v2 (
        snapshot_version TEXT NOT NULL,
        id INTEGER NOT NULL,
        song_id INTEGER NOT NULL,
        group_key TEXT NOT NULL,
        video_id TEXT NOT NULL,
        timestamp_text TEXT NOT NULL,
        seconds INTEGER NOT NULL,
        raw_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        source_comment TEXT NOT NULL,
        jump_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, id)
      )
    `),
  ];
}

async function snapshotMeta(env) {
  try {
    return await env.DB.prepare(
      "SELECT version, status, expected_json FROM dataset_meta WHERE id = 1",
    ).first();
  } catch {
    return null;
  }
}

async function snapshotState(env, version) {
  const row = await snapshotMeta(env);
  if (!row || row.version !== version || row.status !== "loading") return null;
  return row;
}

function expectedTablesEqual(left, right) {
  return [...SEED_TABLES].every((table) => left?.[table] === right?.[table]);
}

function expectedTablesFromState(state) {
  try {
    return snapshotExpectedTables(JSON.parse(state?.expected_json || "{}"));
  } catch {
    return null;
  }
}

function snapshotCountCondition(expected) {
  const countChecks = [...SEED_TABLES].map((table) =>
    `(SELECT COUNT(*) FROM ${SNAPSHOT_STAGING_TABLES[table]} WHERE snapshot_version = ?) = ?`,
  );
  return countChecks.join(" AND ");
}

function snapshotCountParams(version, expected) {
  return [...SEED_TABLES].flatMap((table) => [version, expected[table]]);
}

async function startSnapshot(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing snapshot version" }, 400);
  let expectedTables;
  try {
    expectedTables = snapshotExpectedTables(payload?.tables);
  } catch {
    return json({ ok: false, message: "Missing or invalid snapshot table counts" }, 400);
  }

  try {
    // DDL is kept in its own batch so retries work even when dataset_meta does
    // not exist yet.  The metadata update and version-scoped cleanup below are
    // still one transaction.
    await env.DB.batch(snapshotSchemaStatements(env));
    const current = await snapshotMeta(env);
    const expectedJson = JSON.stringify(expectedTables);
    if (current?.version === version && ["loading", "ready"].includes(current.status)) {
      const currentExpected = expectedTablesFromState(current);
      if (!expectedTablesEqual(currentExpected, expectedTables)) {
        return json({ ok: false, message: "Snapshot version already exists with different row counts" }, 409);
      }
      return json({ ok: true, version, status: current.status });
    }

    await env.DB.batch([
      ...[...SEED_TABLES].map((table) =>
        env.DB.prepare(`
          DELETE FROM ${SNAPSHOT_STAGING_TABLES[table]}
          WHERE snapshot_version <> ?
        `).bind(version),
      ),
      env.DB.prepare(`
        INSERT INTO dataset_meta (id, version, status, expected_json, updated_at)
        VALUES (1, ?, 'loading', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          version = excluded.version,
          status = excluded.status,
          expected_json = excluded.expected_json,
          updated_at = excluded.updated_at
        WHERE dataset_meta.version <> excluded.version
           OR dataset_meta.status NOT IN ('loading', 'ready')
      `).bind(version, expectedJson),
    ]);

    const finalState = await snapshotMeta(env);
    if (!finalState || finalState.version !== version) {
      return json({ ok: false, message: "Snapshot was superseded before it became active" }, 409);
    }
    const finalExpected = expectedTablesFromState(finalState);
    if (!expectedTablesEqual(finalExpected, expectedTables)) {
      return json({ ok: false, message: "Snapshot version already exists with different row counts" }, 409);
    }
    return json({ ok: true, version, status: finalState.status });
  } catch (error) {
    console.error("snapshot start failed", error);
    return json({ ok: false, message: "Snapshot start failed" }, 500);
  }
}

async function commitSnapshot(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing snapshot version" }, 400);
  const current = await snapshotMeta(env);
  if (!current || current.version !== version) {
    return json({ ok: false, message: "Snapshot is not ready for commit" }, 409);
  }
  if (current.status === "ready") {
    return json({ ok: true, version, status: "ready" });
  }
  if (current.status !== "loading") {
    return json({ ok: false, message: "Snapshot is not ready for commit" }, 409);
  }
  const expected = expectedTablesFromState(current);
  if (!expected) {
    return json({ ok: false, message: "Snapshot is incomplete; live data was kept" }, 409);
  }
  const countGuard = snapshotCountCondition(expected);
  const countParams = snapshotCountParams(version, expected);
  const activeGuard = "EXISTS (SELECT 1 FROM dataset_meta WHERE id = 1 AND version = ? AND status = 'committing')";
  const activeParams = [version];

  try {
    const statements = [
      // Count validation and the loading -> committing transition happen in
      // the same transaction as the swap.  A mismatch leaves this row in
      // loading, so all following statements become no-ops.
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'committing', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'loading'
          AND ${countGuard}
      `).bind(version, ...countParams),
      env.DB.prepare(`DELETE FROM song_entries WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM songs WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM song_groups WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM videos WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM channels WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`
        INSERT INTO channels (channel_id, channel_title)
        SELECT channel_id, channel_title
        FROM ${SNAPSHOT_STAGING_TABLES.channels}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at)
        SELECT video_id, channel_id, title, published_at, url, indexed_at
        FROM ${SNAPSHOT_STAGING_TABLES.videos}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
        SELECT group_key, song_title, artist, title_search, artist_search, entry_count, channel_count
        FROM ${SNAPSHOT_STAGING_TABLES.song_groups}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
        SELECT id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at
        FROM ${SNAPSHOT_STAGING_TABLES.songs}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
        SELECT id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at
        FROM ${SNAPSHOT_STAGING_TABLES.song_entries}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'ready', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'committing'
          AND ${activeGuard}
      `).bind(version, ...activeParams),
    ];
    await env.DB.batch(statements);

    const finalState = await snapshotMeta(env);
    if (finalState?.version === version && finalState.status === "ready") {
      return json({ ok: true, version, status: "ready" });
    }
    if (finalState?.version === version && finalState.status === "loading") {
      return json({ ok: false, message: "Snapshot is incomplete; live data was kept" }, 409);
    }
    return json({ ok: false, message: "Snapshot was superseded before commit" }, 409);
  } catch (error) {
    console.error("snapshot commit failed", error);
    return json({ ok: false, message: "Snapshot commit failed; previous data was kept" }, 500);
  }
}

async function seed(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const table = String(payload?.table || "");
  const rows = payload?.rows;
  const version = requestText(payload?.version || request.headers.get("x-seed-version"), 120);
  if (!SEED_TABLES.has(table) || !Array.isArray(rows) || rows.length === 0 || rows.length > 90) {
    return json({ ok: false, message: "Invalid seed batch" }, 400);
  }
  if (!version) {
    return json({ ok: false, message: "Snapshot version is required; start a snapshot before seeding" }, 409);
  }
  if (!(await snapshotState(env, version))) {
    return json({ ok: false, message: "Snapshot is not active" }, 409);
  }
  try {
    // The guard is the first statement in the same D1 transaction as every
    // row write.  A request that was checked before a newer start cannot
    // insert into the newer snapshot's staging rows.
    const statements = [
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'loading'
        WHERE id = 1 AND version = ? AND status = 'loading'
      `).bind(version),
      ...seedStatements(table, rows, env, version),
    ];
    const results = await env.DB.batch(statements);
    const guardChanges = Number(results?.[0]?.meta?.changes);
    if (guardChanges !== 1) {
      return json({ ok: false, message: "Snapshot is no longer active" }, 409);
    }
    return json({ ok: true, table, inserted: rows.length, version });
  } catch (error) {
    console.error("seed failed", table, error);
    return json({ ok: false, message: "Seed batch failed" }, 500);
  }
}

async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (request.method === "GET" && (path === "/" || path === "/index.html")) {
    return textResponse(pageHtml, "text/html; charset=utf-8");
  }
  if (request.method === "GET" && path === "/styles.css") {
    return textResponse(stylesCss, "text/css; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/app.js") {
    return textResponse(clientJs, "text/javascript; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/favicon.svg") {
    return textResponse(faviconSvg, "image/svg+xml", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/api/overview") {
    try {
      return json(await queryOverview(env));
    } catch (error) {
      console.error("overview failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/search") {
    try {
      return json(await searchGroups(env, url));
    } catch (error) {
      console.error("search failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/entries") {
    try {
      const result = await searchEntries(env, url);
      return json(result, result.ok === false ? 400 : 200);
    } catch (error) {
      console.error("entries failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/start") {
    return startSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/commit") {
    return commitSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/seed") {
    return seed(request, env);
  }
  return json({ ok: false, message: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    return handle(request, env);
  },
};
