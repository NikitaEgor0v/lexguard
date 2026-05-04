// Main Application logic & Orchestration
window.app = {
  init() {
    this.bindEvents();
    window.auth.init();
    window.upload.init();
    this.checkStatus();
    setInterval(() => this.checkStatus(), 30000);
  },
  
  bindEvents() {
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
      chatInput.addEventListener('input', e => window.chat.autoResize(e.target));
      chatInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          window.chat.sendMessage();
        }
      });
    }
  },

  async checkStatus() {
    try {
      const d = await window.api.fetch('/status');
      const dot = document.getElementById('statusDot');
      const txt = document.getElementById('statusText');
      if (d.ollama === 'running' && d.model_available) {
        dot.className = 'status-dot online';
        txt.textContent = `${d.model || 'модель'} · ${d.rag?.norms_count || 0} норм в RAG`;
      } else if (d.ollama === 'running') {
        dot.className = 'status-dot';
        txt.textContent = 'ollama запущен, модель не найдена';
      } else {
        dot.className = 'status-dot error';
        txt.textContent = 'ollama недоступен';
      }
    } catch {
      const dot = document.getElementById('statusDot');
      const txt = document.getElementById('statusText');
      if(dot) dot.className = 'status-dot error';
      if(txt) txt.textContent = 'сервер недоступен';
    }
  },

  showError(msg) {
    const box = document.getElementById('errorBox');
    if(box) {
      box.textContent = msg;
      box.classList.add('visible');
    }
  },

  hideError() {
    const box = document.getElementById('errorBox');
    if(box) box.classList.remove('visible');
  },

  async loadExistingAnalysis(analysis_id) {
    try {
      const data = await window.api.fetch(`/analyze/${analysis_id}`);
      
      if (data.status === 'failed') {
        // Analysis was marked as failed (e.g. Celery crash detected by heartbeat)
        const msg = data.message || 'Произошёл сбой при анализе. Попробуйте загрузить документ снова.';
        this.showError(msg);
        if (window.historyAPI) window.historyAPI.loadList();
        return;
      }

      if (data.status === 'processing') {
        window.upload.clearSelection();
        document.getElementById('uploadZone').style.display = 'none';
        const sel = document.getElementById('fileSelected');
        sel.classList.add('visible');
        document.getElementById('fileExt').textContent = '...';
        document.getElementById('fileName').textContent = data.filename || 'Идет анализ...';
        
        // Hide result sections
        document.getElementById('resultsSection').style.display = 'none';
        document.getElementById('summarySection').style.display = 'none';
        document.getElementById('chatSection').style.display = 'none';
        document.getElementById('emptyState').style.display = 'flex';
        
        window.analysis.setLoading(true);
        
        try {
          const result = await window.analysis.pollResult(analysis_id);
          if (!result) return; // Polling cancelled
          window.analysis.renderResults(result);
          if (window.historyAPI) window.historyAPI.loadList();
          document.getElementById('analyzeBtn').style.display = 'none';
          document.getElementById('progressWrap').classList.remove('visible');
          document.getElementById('loadingSteps').classList.remove('visible');
        } catch (e) {
          this.showError('Ошибка ожидания: ' + e.message);
          window.analysis.setLoading(false);
        }
        return;
      }
      
      window.upload.clearSelection();
      
      // Hide loading sections
      document.getElementById('analyzeBtn').style.display = 'none';
      document.getElementById('progressWrap').classList.remove('visible');
      document.getElementById('loadingSteps').classList.remove('visible');
      
      window.analysis.renderResults(data);
      
      // Attempt to load associated chat session (assume 1 session per analysis for simplicity)
      const sessions = await window.api.fetch('/chat/sessions?limit=50');
      const session = sessions.items.find(s => s.analysis_id === analysis_id);
      if (session) {
        const fullSession = await window.api.fetch(`/chat/session/${session.session_id}`);
        window.chat.restoreSession(fullSession);
      } else {
        document.getElementById('chatSection').style.display = 'none';
      }
    } catch (e) {
      this.showError('Не удалось загрузить анализ: ' + e.message);
    }
  }
};

document.addEventListener('DOMContentLoaded', () => window.app.init());
