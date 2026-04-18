// Upload & UI State
window.upload = {
  currentFile: null,

  init() {
    const fileInput = document.getElementById('fileInput');
    const zone = document.getElementById('uploadZone');
    
    if (!fileInput || !zone) return;

    fileInput.addEventListener('change', e => {
      const file = e.target.files[0];
      if (file) this.selectFile(file);
    });

    zone.addEventListener('dragover', e => { 
      e.preventDefault(); 
      zone.classList.add('dragover'); 
    });
    
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    
    zone.addEventListener('drop', e => {
      e.preventDefault(); 
      zone.classList.remove('dragover');
      const file = e.dataTransfer.files[0];
      if (file) this.selectFile(file);
    });

    const fileRemoveBtn = document.getElementById('fileRemove');
    if (fileRemoveBtn) {
      fileRemoveBtn.addEventListener('click', () => this.clearSelection());
    }
  },

  selectFile(file) {
    const allowed = ['.pdf', '.docx'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!allowed.includes(ext)) {
      window.app.showError('Поддерживаются только PDF и DOCX файлы');
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      window.app.showError('Файл слишком большой (максимум 15 МБ)');
      return;
    }
    
    this.currentFile = file;
    window.app.hideError();
    
    document.getElementById('uploadZone').style.display = 'none';
    const sel = document.getElementById('fileSelected');
    sel.classList.add('visible');
    
    document.getElementById('fileExt').textContent = ext.replace('.', '').toUpperCase();
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('analyzeBtn').disabled = false;
  },

  clearSelection() {
    this.currentFile = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('fileSelected').classList.remove('visible');
    document.getElementById('uploadZone').style.display = 'block';
    
    // Also reset progress and buttons if analysis wasn't complete
    document.getElementById('analyzeBtn').disabled = true;
    document.getElementById('analyzeBtn').style.display = 'flex';
    document.getElementById('progressWrap').classList.remove('visible');
    window.app.hideError();
  }
};
