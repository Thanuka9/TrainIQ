/**
 * AI exam create flow — generate then submit (shared question card pattern).
 */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const questionsContainer = document.getElementById("questionsContainer");
    const submitBtn = document.getElementById("submitAiExam");
    const defaultCategoryId = () => document.getElementById("category_id")?.value || "";
    let questionCount = 0;

    function setSubmitEnabled(on) {
      if (submitBtn) submitBtn.disabled = !on;
    }

    function addQuestionCard(prefill) {
      questionCount++;
      const questionDiv = document.createElement("div");
      questionDiv.className = "tiq-card tiq-reveal tiq-revealed";
      questionDiv.setAttribute("data-question-id", questionCount);

      let resolvedCategoryId = prefill?.category_id;
      if (!resolvedCategoryId && prefill?.category) {
        const catObj = (window.CATEGORIES || []).find(
          (c) => c.name.toLowerCase() === prefill.category.toLowerCase().trim()
        );
        if (catObj) resolvedCategoryId = String(catObj.id);
      }
      if (!resolvedCategoryId) resolvedCategoryId = defaultCategoryId();

      let categoryOptionsHtml = '<option value="">Select Category</option>';
      (window.CATEGORIES || []).forEach((cat) => {
        const sel = String(resolvedCategoryId) === String(cat.id) ? "selected" : "";
        categoryOptionsHtml += `<option value="${cat.id}" ${sel}>${cat.name}</option>`;
      });

      const qtype = prefill?.question_type || "single_choice";
      const choices = Array.isArray(prefill?.choices) ? prefill.choices.join(", ") : prefill?.choices || "";
      const correct = prefill?.correct_answer || "";
      const ref = qtype === "structured" ? correct : "";

      questionDiv.innerHTML = `
        <div class="tiq-card-header">
          <div class="tiq-card-title">Question #${questionCount}</div>
          <button type="button" class="tiq-btn tiq-btn-danger tiq-btn-sm remove-question-btn"><i class="fas fa-trash-alt"></i></button>
        </div>
        <div class="tiq-card-body">
          <div class="tiq-form-group">
            <label class="tiq-label">Question Type</label>
            <select name="questions[${questionCount}][question_type]" class="tiq-select q-type-select">
              <option value="single_choice" ${qtype === "single_choice" ? "selected" : ""}>Single Choice</option>
              <option value="multiple_choice" ${qtype === "multiple_choice" ? "selected" : ""}>Multiple Choice</option>
              <option value="structured" ${qtype === "structured" ? "selected" : ""}>Structured</option>
            </select>
          </div>
          <div class="tiq-form-group">
            <label class="tiq-label">Question Text</label>
            <input type="text" name="questions[${questionCount}][question_text]" class="tiq-input" value="${(prefill?.question_text || "").replace(/"/g, "&quot;")}" required />
          </div>
          <div class="q-upload-choices" style="${qtype === "structured" ? "display:none" : ""}">
            <div class="tiq-form-group">
              <label class="tiq-label">Choices</label>
              <input type="text" name="questions[${questionCount}][choices]" class="tiq-input q-choices-input" value="${choices.replace(/"/g, "&quot;")}" />
            </div>
            <div class="tiq-form-group">
              <label class="tiq-label">Correct Answer</label>
              <input type="text" name="questions[${questionCount}][correct_answer]" class="tiq-input q-correct-input" value="${qtype !== "structured" ? correct.replace(/"/g, "&quot;") : ""}" />
            </div>
          </div>
          <div class="q-upload-structured" style="${qtype === "structured" ? "" : "display:none"}">
            <div class="tiq-form-group">
              <label class="tiq-label">Reference Answer</label>
              <textarea name="questions[${questionCount}][reference_answer]" class="tiq-textarea" rows="2">${ref.replace(/</g, "&lt;")}</textarea>
            </div>
          </div>
          <div class="tiq-form-group">
            <label class="tiq-label">Category</label>
            <select name="questions[${questionCount}][category_id]" class="tiq-select" required>${categoryOptionsHtml}</select>
          </div>
        </div>
      `;

      questionDiv.querySelector(".remove-question-btn").addEventListener("click", () => {
        questionDiv.remove();
        setSubmitEnabled(questionsContainer.querySelector("[data-question-id]") !== null);
      });
      questionDiv.querySelector(".q-type-select").addEventListener("change", function () {
        toggleUploadQType(this);
      });
      questionsContainer.appendChild(questionDiv);
      toggleUploadQType(questionDiv.querySelector(".q-type-select"));
      setSubmitEnabled(true);
    }

    if (typeof ExamAIGenerator !== "undefined") {
      ExamAIGenerator.initDocFilters("upload_ai_filter_level", "upload_ai_filter_category", "upload_material_ids");
    }

    document.getElementById("course_id")?.addEventListener("change", (e) => {
      const matSel = document.getElementById("upload_material_ids");
      if (!matSel) return;
      [...matSel.options].forEach((o) => {
        o.selected = o.value === e.target.value;
      });
    });

    document.getElementById("uploadAiGenerateBtn")?.addEventListener("click", async () => {
      const btn = document.getElementById("uploadAiGenerateBtn");
      const materialIds = ExamAIGenerator.selectedMaterialIds("upload_material_ids");
      if (!materialIds.length) {
        alert("Select at least one source course.");
        return;
      }
      const types = [...document.querySelectorAll("#uploadAiTypes input:checked")].map((i) => i.value);
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating…';
      try {
        const res = await fetch(window.AI_PREVIEW_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
          body: JSON.stringify({
            material_ids: materialIds,
            count: parseInt(document.getElementById("ai_question_count").value, 10) || 5,
            question_types: types,
            exam_title: document.getElementById("title")?.value || "New Exam",
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Generation failed");
        questionsContainer.innerHTML = "";
        questionCount = 0;
        (data.questions || []).forEach((q) => addQuestionCard(q));
        if (!data.questions?.length) alert("AI returned no questions.");
      } catch (err) {
        alert(err.message || "Could not generate questions.");
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-magic"></i> Generate with AI';
      }
    });

    const form = document.getElementById("uploadExamForm");
    form?.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!questionsContainer.querySelector("[data-question-id]")) {
        alert("Generate questions with AI first, or go back and use Custom Exam.");
        return;
      }
      const fd = new FormData(form);
      fetch(form.action, { method: "POST", body: fd })
        .then(async (res) => {
          if (res.ok) return res.json();
          throw new Error(await res.text());
        })
        .then((createJson) => {
          if (!createJson.add_questions_url) throw new Error(createJson.error || "Missing add_questions_url");
          return fetch(createJson.add_questions_url, { method: "POST", body: fd });
        })
        .then(async (res2) => {
          if (res2.ok) return res2.json();
          throw new Error("Add questions failed:\n" + (await res2.text()));
        })
        .then((qJson) => {
          if (qJson.errors?.length) alert("Some questions failed:\n" + qJson.errors.join("\n"));
          window.location.href = window.EXAM_LIST_URL;
        })
        .catch((err) => alert(err.message));
    });
  });
})();
