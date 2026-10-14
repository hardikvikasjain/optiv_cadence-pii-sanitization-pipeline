// Cadence Financial Group - PII Sanitization Studio Interactive Client

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const browseBtn = document.getElementById("browseBtn");
  const selectedFileBanner = document.getElementById("selectedFileBanner");
  const selectedFileName = document.getElementById("selectedFileName");
  const selectedFileSize = document.getElementById("selectedFileSize");
  const clearFileBtn = document.getElementById("clearFileBtn");
  const processBtn = document.getElementById("processBtn");
  const presetBtns = document.querySelectorAll(".preset-btn");

  const progressCard = document.getElementById("progressCard");
  const progressBar = document.getElementById("progressBar");
  const progressStepTitle = document.getElementById("progressStepTitle");
  const progressStepDesc = document.getElementById("progressStepDesc");
  const resultsHub = document.getElementById("resultsHub");

  // State
  let activeFile = null;
  let activePreset = null;
  let currentResults = null;
  let isMasked = true;

  // File drag & drop handling
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  browseBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  function handleFileSelected(file) {
    const ext = file.name.split(".").pop().toLowerCase();
    if (!["pdf", "docx", "pptx"].includes(ext)) {
      alert("Please upload a .docx, .pptx, or .pdf document.");
      return;
    }

    activeFile = file;
    activePreset = null;
    presetBtns.forEach((b) => b.classList.remove("active"));

    selectedFileName.textContent = file.name;
    const sizeKB = (file.size / 1024).toFixed(1);
    selectedFileSize.textContent = sizeKB > 1024 ? `${(sizeKB / 1024).toFixed(2)} MB` : `${sizeKB} KB`;

    document.querySelector(".dropzone-content").style.display = "none";
    selectedFileBanner.style.display = "flex";
  }

  clearFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    resetFileSelection();
  });

  function resetFileSelection() {
    activeFile = null;
    activePreset = null;
    fileInput.value = "";
    document.querySelector(".dropzone-content").style.display = "block";
    selectedFileBanner.style.display = "none";
    presetBtns.forEach((b) => b.classList.remove("active"));
  }

  // Preset buttons
  presetBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const presetId = btn.getAttribute("data-preset");
      if (activePreset === presetId) {
        resetFileSelection();
      } else {
        resetFileSelection();
        activePreset = presetId;
        btn.classList.add("active");
      }
    });
  });

  // Execute pipeline
  processBtn.addEventListener("click", async () => {
    if (!activeFile && !activePreset) {
      alert("Please upload a document (.docx, .pptx, .pdf) or select one of the Cadence presets.");
      return;
    }

    // Prepare FormData
    const formData = new FormData();
    if (activeFile) {
      formData.append("file", activeFile);
    } else if (activePreset) {
      formData.append("preset_id", activePreset);
    }

    // UI Progress State
    resultsHub.style.display = "none";
    progressCard.style.display = "block";
    processBtn.disabled = true;
    animateProgress();

    try {
      const response = await fetch("/api/process", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Pipeline execution failed");
      }

      const data = await response.json();
      currentResults = data;

      // Finish progress and render
      progressBar.style.width = "100%";
      document.getElementById("step4").classList.add("active");

      setTimeout(() => {
        progressCard.style.display = "none";
        processBtn.disabled = false;
        renderResults(data);
      }, 400);

    } catch (err) {
      alert(`Error during processing: ${err.message}`);
      progressCard.style.display = "none";
      processBtn.disabled = false;
    }
  });

  function animateProgress() {
    progressBar.style.width = "20%";
    progressStepTitle.textContent = "1. Ingesting & Extracting Structure...";
    progressStepDesc.textContent = "Parsing paragraphs, slide shapes, tables, and applying OCR if scanned.";
    document.getElementById("step1").classList.add("active");
    document.getElementById("step2").classList.remove("active");
    document.getElementById("step3").classList.remove("active");
    document.getElementById("step4").classList.remove("active");

    setTimeout(() => {
      progressBar.style.width = "50%";
      progressStepTitle.textContent = "2. Hybrid PII Detection Engine Running...";
      progressStepDesc.textContent = "Matching regex patterns for IDs/emails/phones and spaCy NER for person names.";
      document.getElementById("step2").classList.add("active");
    }, 1200);

    setTimeout(() => {
      progressBar.style.width = "80%";
      progressStepTitle.textContent = "3. Right-to-Left Redaction Gate...";
      progressStepDesc.textContent = "Executing character offset replacements to ensure zero coordinate-shifting.";
      document.getElementById("step3").classList.add("active");
    }, 2400);
  }

  function renderResults(data) {
    resultsHub.style.display = "block";

    // 1. Safety Gate Banner
    const safetyBanner = document.getElementById("safetyBanner");
    const safetyTitle = document.getElementById("safetyTitle");
    const safetyDesc = document.getElementById("safetyDesc");
    const safetyBadge = document.getElementById("safetyBadge");

    if (data.safety_gate.status === "PASS") {
      safetyBanner.className = "safety-banner pass";
      safetyTitle.textContent = "PRIVACY SAFETY GATE: PASSED";
      safetyDesc.textContent = "100% local execution. High confidence extraction across all segments. Certified safe for downstream LLM ingestion.";
      safetyBadge.textContent = "CERTIFIED SAFE";
    } else {
      safetyBanner.className = "safety-banner warning";
      safetyTitle.textContent = "PRIVACY SAFETY GATE: REVIEW REQUIRED";
      safetyDesc.textContent = `${data.safety_gate.warnings_count} extraction/OCR warning(s) detected. Manual inspection required before releasing to downstream LLMs.`;
      safetyBadge.textContent = "REVIEW REQUIRED";
    }

    // 2. Metrics
    document.getElementById("metricSegments").textContent = data.segments_total.toLocaleString();
    document.getElementById("metricPii").textContent = data.pii_total.toLocaleString();
    document.getElementById("metricTime").textContent = `${data.processing_time_sec}s`;
    document.getElementById("metricFileType").textContent = data.file_type;
    document.getElementById("metricFileSize").textContent = data.file_size_formatted;

    // 3. Breakdown Chips
    const breakdownChips = document.getElementById("breakdownChips");
    breakdownChips.innerHTML = "";

    const typeIcons = {
      PERSON_NAME: "fa-user",
      EMAIL: "fa-envelope",
      PHONE: "fa-phone",
      ACCOUNT_OR_EMPLOYEE_ID: "fa-id-badge",
      IP_ADDRESS: "fa-network-wired",
    };

    const typeClasses = {
      PERSON_NAME: "chip-person",
      EMAIL: "chip-email",
      PHONE: "chip-phone",
      ACCOUNT_OR_EMPLOYEE_ID: "chip-id",
      IP_ADDRESS: "chip-ip",
    };

    for (const [t, count] of Object.entries(data.pii_by_type)) {
      const chip = document.createElement("div");
      chip.className = `chip ${typeClasses[t] || "chip-person"}`;
      chip.innerHTML = `<i class="fa-solid ${typeIcons[t] || "fa-tag"}"></i> ${t.replace(/_/g, " ")} <span class="chip-count">${count}</span>`;
      breakdownChips.appendChild(chip);
    }

    // 4. Download Suite Links
    const nativeBtn = document.getElementById("downloadNativeBtn");
    nativeBtn.href = data.downloads.native;
    nativeBtn.download = data.downloads.native_filename;
    document.getElementById("downloadNativeTitle").textContent = `Download Sanitized .${data.file_type.toLowerCase()}`;
    document.getElementById("downloadNativeFormat").textContent = `Redacted Document (${data.downloads.native_filename})`;

    const txtBtn = document.getElementById("downloadTextBtn");
    txtBtn.href = data.downloads.text;
    txtBtn.download = `${data.filename}.sanitized.txt`;

    const csvBtn = document.getElementById("downloadCsvBtn");
    csvBtn.href = data.downloads.csv;
    csvBtn.download = "pii_findings.csv";

    const jsonBtn = document.getElementById("downloadJsonBtn");
    jsonBtn.href = data.downloads.json;
    jsonBtn.download = "pii_findings.json";

    // 5. Render Comparison List
    renderComparison(data.preview_pairs);

    // 6. Render Findings Table
    renderFindingsTable(data.findings);

    // 7. Render Telemetry Warnings
    const warningsList = document.getElementById("warningsList");
    warningsList.innerHTML = "";
    if (data.safety_gate.warnings_sample && data.safety_gate.warnings_sample.length > 0) {
      data.safety_gate.warnings_sample.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = w;
        warningsList.appendChild(li);
      });
      if (data.safety_gate.warnings_count > data.safety_gate.warnings_sample.length) {
        const li = document.createElement("li");
        li.textContent = `... and ${data.safety_gate.warnings_count - data.safety_gate.warnings_sample.length} additional flagged locations.`;
        warningsList.appendChild(li);
      }
    } else {
      warningsList.innerHTML = "<li class='text-muted'>No extraction warnings. Document parsed cleanly.</li>";
    }

    // Smooth scroll to results
    resultsHub.scrollIntoView({ behavior: "smooth" });
  }

  function renderComparison(pairs) {
    const list = document.getElementById("comparisonList");
    list.innerHTML = "";

    if (!pairs || pairs.length === 0) {
      list.innerHTML = "<p class='text-muted'>No text segments available for comparison.</p>";
      return;
    }

    pairs.forEach((p) => {
      const item = document.createElement("div");
      item.className = "comparison-item";
      item.innerHTML = `
        <span class="comp-loc-badge"><i class="fa-solid fa-map-pin"></i> ${p.location}</span>
        <div class="comp-row">
          <div class="comp-box">${p.raw_html}</div>
          <div class="comp-box" style="color: #6ee7b7; font-family: var(--font-mono); font-size: 13px;">${escapeHtml(p.redacted_text)}</div>
        </div>
      `;
      list.appendChild(item);
    });
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function renderFindingsTable(findings) {
    const tbody = document.getElementById("findingsTableBody");
    tbody.innerHTML = "";

    const query = document.getElementById("tableSearch").value.toLowerCase();
    const typeFilter = document.getElementById("typeFilter").value;

    const filtered = (findings || []).filter((f) => {
      const matchType = typeFilter === "ALL" || f["PII Type"] === typeFilter;
      const textMatch =
        f["Entity Text"].toLowerCase().includes(query) ||
        f["Location"].toLowerCase().includes(query) ||
        f["PII Type"].toLowerCase().includes(query);
      return matchType && textMatch;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-muted" style="text-align: center; padding: 24px;">No findings matching search criteria.</td></tr>`;
      return;
    }

    filtered.forEach((f, idx) => {
      const tr = document.createElement("tr");
      const val = isMasked ? f["Masked Text"] : f["Entity Text"];
      tr.innerHTML = `
        <td>${idx + 1}</td>
        <td><strong>${f["Location"]}</strong></td>
        <td><span class="chip chip-person" style="font-size: 11px;">${f["PII Type"]}</span></td>
        <td><code class="val-pill">${escapeHtml(val)}</code></td>
        <td><span class="badge" style="background: rgba(255,255,255,0.06); font-size: 11px;">${f["Method"]}</span></td>
        <td><span class="text-muted">${(f["Confidence"] * 100).toFixed(0)}%</span></td>
      `;
      tbody.appendChild(tr);
    });
  }

  // Search & Filter Listeners
  document.getElementById("tableSearch").addEventListener("input", () => {
    if (currentResults) renderFindingsTable(currentResults.findings);
  });

  document.getElementById("typeFilter").addEventListener("change", () => {
    if (currentResults) renderFindingsTable(currentResults.findings);
  });

  document.getElementById("toggleMaskBtn").addEventListener("click", () => {
    isMasked = !isMasked;
    const btn = document.getElementById("toggleMaskBtn");
    btn.innerHTML = isMasked
      ? `<i class="fa-solid fa-eye-slash"></i> <span>Toggle Mask PII</span>`
      : `<i class="fa-solid fa-eye"></i> <span>Masking: OFF</span>`;
    if (currentResults) renderFindingsTable(currentResults.findings);
  });

  // Tab switching
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");

      tabBtns.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(targetTab).classList.add("active");
    });
  });

  // Direct Save to Windows Downloads Folder
  async function triggerSaveToDownloads() {
    if (!currentResults) return;
    const toast = document.getElementById("saveToast");
    toast.style.display = "flex";
    toast.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving directly into your Windows Downloads folder...`;

    try {
      const res = await fetch(`/api/save-to-downloads/${currentResults.job_id}`, { method: "POST" });
      const resData = await res.json();
      if (res.ok) {
        toast.innerHTML = `<i class="fa-solid fa-circle-check"></i> <div><strong>File Saved Locally!</strong> Written directly to: <code class="code-pill">${resData.saved_path}</code></div>`;
      } else {
        toast.innerHTML = `<i class="fa-solid fa-circle-xmark text-rose"></i> Save failed: ${resData.detail}`;
      }
    } catch (err) {
      toast.innerHTML = `<i class="fa-solid fa-circle-xmark text-rose"></i> Error saving file: ${err.message}`;
    }
  }

  document.getElementById("saveToDownloadsBtn").addEventListener("click", triggerSaveToDownloads);
  document.getElementById("modalSaveToDownloadsBtn").addEventListener("click", triggerSaveToDownloads);

  // In-Browser Full Document Viewer Modal
  const viewerModal = document.getElementById("viewerModal");
  const closeViewerModalBtn = document.getElementById("closeViewerModalBtn");

  document.getElementById("openViewerBtn").addEventListener("click", async () => {
    if (!currentResults) return;
    viewerModal.style.display = "flex";
    const modalBody = document.getElementById("viewerModalBody");
    modalBody.innerHTML = `<div class="viewer-loading"><i class="fa-solid fa-spinner fa-spin"></i> Loading sanitized content...</div>`;

    try {
      const res = await fetch(`/api/view-sanitized/${currentResults.job_id}`);
      const docData = await res.json();

      document.getElementById("viewerModalTitle").textContent = `Sanitized Document: ${docData.filename}`;
      modalBody.innerHTML = "";

      if (docData.sections && docData.sections.length > 0) {
        docData.sections.forEach((sec) => {
          const card = document.createElement("div");
          card.className = "viewer-section-card";
          card.innerHTML = `
            <div class="viewer-section-title"><i class="fa-solid fa-bookmark"></i> ${escapeHtml(sec.title)}</div>
            <div class="viewer-section-text">${escapeHtml(sec.content)}</div>
          `;
          modalBody.appendChild(card);
        });
      } else {
        modalBody.innerHTML = `<pre class="viewer-section-text">${escapeHtml(docData.full_text)}</pre>`;
      }
    } catch (err) {
      modalBody.innerHTML = `<div class="text-rose" style="padding: 20px;">Failed to load document content: ${err.message}</div>`;
    }
  });

  closeViewerModalBtn.addEventListener("click", () => {
    viewerModal.style.display = "none";
  });

  viewerModal.addEventListener("click", (e) => {
    if (e.target === viewerModal) {
      viewerModal.style.display = "none";
    }
  });
});
