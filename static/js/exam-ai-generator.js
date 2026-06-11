/** Shared document filter + AI question generation for exam forms. */
window.ExamAIGenerator = {
  initDocFilters(levelSelId, catSelId, materialSelId) {
    const levelSel = document.getElementById(levelSelId);
    const catSel = document.getElementById(catSelId);
    const matSel = document.getElementById(materialSelId);
    if (!matSel) return;

    const apply = () => {
      const lvl = levelSel ? levelSel.value : '';
      const cat = catSel ? catSel.value : '';
      [...matSel.options].forEach(opt => {
        const matchLevel = !lvl || opt.dataset.level === lvl;
        const matchCat = !cat || opt.dataset.categoryId === cat;
        opt.hidden = !(matchLevel && matchCat);
      });
    };

    levelSel?.addEventListener('change', apply);
    catSel?.addEventListener('change', apply);
    apply();
  },

  selectedMaterialIds(materialSelId) {
    const sel = document.getElementById(materialSelId);
    if (!sel) return [];
    return [...sel.selectedOptions].map(o => o.value).filter(Boolean);
  },

  selectedQuestionTypes(form) {
    return [...form.querySelectorAll('input[name="question_types"]:checked')].map(i => i.value);
  },
};
