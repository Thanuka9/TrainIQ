/**
 * Custom exam question builder — duplicate, structured shortcut, live count.
 */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const questionsContainer = document.getElementById("questionsContainer");
    const addQuestionBtn = document.getElementById("addQuestionBtn");
    const addStructuredBtn = document.getElementById("addStructuredBtn");
    const qCountBadge = document.getElementById("qCountBadge");
    const questionSummary = document.getElementById("questionSummary");
    const defaultCategoryId = () => document.getElementById("category_id")?.value || "";
    let questionCount = 0;

    function updateCount() {
      const n = questionsContainer.querySelectorAll("[data-question-id]").length;
      if (qCountBadge) qCountBadge.textContent = `(${n})`;
      if (questionSummary) questionSummary.textContent = n === 1 ? "1 question" : `${n} questions`;
      document.querySelectorAll(".exam-step").forEach((el) => {
        el.classList.toggle("tiq-badge-info", el.dataset.step === "2" && n > 0);
        el.classList.toggle("exam-step--active", el.dataset.step === "2" && n > 0);
      });
    }

    function addQuestionCard(prefill, opts) {
      opts = opts || {};
      questionCount++;
      const qid = questionCount;
      const questionDiv = document.createElement("div");
      questionDiv.className = "tiq-card tiq-reveal tiq-revealed";
      questionDiv.setAttribute("data-question-id", qid);

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

      const qtype = opts.forceType || prefill?.question_type || "single_choice";
      const choices = Array.isArray(prefill?.choices)
        ? prefill.choices.join(", ")
        : prefill?.choices || "";
      const correct = prefill?.correct_answer || "";
      const ref = qtype === "structured" ? correct : "";
      const qtext = (prefill?.question_text || "").replace(/"/g, "&quot;");

      questionDiv.innerHTML = `
        <div class="tiq-card-header">
          <div class="tiq-card-title">Question #${questionsContainer.children.length + 1}</div>
          <div class="tiq-flex" style="gap:0.35rem;">
            <button type="button" class="tiq-btn tiq-btn-ghost tiq-btn-sm duplicate-question-btn" title="Duplicate"><i class="fas fa-copy"></i></button>
            <button type="button" class="tiq-btn tiq-btn-danger tiq-btn-sm remove-question-btn" title="Remove"><i class="fas fa-trash-alt"></i></button>
          </div>
        </div>
        <div class="tiq-card-body">
          <div class="tiq-form-group">
            <label class="tiq-label">Question Type</label>
            <select name="questions[${qid}][question_type]" class="tiq-select q-type-select">
              <option value="single_choice" ${qtype === "single_choice" ? "selected" : ""}>Single Choice</option>
              <option value="multiple_choice" ${qtype === "multiple_choice" ? "selected" : ""}>Multiple Choice (MSQ)</option>
              <option value="structured" ${qtype === "structured" ? "selected" : ""}>Structured (Short Answer)</option>
            </select>
          </div>
          <div class="tiq-form-group">
            <label class="tiq-label">Question Text</label>
            <textarea name="questions[${qid}][question_text]" class="tiq-textarea" rows="2" required>${(prefill?.question_text || "").replace(/</g, "&lt;")}</textarea>
          </div>
          <div class="q-upload-choices" style="${qtype === "structured" ? "display:none" : ""}">
            <div class="tiq-form-group">
              <label class="tiq-label">Choices (comma-separated)</label>
              <input type="text" name="questions[${qid}][choices]" class="tiq-input q-choices-input" value="${choices.replace(/"/g, "&quot;")}" placeholder="Option A, Option B, Option C, Option D" />
            </div>
            <div class="tiq-form-group">
              <label class="tiq-label">Correct Answer</label>
              <input type="text" name="questions[${qid}][correct_answer]" class="tiq-input q-correct-input" value="${qtype !== "structured" ? correct.replace(/"/g, "&quot;") : ""}" />
            </div>
          </div>
          <div class="q-upload-structured" style="${qtype === "structured" ? "" : "display:none"}">
            <div class="tiq-form-group">
              <label class="tiq-label">Reference Answer</label>
              <textarea name="questions[${qid}][reference_answer]" class="tiq-textarea" rows="2">${ref.replace(/</g, "&lt;")}</textarea>
            </div>
          </div>
          <div class="tiq-form-group">
            <label class="tiq-label">Category</label>
            <select name="questions[${qid}][category_id]" class="tiq-select" required>${categoryOptionsHtml}</select>
          </div>
        </div>
      `;

      questionDiv.querySelector(".remove-question-btn").addEventListener("click", () => {
        questionDiv.remove();
        renumberCards();
        updateCount();
      });

      questionDiv.querySelector(".duplicate-question-btn").addEventListener("click", () => {
        const typeSel = questionDiv.querySelector(".q-type-select");
        const dup = {
          question_type: typeSel.value,
          question_text: questionDiv.querySelector(`textarea[name="questions[${qid}][question_text]"]`)?.value,
          choices: questionDiv.querySelector(".q-choices-input")?.value,
          correct_answer: questionDiv.querySelector(".q-correct-input")?.value,
          category_id: questionDiv.querySelector(`select[name="questions[${qid}][category_id]"]`)?.value,
        };
        if (typeSel.value === "structured") {
          dup.correct_answer = questionDiv.querySelector(`textarea[name="questions[${qid}][reference_answer]"]`)?.value;
        }
        addQuestionCard(dup);
      });

      questionDiv.querySelector(".q-type-select").addEventListener("change", function () {
        toggleUploadQType(this);
      });

      questionsContainer.appendChild(questionDiv);
      toggleUploadQType(questionDiv.querySelector(".q-type-select"));
      updateCount();
    }

    function renumberCards() {
      questionsContainer.querySelectorAll("[data-question-id]").forEach((card, i) => {
        const title = card.querySelector(".tiq-card-title");
        if (title) title.textContent = `Question #${i + 1}`;
      });
    }

    addQuestionBtn?.addEventListener("click", () => addQuestionCard());
    addStructuredBtn?.addEventListener("click", () => addQuestionCard(null, { forceType: "structured" }));

    addQuestionCard();

    const form = document.getElementById("uploadExamForm");
    form?.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!questionsContainer.querySelector("[data-question-id]")) {
        alert("Add at least one question.");
        return;
      }
      const fd = new FormData(form);
      fetch(form.action, { method: "POST", body: fd })
        .then(async (res) => {
          if (res.ok) return res.json();
          throw new Error("Create exam failed:\n" + (await res.text()));
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
          else window.location.href = form.dataset.redirect || "/exams";
        })
        .catch((err) => {
          console.error(err);
          alert(err.message);
        });
    });
  });
})();
