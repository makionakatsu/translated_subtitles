let currentProject = null;
let saveTimer = null;
let appSettings = { gemini_api_key: { configured: false, source: "missing" } };
let lastProjectDataRefreshAt = 0;

const mlxModels = {
  fast: "mlx-community/whisper-small-mlx",
  balanced: "mlx-community/whisper-medium-mlx",
  quality: "mlx-community/whisper-large-v3-mlx",
};

const $ = (id) => document.getElementById(id);

function apiKey() {
  return $("apiKey").value.trim();
}

function setStatus(message, progress = null) {
  $("statusText").textContent = message;
  if (progress !== null) $("progress").value = progress;
}

function setStage(stage = "idle", label = "待機中", stageProgress = 0) {
  const pill = $("stagePill");
  pill.textContent = label;
  pill.className = `stage-pill ${stage === "done" ? "done" : stage === "failed" ? "failed" : stage === "idle" ? "idle" : "running"}`;
  $("stageLabel").textContent = label;
  $("stageProgressText").textContent = `${Math.round(stageProgress || 0)}%`;
}

function logActivity(message, type = "info") {
  const log = $("activityLog");
  if (!log) return;
  const entry = document.createElement("div");
  entry.className = `activity ${type}`;
  const time = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  entry.textContent = `[${time}] ${message}`;
  log.prepend(entry);
  while (log.children.length > 80) log.removeChild(log.lastChild);
}

