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
      window.upload.clearSelection();
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
