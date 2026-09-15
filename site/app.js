(() => {
  const pageSize = 20;
  const entryPageSize = 10;
  const state = {
    overview: null,
    page: 1,
    pageCount: 1,
    total: 0,
    matches: [],
    requestId: 0,
  };

  const elements = {
    content: document.querySelector("#content"),
    loading: document.querySelector("#loading-state"),
    error: document.querySelector("#error-state"),
    dataStatus: document.querySelector("#data-status"),
    statsSummary: document.querySelector("#stats-summary"),
    updatedAt: document.querySelector("#updated-at"),
    form: document.querySelector("#search-form"),
    channelInput: document.querySelector("#channel-input"),
    songInput: document.querySelector("#song-input"),
    artistInput: document.querySelector("#artist-input"),
    clearSearch: document.querySelector("#clear-search"),
    homeView: document.querySelector("#home-view"),
    resultsView: document.querySelector("#results-view"),
    channelGrid: document.querySelector("#channel-grid"),
    resultSummary: document.querySelector("#result-summary"),
    resultsList: document.querySelector("#results-list"),
    resultsEmpty: document.querySelector("#results-empty"),
    resultsEmptyTitle: document.querySelector("#results-empty h3"),
    resultsEmptyText: document.querySelector("#results-empty p"),
    resultsPager: document.querySelector("#results-pager"),
    resultsPrev: document.querySelector("#results-prev"),
    resultsNext: document.querySelector("#results-next"),
    resultsPageLabel: document.querySelector("#results-page-label"),
    retryButton: document.querySelector("#retry-button"),
  };

  const text = (value) => String(value ?? "");
  const formatNumber = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const formatDate = (value) => {
    if (!value) return "日期未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return text(value).slice(0, 10);
    return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
  };

  function createElement(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = text(content);
    return element;
  }

  function getQueries() {
    const params = new URLSearchParams(window.location.search);
    return {
      channel: params.get("channel") || "",
      song: params.get("song") || "",
      artist: params.get("artist") || "",
    };
  }

  function setQueries(queries, replace = false) {
    const params = new URLSearchParams();
    ["channel", "song", "artist"].forEach((key) => {
      if (text(queries[key]).trim()) params.set(key, text(queries[key]).trim());
    });
    const url = params.toString() ? `${window.location.pathname}?${params}` : window.location.pathname;
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
  }

  function renderSearchInputs(queries) {
    elements.channelInput.value = queries.channel;
    elements.songInput.value = queries.song;
    elements.artistInput.value = queries.artist;
    elements.clearSearch.hidden = !Object.values(queries).some((value) => value.trim());
  }

  function renderStats() {
    const stats = state.overview?.stats || {};
    elements.statsSummary.textContent = `共 ${formatNumber(stats.channels)} 个频道 · ${formatNumber(stats.videos)} 个视频 · ${formatNumber(stats.songs)} 首歌曲 · ${formatNumber(stats.entries)} 个时间点`;
    elements.dataStatus.textContent = `${formatNumber(stats.entries)} 个时间点已就绪`;
    const updatedAt = state.overview?.updatedAt ? new Date(state.overview.updatedAt) : null;
    if (updatedAt && !Number.isNaN(updatedAt.getTime())) {
      elements.updatedAt.textContent = `数据库更新于 ${new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(updatedAt)}`;
    }
  }

  function renderChannels() {
    elements.channelGrid.replaceChildren();
    (state.overview?.channels || []).forEach((channel) => {
      const link = createElement("a", "channel-card");
      const accent = createElement("span", "channel-accent", "◒");
      const body = createElement("span", "channel-card-body");
      body.append(createElement("strong", "channel-title", channel.channel_title));
      body.append(createElement("span", "channel-count", `${formatNumber(channel.song_count)} 首歌曲 · ${formatNumber(channel.entry_count)} 个时间点`));
      const arrow = createElement("span", "channel-arrow", "↗");
      link.append(accent, body, arrow);
      link.href = `?channel=${encodeURIComponent(channel.channel_title)}`;
      elements.channelGrid.append(link);
    });
  }

  function makeEntryPager(groupKey, channel, artistQuery = "") {
    const wrapper = createElement("div", "entry-pager");
    const list = createElement("div", "entry-list");
    const controls = createElement("div", "entry-controls");
    const previous = createElement("button", "entry-button", "上一页");
    const label = createElement("span", "entry-page-label");
    const next = createElement("button", "entry-button", "下一页");
    let currentPage = 1;
    let pageCount = Math.max(1, Math.ceil(Number(channel.entryCount || 0) / entryPageSize));
    let entries = [];
    let loading = false;
    let loaded = false;
    let requestId = 0;

    const render = (message = "") => {
      list.replaceChildren();
      if (message) {
        list.append(createElement("div", "entry-state", message));
      } else if (entries.length === 0) {
        list.append(createElement("div", "entry-state", "暂无时间点"));
      } else {
        entries.forEach((entry) => {
          const row = createElement("div", "entry-row");
          const time = createElement("a", "timestamp", entry.timestampText || "打开");
          time.href = entry.jumpUrl;
          time.target = "_blank";
          time.rel = "noopener noreferrer";
          const video = createElement("span", "entry-video", entry.videoTitle || "未命名视频");
          const date = createElement("time", "entry-date", formatDate(entry.publishedAt));
          row.append(time, video, date);
          list.append(row);
        });
      }
      controls.hidden = pageCount <= 1;
      previous.disabled = loading || currentPage <= 1;
      next.disabled = loading || currentPage >= pageCount;
      label.textContent = `第 ${currentPage} / ${pageCount} 页`;
    };

    const loadPage = async (page) => {
      const currentRequest = ++requestId;
      loading = true;
      currentPage = page;
      render("正在载入时间点…");
      const params = new URLSearchParams({
        groupKey,
        channelId: channel.id,
        page: String(page),
        pageSize: String(entryPageSize),
      });
      if (artistQuery.trim()) params.set("artist", artistQuery.trim());
      try {
        const payload = await requestJson(`/api/entries?${params}`);
        if (currentRequest !== requestId) return;
        entries = Array.isArray(payload.entries) ? payload.entries : [];
        currentPage = Math.max(1, Number(payload.page || page));
        pageCount = Math.max(1, Number(payload.pageCount || 1));
        loaded = true;
        loading = false;
        render();
      } catch (error) {
        if (currentRequest !== requestId) return;
        console.error(error);
        loading = false;
        render("时间点载入失败，请稍后重试。");
      }
    };

    const loadIfNeeded = () => {
      if (!loaded && !loading && Number(channel.entryCount || 0) > 0) {
        void loadPage(currentPage);
      }
    };

    previous.addEventListener("click", () => {
      if (!loading && currentPage > 1) {
        void loadPage(currentPage - 1);
      }
    });
    next.addEventListener("click", () => {
      if (!loading && currentPage < pageCount) {
        void loadPage(currentPage + 1);
      }
    });
    controls.append(previous, label, next);
    wrapper.append(list, controls);
    render();
    return { element: wrapper, loadIfNeeded };
  }

  function renderGroup(group, shouldOpen, artistQuery = "") {
    const details = createElement("details", "song-group");
    details.open = shouldOpen;
    const summary = createElement("summary", "song-summary");
    const icon = createElement("span", "song-icon", "♪");
    const main = createElement("span", "song-main");
    main.append(createElement("strong", "song-title", group.songTitle));
    main.append(createElement("span", "song-meta", `${formatNumber(group.entryCount)} 个时间点 · ${formatNumber(group.channelCount)} 个频道`));
    const artist = createElement("span", "song-artist", group.artist || "作者未知");
    const chevron = createElement("span", "song-chevron", "›");
    summary.append(icon, main, artist, chevron);

    const body = createElement("div", "song-body");
    (group.channels || []).forEach((channel) => {
      const channelBlock = createElement("details", "channel-block");
      channelBlock.open = group.channels.length === 1;
      const channelSummary = createElement("summary", "channel-summary");
      channelSummary.append(createElement("span", "channel-chevron", "›"));
      channelSummary.append(createElement("strong", "channel-name", channel.title));
      channelSummary.append(createElement("span", "channel-entry-count", `${formatNumber(channel.entryCount)} 个时间点`));
      const pager = makeEntryPager(group.id, channel, artistQuery);
      channelBlock.append(channelSummary, pager.element);
      channelBlock.addEventListener("toggle", () => {
        if (channelBlock.open) pager.loadIfNeeded();
      });
      if (channelBlock.open) pager.loadIfNeeded();
      body.append(channelBlock);
    });
    details.append(summary, body);
    return details;
  }

  function setEmptyState(title, message, hidden) {
    elements.resultsEmptyTitle.textContent = title;
    elements.resultsEmptyText.textContent = message;
    elements.resultsEmpty.hidden = hidden;
  }

  function renderResults() {
    const queries = getQueries();
    elements.resultsList.replaceChildren();
    state.matches.forEach((group) => elements.resultsList.append(renderGroup(group, state.total === 1, queries.artist)));
    elements.resultSummary.textContent = state.total ? `${formatNumber(state.total)} 首匹配歌曲` : "没有匹配歌曲";
    setEmptyState("没有找到匹配条目", "可以换一种歌曲或作者写法，或者先清除一个筛选条件。", state.total !== 0);
    elements.resultsPager.hidden = state.total === 0 || state.pageCount <= 1;
    elements.resultsPrev.disabled = state.page <= 1;
    elements.resultsNext.disabled = state.page >= state.pageCount;
    elements.resultsPageLabel.textContent = `第 ${state.page} / ${state.pageCount} 页`;
  }

  async function requestJson(url) {
    const response = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.message || `请求失败（${response.status}）`);
    return payload;
  }

  async function refreshResults(queries) {
    const requestId = ++state.requestId;
    const params = new URLSearchParams();
    Object.entries(queries).forEach(([key, value]) => {
      if (value.trim()) params.set(key, value.trim());
    });
    params.set("page", String(state.page));
    params.set("pageSize", String(pageSize));
    elements.resultSummary.textContent = "正在查询数据库…";
    elements.resultsList.replaceChildren();
    setEmptyState("正在查询", "正在从实时数据库读取歌曲和时间点。", false);
    elements.resultsPager.hidden = true;
    try {
      const payload = await requestJson(`/api/search?${params}`);
      if (requestId !== state.requestId) return;
      state.matches = Array.isArray(payload.groups) ? payload.groups : [];
      state.page = Math.max(1, Number(payload.page || state.page));
      state.pageCount = Math.max(1, Number(payload.pageCount || 1));
      state.total = Math.max(0, Number(payload.total || 0));
      renderResults();
    } catch (error) {
      if (requestId !== state.requestId) return;
      console.error(error);
      state.matches = [];
      state.total = 0;
      state.pageCount = 1;
      elements.resultSummary.textContent = "查询失败";
      setEmptyState("数据库暂时无法查询", "请稍后重试；如果问题持续存在，请刷新页面。", false);
    }
  }

  async function render() {
    const queries = getQueries();
    renderSearchInputs(queries);
    const hasSearch = Object.values(queries).some((value) => value.trim());
    elements.homeView.hidden = hasSearch;
    elements.resultsView.hidden = !hasSearch;
    if (hasSearch) await refreshResults(queries);
  }

  function showLoadedState() {
    elements.loading.hidden = true;
    elements.error.hidden = true;
    elements.content.hidden = false;
    renderStats();
    renderChannels();
  }

  async function loadOverview() {
    elements.loading.hidden = false;
    elements.error.hidden = true;
    elements.content.hidden = true;
    elements.dataStatus.textContent = "载入数据库中";
    try {
      state.overview = await requestJson("/api/overview");
      showLoadedState();
      await render();
    } catch (error) {
      console.error(error);
      elements.loading.hidden = true;
      elements.error.hidden = false;
      elements.content.hidden = true;
      elements.dataStatus.textContent = "载入失败";
    }
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    state.page = 1;
    setQueries({
      channel: elements.channelInput.value,
      song: elements.songInput.value,
      artist: elements.artistInput.value,
    });
    void render();
  });
  elements.clearSearch.addEventListener("click", () => {
    state.page = 1;
    setQueries({ channel: "", song: "", artist: "" });
    void render();
    elements.channelInput.focus();
  });
  elements.resultsPrev.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      void refreshResults(getQueries());
      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: "smooth" });
    }
  });
  elements.resultsNext.addEventListener("click", () => {
    if (state.page < state.pageCount) {
      state.page += 1;
      void refreshResults(getQueries());
      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: "smooth" });
    }
  });
  window.addEventListener("popstate", () => {
    state.page = 1;
    void render();
  });
  elements.retryButton.addEventListener("click", () => void loadOverview());

  if (typeof document.modelContext?.registerTool === "function") {
    const lifecycle = new AbortController();
    Promise.resolve(document.modelContext.registerTool({
      name: "search_vtuber_songs",
      title: "Search VTuber songs",
      description: "Search the live VTuber Song Finder database by channel, song title, or artist and update the page to show matching songs.",
      inputSchema: {
        type: "object",
        properties: {
          channel: { type: "string", description: "Optional channel name or channel ID." },
          song: { type: "string", description: "Optional song title or keyword." },
          artist: { type: "string", description: "Optional artist or author name." },
        },
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: true },
      async execute(input) {
        if (!state.overview) return { ok: false, message: "The database is still loading." };
        const value = input && typeof input === "object" ? input : {};
        const queries = {
          channel: text(value.channel),
          song: text(value.song),
          artist: text(value.artist),
        };
        state.page = 1;
        setQueries(queries);
        await render();
        return {
          ok: true,
          matchCount: state.total,
          page: state.page,
          query: queries,
          songs: state.matches.slice(0, 5).map((group) => ({ title: group.songTitle, artist: group.artist, entryCount: group.entryCount })),
        };
      },
    }, { signal: lifecycle.signal })).catch((error) => console.warn("WebMCP registration failed", error));
    window.addEventListener("pagehide", () => lifecycle.abort(), { once: true });
  }

  void loadOverview();
})();