function showError(error) {
  const message = error && error.message ? error.message : String(error);
  setStatus(`エラー: ${message}`);
  setStage("failed", "失敗", 100);
  logActivity(`エラー: ${message}`, "error");
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function selectedLabel(id) {
  const el = $(id);
  return el.options[el.selectedIndex] ? el.options[el.selectedIndex].textContent : "";
}

function updateSettingsSummary() {
  $("settingsSummary").textContent = `${selectedLabel("preset")} / ${selectedLabel("asrEngine")} / ${selectedLabel("targetLang")}`;
  $("presetModel").textContent = mlxModels[$("preset").value] || mlxModels.fast;
}

async function runAction(action, label = "処理中") {
  try {
    setStatus(label, null);
    logActivity(label);
    await action();
  } catch (error) {
    console.error(error);
    showError(error);
  }
}

function enableProjectButtons(enabled) {
  const hasProject = Boolean(currentProject && enabled);
  const hasSegments = hasProject && currentProject.segments && currentProject.segments.length > 0;
  $("generateBtn").disabled = !hasProject;
  $("renderSubsBtn").disabled = !hasSegments;
  $("renderMp4Btn").disabled = !hasSegments;
  updateSteps();
}

async function refreshProject() {
  if (!currentProject) return;
  const data = await jsonFetch(`/api/projects/${currentProject.id}`);
  currentProject = data.project;
  renderProject(data.artifacts || {});
}

async function refreshProjectDataOnly() {
  if (!currentProject) return;
  const data = await jsonFetch(`/api/projects/${currentProject.id}`);
  currentProject = data.project;
  renderSegments();
  renderSummary();
  renderArtifacts(data.artifacts || {});
  updateSteps();
}

function renderProject(artifacts = {}) {
  const videoPath = `/api/projects/${currentProject.id}/video`;
  if (!$("video").src || new URL($("video").src, location.href).pathname !== videoPath) {
    $("video").src = videoPath;
  }
  renderSegments();
  renderArtifacts(artifacts);
  renderSummary();
  enableProjectButtons(true);
  const status = currentProject.generation_status || {};
  if (status.message) {
    setStatus(status.message, status.stage === "done" ? 100 : $("progress").value);
    setStage(status.stage || "idle", stageLabelFromStatus(status.stage), status.stage === "done" ? 100 : 0);
  } else if (!currentProject.segments || currentProject.segments.length === 0) {
    setStatus("動画の読み込みが完了しました。次は字幕を作成してください", 0);
    setStage("idle", "待機中", 0);
  }
  updateSteps();
}

function renderSummary() {
  const segments = currentProject ? currentProject.segments || [] : [];
  const summary = currentProject ? currentProject.translation_summary || {} : {};
  const translated = Number(summary.translated || segments.filter((s) => s.translated_text).length);
  const warnings = Number(summary.warning_segments || segments.filter((s) => (s.warnings || []).length).length);
  $("summarySegments").textContent = String(segments.length);
  $("summaryTranslated").textContent = String(translated);
  $("summaryWarnings").textContent = String(warnings);
  $("segmentCount").textContent = `${segments.length}件`;
  $("tableSummary").textContent = `${segments.length}件中 ${translated}件翻訳済み / 警告 ${warnings}件`;
}

function renderArtifacts(artifacts) {
  const labels = {
    ass_path: "ASS",
    srt_path: "SRT",
    vtt_path: "VTT",
    bilingual_ass_path: "Bilingual ASS",
    burned_mp4_path: "MP4",
    preview_mp4_path: "Preview",
  };
  $("artifactLinks").innerHTML = Object.entries(artifacts)
    .map(([key, url]) => `<a href="${url}" download>${labels[key] || key}</a>`)
    .join("");
}

function renderSegments() {
  const container = $("segments");
  container.innerHTML = "";
  const segments = filteredSegments();
  for (const segment of segments) {
    const row = document.createElement("div");
    row.className = "segment";
    row.dataset.id = segment.id;
    const status = segmentStatus(segment);
    row.innerHTML = `
      <button class="seek" type="button">${segment.id}</button>
      <div class="segment-time">
        <input class="start" type="number" min="0" step="10" value="${segment.start_ms}">
        <input class="end" type="number" min="0" step="10" value="${segment.end_ms}">
      </div>
      <span class="badge ${status.className}">${status.label}</span>
      <textarea class="source" readonly>${escapeHtml(segment.source_text || "")}</textarea>
      <textarea class="translated" readonly>${escapeHtml(segment.translated_text || "")}</textarea>
      <textarea class="text">${escapeHtml(segment.display_text || "")}</textarea>
      <div class="segment-tools">
        <label><input class="locked" type="checkbox" ${segment.locked ? "checked" : ""}> 固定</label>
        <button class="split" type="button">分割</button>
        <button class="merge" type="button">結合</button>
      </div>
      <div class="warnings">${(segment.warnings || []).join(" / ")}</div>
    `;
    row.querySelector(".seek").addEventListener("click", () => {
      $("video").currentTime = segment.start_ms / 1000;
      updateCurrentCaption();
      $("video").play().catch(() => {});
    });
    row.querySelector(".split").addEventListener("click", () => runAction(async () => {
      const atMs = Math.round(($("video").currentTime || ((segment.start_ms + segment.end_ms) / 2000)) * 1000);
      const splitAt = atMs > segment.start_ms && atMs < segment.end_ms ? atMs : Math.round((segment.start_ms + segment.end_ms) / 2);
      const data = await jsonFetch(`/api/projects/${currentProject.id}/segments/${segment.id}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ at_ms: splitAt }),
      });
      currentProject = data.project;
      renderProject(data.artifacts || {});
    }, "字幕を分割しています"));
    row.querySelector(".merge").addEventListener("click", () => runAction(async () => {
      const data = await jsonFetch(`/api/projects/${currentProject.id}/segments/${segment.id}/merge-next`, { method: "POST" });
      currentProject = data.project;
      renderProject(data.artifacts || {});
    }, "字幕を結合しています"));
    ["start", "end", "text", "locked"].forEach((klass) => {
      row.querySelector(`.${klass}`).addEventListener("input", () => scheduleSave(row));
    });
    container.appendChild(row);
  }
}

function filteredSegments() {
  if (!currentProject) return [];
  const segments = currentProject.segments || [];
  const mode = $("segmentFilter").value;
  const videoTime = $("video").currentTime * 1000;
  let visible = segments;
  if (mode === "missing") visible = segments.filter((s) => !s.translated_text && currentProject.target_lang !== "none");
  if (mode === "warnings") visible = segments.filter((s) => (s.warnings || []).length > 0);
  if (mode === "current") visible = segments.filter((s) => Math.abs(s.start_ms - videoTime) < 180000);
  if (visible.length > 160) {
    const around = visible.filter((s) => Math.abs(s.start_ms - videoTime) < 180000);
    visible = around.length >= 40 ? around : visible.slice(0, 160);
  }
  return visible;
}

function segmentStatus(segment) {
  const warnings = segment.warnings || [];
  if (warnings.includes("TRANSLATION_MISSING")) return { label: "fallback", className: "fallback" };
  if (segment.translated_text) return { label: "翻訳済み", className: "translated" };
  if (currentProject && currentProject.target_lang !== "none" && currentProject.status === "translated") return { label: "未翻訳", className: "missing" };
  if (currentProject && currentProject.status === "transcribed") return { label: "翻訳待ち", className: "pending" };
  return { label: "作成済み", className: "pending" };
}

function scheduleSave(row) {
  const id = Number(row.dataset.id);
  const segment = currentProject.segments.find((s) => s.id === id);
  if (!segment) return;
  segment.start_ms = Number(row.querySelector(".start").value);
  segment.end_ms = Number(row.querySelector(".end").value);
  segment.display_text = row.querySelector(".text").value;
  segment.locked = row.querySelector(".locked").checked;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveSegments, 450);
}

async function saveSegments() {
  const patches = currentProject.segments.map((s) => ({
    id: s.id,
    start_ms: s.start_ms,
    end_ms: s.end_ms,
    display_text: s.display_text,
    locked: s.locked,
  }));
  const data = await jsonFetch(`/api/projects/${currentProject.id}/segments`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patches),
  });
  currentProject = data.project;
  renderSegments();
  renderSummary();
}

function currentCaption() {
  if (!currentProject) return "";
  const now = $("video").currentTime * 1000;
  const segment = currentProject.segments.find((s) => now >= s.start_ms && now <= s.end_ms);
  return segment ? segment.display_text || "" : "";
}

function updateCurrentCaption() {
  const text = currentCaption();
  $("captionOverlay").textContent = text;
  $("currentCaptionText").textContent = text || "該当する字幕はありません";
}

function watchJob(jobId, options = {}) {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/jobs/${jobId}`);
  ws.onmessage = async (event) => {
    const job = JSON.parse(event.data);
    renderJob(job);
    if (["succeeded", "failed", "canceled"].includes(job.status)) {
      await refreshProject().catch(() => {});
      if (job.status === "succeeded" && options.onSucceeded) await options.onSucceeded(job);
    }
  };
  ws.onerror = () => {
    logActivity("進捗接続でエラーが発生しました。状態を再取得します", "error");
    setTimeout(() => refreshProject().catch(() => {}), 1000);
  };
  ws.onclose = () => {
    setTimeout(() => refreshProject().catch(() => {}), 800);
  };
}

function renderJob(job) {
  const message = `${job.status}: ${job.message || ""}${job.error ? " - " + job.error : ""}`;
  setStatus(message, job.progress || 0);
  setStage(job.stage || job.status, job.stage_label || stageLabelFromStatus(job.stage || job.status), job.stage_progress || job.progress || 0);
  $("batchCounter").textContent = job.total_items ? `${job.current_item || 0}/${job.total_items}` : "-";
  $("etaText").textContent = job.eta_sec ? formatEta(job.eta_sec) : "-";
  logActivity(`${job.stage_label || job.kind || "job"}: ${Math.round(job.progress || 0)}% ${job.message || ""}${job.error ? " - " + job.error : ""}`, job.status === "failed" ? "error" : "info");

  if (job.status === "running" && job.stage === "translate") {
    const now = Date.now();
    if (now - lastProjectDataRefreshAt > 3000) {
      lastProjectDataRefreshAt = now;
      refreshProjectDataOnly().catch(() => {});
    }
  }
}

function stageLabelFromStatus(stage) {
  const labels = {
    prepare: "動画準備",
    audio: "音声抽出",
    asr_prepare: "ASR準備",
    asr: "文字起こし",
    segment: "字幕分割",
    translate: "Gemini翻訳",
    translate_skip: "翻訳判定",
    quality: "品質チェック",
    done: "完了",
    failed: "失敗",
    running: "実行中",
  };
  return labels[stage] || "待機中";
}

function formatEta(seconds) {
  const value = Math.max(0, Math.round(seconds));
  if (value < 60) return `${value}秒`;
  return `${Math.floor(value / 60)}分${String(value % 60).padStart(2, "0")}秒`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function setStep(id, state) {
  const el = $(id);
  el.classList.remove("active", "done", "blocked");
  if (state) el.classList.add(state);
}

function updateSteps() {
  const hasProject = Boolean(currentProject);
  const hasSegments = hasProject && currentProject.segments && currentProject.segments.length > 0;
  const translated = hasSegments && currentProject.segments.some((segment) => segment.translated_text);
  const rendered = hasProject && currentProject.artifacts && (currentProject.artifacts.ass_path || currentProject.artifacts.srt_path || currentProject.artifacts.burned_mp4_path);
  setStep("stepProject", hasProject ? "done" : "active");
  setStep("stepTranscribe", !hasProject ? "blocked" : hasSegments ? "done" : "active");
  setStep("stepTranslate", !hasSegments ? "blocked" : translated || (currentProject.generation_status || {}).translate === false ? "done" : "active");
  setStep("stepEdit", !hasSegments ? "blocked" : "active");
  setStep("stepExport", !hasSegments ? "blocked" : rendered ? "done" : "active");
}

async function runPreflight() {
  const headers = apiKey() ? { "X-Gemini-Api-Key": apiKey() } : {};
  const data = await jsonFetch("/api/preflight", { headers });
  $("preflight").textContent = data.checks.map((c) => `${c.ok ? "OK" : "NG"} ${c.name}: ${c.detail}`).join("\n");
  const required = new Set(["ffmpeg", "ffprobe", "projects_writable", "subtitle_render_filter", "yt_dlp", "asr_engine"]);
  const failedRequired = data.checks.filter((c) => required.has(c.name) && !c.ok);
  const gemini = data.checks.find((c) => c.name === "gemini_api_key" || c.name === "gemini_connectivity");
  if (failedRequired.length > 0) {
    $("systemSummary").textContent = `${failedRequired.length}件の確認が必要`;
  } else if (gemini && !gemini.ok) {
    $("systemSummary").textContent = "基本OK / Gemini未確認";
  } else {
    const asr = data.checks.find((c) => c.name === "asr_engine");
    $("systemSummary").textContent = asr ? `基本OK / ASR: ${asr.detail}` : "基本OK";
  }
}

async function loadSettings() {
  const data = await jsonFetch("/api/settings");
  appSettings = data;
  renderApiKeyStatus();
}

function renderApiKeyStatus() {
  const status = appSettings.gemini_api_key || { configured: false, source: "missing" };
  $("apiKeyStatus").textContent = status.configured ? `保存済み: ${status.source}` : "未保存: 入力するとGemini翻訳に使用できます";
}

async function persistApiKeyIfNeeded() {
  const key = apiKey();
  if (!key || !$("apiKeyPersist").checked) return;
  const data = await jsonFetch("/api/settings/gemini-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: key }),
  });
  appSettings = data;
  $("apiKey").value = "";
  renderApiKeyStatus();
  await runPreflight();
  logActivity("Gemini APIキーを保存しました");
}

$("createProjectBtn").addEventListener("click", () => runAction(async () => {
  setStatus("動画を取り込み中。URLの場合はダウンロードと検証を行います", 0);
  setStage("running", "動画準備", 0);
  const form = new FormData();
  const file = $("fileInput").files[0];
  if (file) form.append("video_file", file);
  const localPath = $("localPath").value.trim();
  if (localPath) form.append("local_path", localPath);
  const data = await jsonFetch("/api/projects", { method: "POST", body: form });
  currentProject = data.project;
  renderProject(data.artifacts || {});
  setStatus("動画の読み込みが完了しました。字幕を作成できます", 0);
  logActivity(`動画を読み込みました: ${currentProject.video_name}`);
}, "動画を読み込み中"));

$("generateBtn").addEventListener("click", () => runAction(async () => {
  enableProjectButtons(false);
  await persistApiKeyIfNeeded();
  const data = await jsonFetch(`/api/projects/${currentProject.id}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preset: $("preset").value,
      source_lang: $("sourceLang").value,
      target_lang: $("targetLang").value,
      asr_engine: $("asrEngine").value,
      translate_mode: "auto",
      api_key: apiKey() || null,
    }),
  });
  watchJob(data.job_id, {
    onSucceeded: async () => {
      setStatus("字幕作成が完了しました", 100);
      logActivity("字幕作成が完了しました");
    },
  });
}, "字幕作成を開始しています"));

$("renderSubsBtn").addEventListener("click", () => runAction(async () => {
  if (!currentProject.segments || currentProject.segments.length === 0) {
    throw new Error("先に字幕を作成してください。出力する字幕がまだありません。");
  }
  const data = await jsonFetch(`/api/projects/${currentProject.id}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outputs: ["ass", "srt", "vtt", "bilingual_ass"] }),
  });
  currentProject = data.project;
  renderProject(data.artifacts || {});
  setStatus("字幕ファイル出力完了", 100);
  logActivity("字幕ファイルを書き出しました");
}, "字幕ファイル出力中"));

$("renderMp4Btn").addEventListener("click", () => runAction(async () => {
  if (!currentProject.segments || currentProject.segments.length === 0) {
    throw new Error("先に字幕を作成してください。焼き込む字幕がまだありません。");
  }
  const data = await jsonFetch(`/api/projects/${currentProject.id}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outputs: ["ass", "srt", "mp4"] }),
  });
  watchJob(data.job_id);
}, "MP4焼き込み開始中"));

$("video").addEventListener("timeupdate", updateCurrentCaption);
$("video").addEventListener("seeked", () => {
  updateCurrentCaption();
  if ($("segmentFilter").value === "current") renderSegments();
});

$("fileInput").addEventListener("change", () => {
  const file = $("fileInput").files[0];
  $("filePickerLabel").textContent = file ? file.name : "ファイルを選択";
});

$("segmentFilter").addEventListener("change", renderSegments);

["preset", "asrEngine", "sourceLang", "targetLang"].forEach((id) => {
  $(id).addEventListener("change", () => {
    updateSettingsSummary();
    enableProjectButtons(true);
  });
});

$("apiKey").addEventListener("change", () => {
  persistApiKeyIfNeeded().catch(showError);
  runPreflight().catch(showError);
});

$("clearApiKeyBtn").addEventListener("click", () => runAction(async () => {
  const data = await jsonFetch("/api/settings/gemini-key", { method: "DELETE" });
  appSettings = data;
  $("apiKey").value = "";
  renderApiKeyStatus();
  await runPreflight();
  logActivity("保存済みGemini APIキーを削除しました");
}, "保存キーを削除しています"));

$("apiKeyPersist").addEventListener("change", () => {
  const key = apiKey();
  if (key && $("apiKeyPersist").checked) persistApiKeyIfNeeded().catch(showError);
});

updateSteps();
updateSettingsSummary();
setStage("idle", "待機中", 0);
loadSettings().catch(showError);
runPreflight().catch(showError);
