// Interactive AI Chat logic
window.chat = {
  sessionId: null,
  waiting: false,
  chipsVisible: true,

  async initSession(analysisId, risks = []) {
    this.sessionId = null;
    this.waiting = false;
    this.chipsVisible = true;

    const messages = document.getElementById('chatMessages');
    const input = document.getElementById('chatInput');
    const chips = document.getElementById('chatChips');
    const typing = document.getElementById('typingIndicator');

    if (!messages) return;

    messages.innerHTML = '';
    chips.style.display = 'flex';
    chips.innerHTML = '';
    input.value = '';
    this.autoResize(input);
    typing.style.display = 'none';
    document.getElementById('chatSection').style.display = 'block';
    
    this.setInputState(false);
    this.renderChips(risks);

    try {
      const data = await window.api.fetch('/chat/session', {
        method: 'POST',
        body: JSON.stringify({ analysis_id: analysisId })
      });
      this.sessionId = data.session_id;
      this.setInputState(true);

      if (data.messages && data.messages.length > 0) {
        // Restore history context
        this.chipsVisible = false;
        document.getElementById('chatChips').style.display = 'none';
        data.messages.forEach(msg => {
          this.appendBubble(msg.role, msg.content);
        });
        this.scrollToBottom();
      } else {
        // Start fresh context
        const riskyCount = risks.filter(x => x.is_risky).length;
        const highCount = risks.filter(x => x.risk_level === 'high').length;
        
        const welcome = `Контракт проанализирован. Найдено рисков: **${riskyCount}**`
          + (highCount > 0 ? `, из них высоких: **${highCount}**` : '')
          + '. Задайте любой вопрос по документу.';
        
        this.appendBubble('assistant', welcome);
      }
    } catch (e) {
      this.appendBubble('assistant', 'Чат временно недоступен: ' + e.message, true);
    }
  },

  async restoreSession(sessionData) {
    this.sessionId = sessionData.session_id;
    this.waiting = false;
    this.chipsVisible = false;

    const messagesEl = document.getElementById('chatMessages');
    messagesEl.innerHTML = '';
    document.getElementById('chatChips').style.display = 'none';
    document.getElementById('chatSection').style.display = 'block';
    
    sessionData.messages.forEach(msg => {
      this.appendBubble(msg.role, msg.content);
    });
    
    this.setInputState(true);
    this.scrollToBottom();
  },

  renderChips(risks) {
    const container = document.getElementById('chatChips');
    container.innerHTML = '';
    const chips = [];

    const highRisks = risks.filter(r => r.risk_level === 'high').slice(0, 2);
    highRisks.forEach(r => chips.push(`Объясни подробнее риск #${r.segment_id}`));
    chips.push('Какие пункты нужно переписать в первую очередь?');
    chips.push('Предложи безопасную формулировку');
    if (risks.filter(r => r.is_risky).length > 2) chips.push('Есть ли противоречия в договоре?');

    chips.slice(0, 4).forEach(text => {
      const btn = document.createElement('button');
      btn.className = 'chat-chip';
      btn.textContent = text;
      btn.onclick = () => this.sendQuick(text);
      container.appendChild(btn);
    });
  },

  sendQuick(text) {
    const input = document.getElementById('chatInput');
    input.value = text;
    this.autoResize(input);
    this.sendMessage();
  },

  async sendMessage() {
    const input = document.getElementById('chatInput');
    const content = input.value.trim();
    if (!content || content.length > 2000) return;
    if (!this.sessionId || this.waiting) return;

    if (this.chipsVisible) {
      document.getElementById('chatChips').style.display = 'none';
      this.chipsVisible = false;
    }

    input.value = '';
    this.autoResize(input);
    this.appendBubble('user', content);

    this.waiting = true;
    this.setInputState(false);
    document.getElementById('typingIndicator').style.display = 'flex';
    this.scrollToBottom();

    try {
      const data = await window.api.fetch(`/chat/session/${this.sessionId}/message`, {
        method: 'POST',
        body: JSON.stringify({ content })
      });
      this.appendBubble('assistant', data.content || '');
    } catch (e) {
      this.appendBubble('assistant', 'Ошибка чата: ' + e.message, true);
    } finally {
      this.waiting = false;
      document.getElementById('typingIndicator').style.display = 'none';
      this.setInputState(true);
      input.focus();
    }
  },

  appendBubble(role, text, isError = false) {
    const messages = document.getElementById('chatMessages');
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role === 'user' ? 'user' : 'assistant'}`;
    if (isError && role !== 'user') bubble.style.borderColor = 'var(--high-border)';

    const textNode = document.createElement('div');
    textNode.innerHTML = this.formatText(text);
    bubble.appendChild(textNode);

    const time = document.createElement('div');
    time.className = 'bubble-time';
    time.textContent = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    bubble.appendChild(time);

    messages.appendChild(bubble);
    this.scrollToBottom();
  },

  formatText(text) {
    let html = this.escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');

    // Optional: add interactive risk references if currentResult matches this chat session
    if (window.analysis.currentResult) {
      const risks = window.analysis.currentResult.risks || [];
      html = html.replace(/#(\d+)/g, (_, id) => {
        const risk = risks.find(r => Number(r.segment_id) === Number(id));
        const lvl = risk ? risk.risk_level : 'low';
        return `<span class="risk-ref ${lvl}" onclick="window.chat.scrollToRisk(${id})">#${id}</span>`;
      });
    } else {
       html = html.replace(/#(\d+)/g, '<span class="risk-ref low">#$1</span>');
    }
    return html;
  },

  scrollToRisk(segmentId) {
    const cards = Array.from(document.querySelectorAll('.risk-card'));
    const target = cards.find(c => {
      const idEl = c.querySelector('.risk-id');
      return idEl && idEl.textContent === `#${segmentId}`;
    });
    if (!target) return;
    if (!target.classList.contains('expanded')) target.classList.add('expanded');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },

  setInputState(enabled) {
    const input = document.getElementById('chatInput');
    const btn = document.getElementById('chatSendBtn');
    if(input) input.disabled = !enabled;
    if(btn) btn.disabled = !enabled;
  },

  autoResize(el) {
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 80) + 'px';
  },

  scrollToBottom() {
    const panel = document.getElementById('panelRight');
    if(panel) panel.scrollTop = panel.scrollHeight;
  },

  escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
};
