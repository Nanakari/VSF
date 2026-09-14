(() => {
  const pageSize = 20;
  const entryPageSize = 10;
  const state = {
    catalog: null,
    page: 1,
    matches: [],
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
    resultsPager: document.querySelector("#results-pager"),
    resultsPrev: document.querySelector("#results-prev"),
    resultsNext: document.querySelector("#results-next"),
    resultsPageLabel: document.querySelector("#results-page-label"),
    retryButton: document.querySelector("#retry-button"),
  };

  const text = (value) => String(value ?? "");
  const normalized = (value) => text(value).trim().toLocaleLowerCase();
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
      if (queries[key].trim()) params.set(key, queries[key].trim());
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
    const stats = state.catalog.stats || {};
    elements.statsSummary.textContent = `共 ${formatNumber(stats.channels)} 个频道 · ${formatNumber(stats.videos)} 个视频 · ${formatNumber(stats.songs)} 首歌曲 · ${formatNumber(stats.entries)} 个时间点`;
    elements.dataStatus.textContent = `${formatNumber(stats.entries)} 个时间点已就绪`;
    const generatedAt = state.catalog.generatedAt ? new Date(state.catalog.generatedAt) : null;
    if (generatedAt && !Number.isNaN(generatedAt.getTime())) {
      elements.updatedAt.textContent = `数据快照 ${new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(generatedAt)}`;
    }
  }

  function renderChannels() {
    elements.channelGrid.replaceChildren();
    state.catalog.channels.forEach((channel) => {
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

  function matchesGroup(group, queries) {
    const channelQuery = normalized(queries.channel);
    const songQuery = normalized(queries.song);
    const artistQuery = normalized(queries.artist);
    if (channelQuery) {
      const matchesChannel = group.channels.some((channel) => normalized(channel.title).includes(channelQuery) || normalized(channel.id) === channelQuery);
      if (!matchesChannel) return false;
    }
    if (songQuery && !normalized(group.titleSearchText || group.songTitle).includes(songQuery)) return false;
    if (artistQuery && !normalized(group.artistSearchText || group.artist).includes(artistQuery)) return false;
    return true;
  }

  function makeEntryPager(entries) {
    const wrapper = createElement("div", "entry-pager");
    const list = createElement("div", "entry-list");
    const controls = createElement("div", "entry-controls");
    const previous = createElement("button", "entry-button", "上一页");
    const label = createElement("span", "entry-page-label");
    const next = createElement("button", "entry-button", "下一页");
    let currentPage = 0;
    const pageCount = Math.max(1, Math.ceil(entries.length / entryPageSize));

    const render = () => {
      list.replaceChildren();
      const start = currentPage * entryPageSize;
      entries.slice(start, start + entryPageSize).forEach((entry) => {
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
      previous.disabled = currentPage === 0;
      next.disabled = currentPage >= pageCount - 1;
      label.textContent = `第 ${currentPage + 1} / ${pageCount} 页`;
    };

    previous.addEventListener("click", () => {
      if (currentPage > 0) {
        currentPage -= 1;
        render();
      }
    });
    next.addEventListener("click", () => {
      if (currentPage < pageCount - 1) {
        currentPage += 1;
        render();
      }
    });
    controls.append(previous, label, next);
    wrapper.append(list, controls);
    render();
    return wrapper;
  }

  function renderGroup(group, shouldOpen) {
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
    group.channels.forEach((channel) => {
      const channelBlock = createElement("details", "channel-block");
      channelBlock.open = group.channels.length === 1;
      const channelSummary = createElement("summary", "channel-summary");
      channelSummary.append(createElement("span", "channel-chevron", "›"));
      channelSummary.append(createElement("strong", "channel-name", channel.title));
      channelSummary.append(createElement("span", "channel-entry-count", `${formatNumber(channel.entries.length)} 个时间点`));
      channelBlock.append(channelSummary, makeEntryPager(channel.entries));
      body.append(channelBlock);
    });
    details.append(summary, body);
    return details;
  }

  function renderResults(queries) {
    state.matches = state.catalog.groups.filter((group) => matchesGroup(group, queries));
    const totalPages = Math.max(1, Math.ceil(state.matches.length / pageSize));
    state.page = Math.min(state.page, totalPages);
    const start = (state.page - 1) * pageSize;
    const visibleGroups = state.matches.slice(start, start + pageSize);
    elements.resultsList.replaceChildren();
    visibleGroups.forEach((group) => elements.resultsList.append(renderGroup(group, state.matches.length === 1)));
    elements.resultSummary.textContent = state.matches.length ? `${formatNumber(state.matches.length)} 首匹配歌曲` : "没有匹配歌曲";
    elements.resultsEmpty.hidden = state.matches.length !== 0;
    elements.resultsPager.hidden = state.matches.length <= pageSize;
    elements.resultsPrev.disabled = state.page === 1;
    elements.resultsNext.disabled = state.page >= totalPages;
    elements.resultsPageLabel.textContent = `第 ${state.page} / ${totalPages} 页`;
  }

  function render() {
    const queries = getQueries();
    renderSearchInputs(queries);
    const hasSearch = Object.values(queries).some((value) => value.trim());
    elements.homeView.hidden = hasSearch;
    elements.resultsView.hidden = !hasSearch;
    if (hasSearch) renderResults(queries);
  }

  function showLoadedState() {
    elements.loading.hidden = true;
    elements.error.hidden = true;
    elements.content.hidden = false;
    renderStats();
    renderChannels();
    render();
  }

  async function loadCatalog() {
    try {
      const response = await fetch("./catalog.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`catalog ${response.status}`);
      state.catalog = await response.json();
      showLoadedState();
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
    render();
  });
  elements.clearSearch.addEventListener("click", () => {
    state.page = 1;
    setQueries({ channel: "", song: "", artist: "" });
    render();
    elements.channelInput.focus();
  });
  elements.resultsPrev.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      renderResults(getQueries());
      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: "smooth" });
    }
  });
  elements.resultsNext.addEventListener("click", () => {
    const totalPages = Math.ceil(state.matches.length / pageSize);
    if (state.page < totalPages) {
      state.page += 1;
      renderResults(getQueries());
      window.scrollTo({ top: elements.resultsView.offsetTop - 24, behavior: "smooth" });
    }
  });
  window.addEventListener("popstate", () => {
    state.page = 1;
    render();
  });
  elements.retryButton.addEventListener("click", loadCatalog);

  if (typeof document.modelContext?.registerTool === "function") {
    const lifecycle = new AbortController();
    Promise.resolve(document.modelContext.registerTool({
      name: "search_vtuber_songs",
      title: "Search VTuber songs",
      description: "Search the visible VTuber Song Finder catalog by channel, song title, or artist and update the page to show matching songs.",
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
      execute(input) {
        if (!state.catalog) return { ok: false, message: "The catalog is still loading." };
        const value = input && typeof input === "object" ? input : {};
        const queries = {
          channel: text(value.channel),
          song: text(value.song),
          artist: text(value.artist),
        };
        state.page = 1;
        setQueries(queries);
        render();
        return {
          ok: true,
          matchCount: state.matches.length,
          page: 1,
          query: queries,
          songs: state.matches.slice(0, 5).map((group) => ({ title: group.songTitle, artist: group.artist, entryCount: group.entryCount })),
        };
      },
    }, { signal: lifecycle.signal })).catch((error) => console.warn("WebMCP registration failed", error));
    window.addEventListener("pagehide", () => lifecycle.abort(), { once: true });
  }

  loadCatalog();
})();
