// Custom User Documents for RAG
window.documentsAPI = {
  mode: 'file',
  elements: {
    list: () => document.getElementById('docList'),
    fileInput: () => document.getElementById('docFileInput'),
    filename: () => document.getElementById('docFileSelected'),
    titleInput: () => document.getElementById('docTitleInput'),
    textInput: () => document.getElementById('docTextInput'),
    typeSelect: () => document.getElementById('docTypeSelect'),
    descInput: () => document.getElementById('docDescInput'),
    submitBtn: () => document.getElementById('docSubmitBtn')
  },
  
  switchMode(newMode) {
    this.mode = newMode;
    document.getElementById('docFileTab').classList.toggle('active', newMode === 'file');
    document.getElementById('docTextTab').classList.toggle('active', newMode === 'text');
    document.getElementById('docFileMode').style.display = newMode === 'file' ? 'block' : 'none';
    document.getElementById('docTextMode').style.display = newMode === 'text' ? 'block' : 'none';
    this.validateForm();
  },

  validateForm() {
    const btn = this.elements.submitBtn();
    if (this.mode === 'file') {
      btn.disabled = !this.elements.fileInput().files.length;
    } else {
      const t = this.elements.titleInput().value.trim();
      const txt = this.elements.textInput().value.trim();
      btn.disabled = !(t && txt);
    }
  },

  setupListeners() {
    this.elements.titleInput()?.addEventListener('input', () => this.validateForm());
    this.elements.textInput()?.addEventListener('input', () => this.validateForm());
  },
  
  async loadList() {
    const listEl = this.elements.list();
    if (!listEl) return;

    try {
      const docs = await window.api.fetch('/documents');
      if (docs.length === 0) {
        listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center;">Нет загруженных эталонов</div>';
        return;
      }

      const corporateNorms = docs.filter(d => d.description && d.description.includes('Корпоративная норма'));
      const standardEtalons = docs.filter(d => !d.description || !d.description.includes('Корпоративная норма'));

      let html = '';

      if (corporateNorms.length > 0) {
        html += '<div class="doc-section-label" style="font-size:11px; color:var(--accent); font-weight:600; margin:8px 0 4px; text-transform:uppercase; letter-spacing:0.5px;">Корпоративные нормы (принятые риски)</div>';
        html += corporateNorms.map(doc => {
          const preview = doc.source_text
            ? (doc.source_text.length > 120 ? doc.source_text.slice(0, 120) + '...' : doc.source_text)
            : '';
          return `
          <div class="doc-item doc-item--corporate">
            <div class="doc-info">
              <span class="doc-name" title="${doc.filename}">${doc.filename}</span>
              ${preview ? `<div class="doc-preview">${preview}</div>` : ''}
              <div class="doc-meta">
                <span class="doc-tag doc-tag--corporate">${doc.contract_type === 'любой' ? 'любой (все договоры)' : doc.contract_type}</span>
                <span class="doc-tag">${doc.chunks_count} чанк(ов)</span>
              </div>
            </div>
            <button class="btn-icon" onclick="documentsAPI.deleteDoc('${doc.id}')" title="Удалить">✕</button>
          </div>`;
        }).join('');
      }

      if (standardEtalons.length > 0) {
        if (corporateNorms.length > 0) {
          html += '<div class="doc-section-label" style="font-size:11px; color:var(--text-muted); font-weight:600; margin:12px 0 4px; text-transform:uppercase; letter-spacing:0.5px;">Пользовательские эталоны</div>';
        }
        html += standardEtalons.map(doc => `
          <div class="doc-item">
            <div class="doc-info">
              <span class="doc-name" title="${doc.filename}">${doc.filename}</span>
              <div class="doc-meta">
                <span class="doc-tag">${doc.contract_type}</span>
                ${doc.description ? `<span>${doc.description}</span>` : ''}
              </div>
            </div>
            <button class="btn-icon" onclick="documentsAPI.deleteDoc('${doc.id}')" title="Удалить">✕</button>
          </div>
        `).join('');
      }

      listEl.innerHTML = html;
    } catch (e) {
      console.error('Failed to load user documents', e);
      listEl.innerHTML = '<div style="font-size:12px; color:var(--high);">Ошибка загрузки</div>';
    }
  },
  
  handleFileSelect() {
    const el = this.elements.fileInput();
    const nameEl = this.elements.filename();
    
    if (el.files.length > 0) {
      const name = el.files[0].name;
      const ext = name.split('.').pop().toLowerCase();
      if (!['pdf', 'docx'].includes(ext)) {
        alert('Только PDF и DOCX');
        el.value = '';
        nameEl.textContent = 'Выберите файл эталона';
      } else {
        nameEl.textContent = name;
      }
    } else {
      nameEl.textContent = 'Выберите файл эталона';
    }
    this.validateForm();
  },
  
  async submitUpload(btn) {
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Загрузка...';
    
    const type = this.elements.typeSelect().value;
    const desc = this.elements.descInput().value.trim();
    
    const formData = new FormData();
    formData.append('contract_type', type);
    formData.append('description', desc);
    
    let endpoint = '/documents/upload';

    if (this.mode === 'file') {
      formData.append('file', this.elements.fileInput().files[0]);
    } else {
      endpoint = '/documents/upload/text';
      formData.append('text', this.elements.textInput().value.trim());
      formData.append('title', this.elements.titleInput().value.trim());
    }
    
    try {
      await window.api.fetch(endpoint, {
        method: 'POST',
        body: formData
      });
      
      // Reset form
      if (this.mode === 'file') {
        this.elements.fileInput().value = '';
        this.elements.filename().textContent = 'Выберите файл эталона';
      } else {
        this.elements.titleInput().value = '';
        this.elements.textInput().value = '';
      }
      this.elements.typeSelect().value = 'любой';
      this.elements.descInput().value = '';
      this.validateForm();
      
      // Reload list
      await this.loadList();
    } catch (e) {
      alert('Ошибка: ' + e.message);
      this.validateForm();
    } finally {
      btn.textContent = originalText;
    }
  },
  
  async deleteDoc(id) {
    if (!confirm('Точно удалить этот эталон? Он перестанет учитываться при анализе.')) return;
    try {
      await window.api.fetch(`/documents/${id}`, { method: 'DELETE' });
      await this.loadList();
    } catch (e) {
      alert('Ошибка при удалении: ' + e.message);
    }
  }
};

// Initialize listeners on DOM load
document.addEventListener('DOMContentLoaded', () => {
  if (window.documentsAPI) window.documentsAPI.setupListeners();
});
