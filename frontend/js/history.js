// Analysis History
window.historyAPI = {
  currentOffset: 0,
  limit: 10,
  hasMore: true,
  
  elements: {
    list: () => document.getElementById('historyList'),
    loadMoreBtn: () => document.getElementById('historyLoadMore')
  },
  
  async loadList(reset = true) {
    if (reset) {
      this.currentOffset = 0;
      this.hasMore = true;
      if (this.elements.list()) this.elements.list().innerHTML = '';
      if (this.elements.loadMoreBtn()) this.elements.loadMoreBtn().style.display = 'none';
    }
    
    if (!this.hasMore || !this.elements.list()) return;
    
    try {
      const data = await window.api.fetch(`/analyses?limit=${this.limit}&offset=${this.currentOffset}`);
      const items = data.items;
      
      if (items.length < this.limit) {
        this.hasMore = false;
        this.elements.loadMoreBtn().style.display = 'none';
      } else {
        this.elements.loadMoreBtn().style.display = 'block';
      }
      
      const listEl = this.elements.list();
      if (reset && items.length === 0) {
        listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center;">История пуста</div>';
        return;
      }
      
      items.forEach(item => {
        const ts = new Date(item.created_at).toLocaleDateString('ru-RU', { 
          day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' 
        });
        
        // Calculate score color class
        let scoreClass = 'score-low';
        if (item.risk_score > 0.6) scoreClass = 'score-high';
        else if (item.risk_score > 0.3) scoreClass = 'score-medium';
        
        const div = document.createElement('div');
        div.className = 'history-item';
        div.dataset.id = item.analysis_id;
        div.onclick = () => window.app.loadExistingAnalysis(item.analysis_id);
        
        div.innerHTML = `
          <div class="history-name" title="${item.filename}">${item.filename}</div>
          <div class="history-metrics">
            <span class="history-score ${scoreClass}">Idx: ${item.risk_score.toFixed(2)}</span>
            <span class="history-date">${ts}</span>
          </div>
        `;
        
        listEl.appendChild(div);
      });
      
      this.currentOffset += items.length;
    } catch (e) {
      console.error('Failed to load history', e);
    }
  },
  
  setActive(analysisId) {
    if (!this.elements.list()) return;
    document.querySelectorAll('.history-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === analysisId);
    });
  }
};
