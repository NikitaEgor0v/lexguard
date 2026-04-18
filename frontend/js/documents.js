// Custom User Documents for RAG
window.documentsAPI = {
  elements: {
    list: () => document.getElementById('docList'),
    fileInput: () => document.getElementById('docFileInput'),
    filename: () => document.getElementById('docFileSelected'),
    typeSelect: () => document.getElementById('docTypeSelect'),
    descInput: () => document.getElementById('docDescInput'),
    submitBtn: () => document.getElementById('docSubmitBtn')
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
      
      listEl.innerHTML = docs.map(doc => `
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
    } catch (e) {
      console.error('Failed to load user documents', e);
      listEl.innerHTML = '<div style="font-size:12px; color:var(--high);">Ошибка загрузки</div>';
    }
  },
  
  handleFileSelect() {
    const el = this.elements.fileInput();
    const nameEl = this.elements.filename();
    const btn = this.elements.submitBtn();
    
    if (el.files.length > 0) {
      const name = el.files[0].name;
      const ext = name.split('.').pop().toLowerCase();
      if (!['pdf', 'docx'].includes(ext)) {
        alert('Только PDF и DOCX');
        el.value = '';
        nameEl.textContent = 'Выберите файл эталона';
        btn.disabled = true;
        return;
      }
      nameEl.textContent = name;
      btn.disabled = false;
    } else {
      nameEl.textContent = 'Выберите файл эталона';
      btn.disabled = true;
    }
  },
  
  async submitUpload(btn) {
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Загрузка...';
    
    const file = this.elements.fileInput().files[0];
    const type = this.elements.typeSelect().value;
    const desc = this.elements.descInput().value.trim();
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('contract_type', type);
    formData.append('description', desc);
    
    try {
      await window.api.fetch('/documents/upload', {
        method: 'POST',
        body: formData
      });
      
      // Reset form
      this.elements.fileInput().value = '';
      this.elements.filename().textContent = 'Выберите файл эталона';
      this.elements.typeSelect().value = 'иной';
      this.elements.descInput().value = '';
      
      // Reload list
      await this.loadList();
    } catch (e) {
      alert('Ошибка: ' + e.message);
    } finally {
      btn.textContent = originalText;
      if (!this.elements.fileInput().files[0]) btn.disabled = true;
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
