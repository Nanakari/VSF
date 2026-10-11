(() => {
  const root = document.querySelector("#setup-root");
  const form = document.querySelector("#index-form");
  const button = document.querySelector("#start-button");
  const saveSiteConfigButton = document.querySelector("#save-site-config");
  const syncSiteButton = document.querySelector("#sync-site-button");
  const confirmDeleteButton = document.querySelector("#confirm-delete-button");
  const exitButton = document.querySelector("#exit-button");
  const updateChannelButtons = document.querySelectorAll(".update-channel-button");
  const deleteChannelButtons = document.querySelectorAll(".delete-channel-button");
  const message = document.querySelector("#status-message");
  const log = document.querySelector("#job-log");
  const deleteDialog = document.querySelector("#delete-dialog");
  const deleteConfirmForm = document.querySelector("#delete-confirm-form");
  const deleteChannelId = document.querySelector("#delete-channel-id");
  const deleteConfirmation = document.querySelector("#delete-confirmation");
  const deleteDialogSummary = document.querySelector("#delete-dialog-summary");
  const cancelDelete = document.querySelector("#cancel-delete");
  let deleteChannelTitle = "";
  let formError = "";
  let reloadAfterDelete = false;
  let reloadAfterIndex = false;
  let requestPending = false;
  let statusPending = false;
  let statusGeneration = 0;
  const statMap = {
    videos_seen: document.querySelector("#videos-seen"),
    videos_indexed: document.querySelector("#videos-indexed"),
    videos_skipped: document.querySelector("#videos-skipped"),
    videos_failed: document.querySelector("#videos-failed"),
    comments_seen: document.querySelector("#comments-seen"),
    timeline_comments: document.querySelector("#timeline-comments"),
    entries_inserted: document.querySelector("#entries-inserted")
  };

  const setIndexControlsDisabled = (disabled) => {
    button.disabled = disabled;
    saveSiteConfigButton.disabled = disabled;
    syncSiteButton.disabled = disabled;
    confirmDeleteButton.disabled = disabled;
    deleteChannelButtons.forEach((deleteButton) => {
      deleteButton.disabled = disabled;
    });
    updateChannelButtons.forEach((updateButton) => {
      updateButton.disabled = disabled;
    });
  };

  const postAction = async (url, payload, pendingMessage, operation = "") => {
    if (requestPending) return false;
    requestPending = true;
    statusGeneration += 1;
    formError = "";
    setIndexControlsDisabled(true);
    message.textContent = pendingMessage;
    try {
      const response = await fetch(url, {
        method: "POST",
        body: payload
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        formError = data.message || "启动失败。";
        setIndexControlsDisabled(false);
        message.textContent = formError;
        return false;
      }
      message.textContent = data.message || "操作已开始。";
      if (operation === "index") reloadAfterIndex = true;
      if (operation === "delete-channel") reloadAfterDelete = true;
      if (!operation) formError = message.textContent;
      return true;
    } catch (_) {
      formError = "无法连接更新服务，请重新打开更新页面。";
      setIndexControlsDisabled(false);
      message.textContent = formError;
      return false;
    } finally {
      requestPending = false;
      statusGeneration += 1;
      await refreshStatus();
    }
  };

  const startIndexTask = (payload, pendingMessage) => postAction(form.action, payload, pendingMessage, "index");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void startIndexTask(new FormData(form), "正在启动索引任务...");
  });

  updateChannelButtons.forEach((updateButton) => {
    updateButton.addEventListener("click", () => {
      const channelId = updateButton.dataset.channelId || "";
      const channelTitle = updateButton.dataset.channelTitle || channelId;
      const payload = new FormData(form);
      payload.set("channel", channelId);
      const mode = updateButton.dataset.mode || "incremental";
      payload.set("mode", mode);
      payload.delete("reset_backfill");
      void startIndexTask(
        payload,
        `正在对“${channelTitle}”执行${mode === "backfill" ? "历史回填" : "增量更新"}...`
      );
    });
  });

  saveSiteConfigButton.addEventListener("click", () => {
    void postAction(root.dataset.saveConfigUrl, new FormData(form), "正在保存站点同步设置...");
  });

  syncSiteButton.addEventListener("click", () => {
    void postAction(root.dataset.syncUrl, new FormData(form), "正在同步站点数据...", "sync-site");
  });

  deleteChannelButtons.forEach((deleteButton) => {
    deleteButton.addEventListener("click", () => {
      deleteChannelTitle = deleteButton.dataset.channelTitle || "";
      deleteChannelId.value = deleteButton.dataset.channelId || "";
      deleteConfirmation.value = "";
      confirmDeleteButton.disabled = false;
      deleteDialogSummary.textContent = `将删除“${deleteChannelTitle}”及其 ${deleteButton.dataset.channelVideoCount || 0} 个视频、${deleteButton.dataset.channelSongCount || 0} 首歌曲和 ${deleteButton.dataset.channelEntryCount || 0} 个时间点。`;
      deleteDialog.showModal();
      deleteConfirmation.focus();
    });
  });

  cancelDelete.addEventListener("click", () => deleteDialog.close());

  deleteConfirmForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (deleteConfirmation.value !== deleteChannelTitle) {
      message.textContent = "频道名称不匹配，未执行删除。";
      deleteConfirmation.focus();
      return;
    }
    const deleteData = new FormData(deleteConfirmForm);
    deleteData.append("site_base_url", form.elements.site_base_url.value);
    deleteData.append("site_seed_token", form.elements.site_seed_token.value);
    if (await postAction(deleteConfirmForm.action, deleteData, "正在删除频道...", "delete-channel")) {
      deleteDialog.close();
    }
  });

  exitButton.addEventListener("click", async () => {
    exitButton.disabled = true;
    message.textContent = "正在退出...";
    const shutdownUrl = root.dataset.shutdownUrl;
    const closeUrl = root.dataset.closeUrl;
    try {
      const response = await fetch(shutdownUrl, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        message.textContent = data.message || "索引任务正在运行，暂时不能退出。";
        exitButton.disabled = false;
        return;
      }
    } catch (_) {
      message.textContent = "无法确认索引服务状态，请不要关闭窗口，稍后重试。";
      exitButton.disabled = false;
      return;
    }
    window.open("", "_self");
    window.close();
    setTimeout(() => { window.location.href = closeUrl; }, 300);
  });
  const refreshStatus = async () => {
    if (requestPending || statusPending) return;
    const generation = statusGeneration;
    statusPending = true;
    try {
      const response = await fetch(root.dataset.statusUrl, { cache: "no-store" });
      if (!response.ok) throw new Error("status unavailable");
      const data = await response.json();
      // A status request started before a submission cannot unlock its controls
      // or report the previous task's completion after that submission.
      if (generation !== statusGeneration || requestPending) return;
      if (data.operation === "index" && data.running) {
        reloadAfterIndex = true;
      }
      if (data.operation === "delete-channel" && data.running) reloadAfterDelete = true;
      if (!formError) {
        message.textContent = data.message || "";
      }
      const stats = data.stats || {};
      Object.entries(statMap).forEach(([key, element]) => {
        element.textContent = String(stats[key] || 0);
      });
      log.textContent = (data.log || []).join("\n");
      log.scrollTop = log.scrollHeight;
      setIndexControlsDisabled(Boolean(data.running));
      if (reloadAfterDelete && data.operation === "delete-channel" && data.done && !data.running) {
        reloadAfterDelete = false;
        if (data.local_changed) window.setTimeout(() => window.location.reload(), 1200);
      }
      if (reloadAfterIndex && data.operation === "index" && data.done && !data.running) {
        reloadAfterIndex = false;
        window.setTimeout(() => window.location.reload(), 1200);
      }
    } catch (_) {
      if (generation === statusGeneration && !formError && !requestPending) {
        message.textContent = "暂时无法读取任务状态，正在重试...";
      }
    } finally {
      statusPending = false;
    }
  };

  const pollStatus = async () => {
    await refreshStatus();
    window.setTimeout(pollStatus, 1500);
  };
  void pollStatus();

  if (root.dataset.autoExit === "true") {
    const clientId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random());
    const payload = () => JSON.stringify({ client_id: clientId });
    const post = (url) => {
      try {
        navigator.sendBeacon(url, new Blob([payload()], { type: "application/json" }));
      } catch {
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload(),
          keepalive: true
        }).catch(() => {});
      }
    };
    post(root.dataset.pingUrl);
    const intervalId = window.setInterval(() => post(root.dataset.pingUrl), 5000);
    window.addEventListener("pagehide", (event) => {
      window.clearInterval(intervalId);
      if (event.persisted) {
        return;
      }
      post(root.dataset.clientCloseUrl);
    });
  }
})();
