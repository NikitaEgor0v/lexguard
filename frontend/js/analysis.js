// Analysis workflow and Results rendering
window.analysis = {
  currentResult: null,
  activeFilter: 'all',
  
  async start() {
    if (!window.upload.currentFile) return;
    
    // Requires Auth for full usage, API will intercept 401 if missing.
    window.app.hideError();
    this.setLoading(true);

    const formData = new FormData();
    formData.append('file', window.upload.currentFile);

    try {
      // Setup polling instead of simple fetch since Celery pushes to background
      // Update: Celery is task 6, we will implement frontend polling here assuming the API returns 202
      let result = null;
      const respRaw = await fetch('/api/v1/analyze', { 
        method: 'POST', 
        body: formData,
        // include cookie auth
        headers: { 'Accept': 'application/json' }
      });
      
      if (respRaw.status === 401) {
        window.auth.handleUnauthorized();
        throw new Error('Требуется авторизация');
      }
      
      if (!respRaw.ok) {
         const err = await respRaw.json();
         throw new Error(err.detail || 'Ошибка анализа');
      }
      
      if (respRaw.status === 202) {
        const initData = await respRaw.json();
        result = await this.pollResult(initData.analysis_id);
      } else {
        result = await respRaw.json();
      }

      this.currentResult = result;
      this.renderResults(result);
      
      if (window.historyAPI) window.historyAPI.loadList();
      document.getElementById('analyzeBtn').style.display = 'none';
      document.getElementById('progressWrap').classList.remove('visible');
      document.getElementById('loadingSteps').classList.remove('visible');
      
    } catch (e) {
      window.app.showError(e.message);
      this.setLoading(false);
    }
  },
  
  async pollResult(analysis_id) {
    const maxAttempts = 1200; // 1200 * 3s = 60 minutes
    for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 3000));
        const res = await window.api.fetch(`/analyze/${analysis_id}`);
        
        if (res.status === 'completed' || res.analysis_id && !res.status) {
            // It might return the full AnalysisResponse directly
            return res.analysis_id ? res : res.result; 
        }
        if (res.status === 'failed') throw new Error('Сбой обработки документа');
        
        if (res.status === 'processing') {
             // Real progress updating from server
             let pct = res.progress_percent || 0;
             let label = res.progress_label || 'Обработка в фоне...';
             this.setProgress(pct, label);
             
             // Update step visuals dynamically
             if (pct > 0) {
                 document.getElementById('step1').className = 'loading-step done';
                 document.getElementById('step2').className = 'loading-step done';
                 document.getElementById('step3').className = 'loading-step active';
                 if (pct > 95) document.getElementById('step4').className = 'loading-step active';
             }
        }
    }
    throw new Error('Превышено время ожидания результатов (60 минут)');
  },

  setLoading(on) {
    document.getElementById('analyzeBtn').disabled = on;
    document.getElementById('progressWrap').classList.toggle('visible', on);
    document.getElementById('loadingSteps').classList.toggle('visible', on);
    if (!on) {
      document.getElementById('progressFill').style.width = '0%';
      document.querySelectorAll('.loading-step').forEach(s => s.className = 'loading-step');
    } else {
      this.setProgress(5, 'Чтение документа...');
      document.getElementById('step1').className = 'loading-step active';
    }
  },

  setProgress(pct, label) {
    document.getElementById('progressFill').style.width = Math.max(5, pct) + '%';
    document.getElementById('progressLabel').textContent = label;
    document.getElementById('progressPct').textContent = pct + '%';
  },

  renderResults(data) {
    this.currentResult = data;
    
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';
    document.getElementById('summarySection').style.display = 'flex';

    // Summary
    const s = data.summary;
    document.getElementById('statTotal').textContent = s.total_segments;
    document.getElementById('statRisky').textContent = s.risky_segments;
    document.getElementById('statHigh').textContent = s.high_risk_count;
    document.getElementById('statMedium').textContent = s.medium_risk_count;
    document.getElementById('resultsFilename').textContent = data.filename;

    // Score
    const score = s.risk_score;
    const scoreEl = document.getElementById('scoreValue');
    scoreEl.textContent = score.toFixed(2);
    const fill = document.getElementById('scoreFill');
    fill.style.width = (score * 100) + '%';
    if (score > 0.6) { fill.style.background = 'var(--high)'; scoreEl.style.color = 'var(--high)'; }
    else if (score > 0.3) { fill.style.background = 'var(--medium)'; scoreEl.style.color = 'var(--medium)'; }
    else { fill.style.background = 'var(--accent)'; scoreEl.style.color = 'var(--accent)'; }

    // Risk list
    const list = document.getElementById('riskList');
    list.innerHTML = '';
    data.risks.forEach((risk, idx) => {
      list.appendChild(this.createRiskCard(risk, idx));
    });

    this.applyFilter(this.activeFilter);
    window.chat.initSession(data.analysis_id, data.risks);
    if (window.historyAPI) window.historyAPI.setActive(data.analysis_id);
  },

  createRiskCard(risk, idx) {
    const card = document.createElement('div');
    card.className = `risk-card ${risk.risk_level}`;
    card.style.animationDelay = (idx * 0.04) + 's';
    card.dataset.level = risk.risk_level;

    const levelLabels = { high: 'Высокий', medium: 'Средний', low: 'Низкий', none: 'Норма' };
    const preview = risk.text.length > 80 ? risk.text.slice(0, 80) + '…' : risk.text;

    card.innerHTML = `
      <div class="risk-card-header" onclick="this.parentElement.classList.toggle('expanded')">
        <span class="risk-id">#${risk.segment_id}</span>
        <span class="risk-level-badge badge-${risk.risk_level}">${levelLabels[risk.risk_level] || 'Неизв'}</span>
        ${risk.risk_category ? `<span class="risk-category-tag">${risk.risk_category}</span>` : ''}
        <span class="risk-text-preview">${preview}</span>
        <span class="risk-chevron">›</span>
      </div>
      <div class="risk-card-body">
        <div class="risk-full-text">${risk.text}</div>
        <div class="risk-details">
          ${risk.risk_description ? `
          <div class="risk-detail-row">
            <span class="risk-detail-label">Риск</span>
            <span class="risk-detail-value">${risk.risk_description}</span>
          </div>` : ''}
          ${risk.recommendation ? `
          <div class="risk-detail-row">
            <span class="risk-detail-label">Рекомендация</span>
            <div class="recommendation-box">${risk.recommendation}</div>
          </div>` : ''}
          ${risk.rag_context ? `
          <div class="risk-detail-row">
            <span class="risk-detail-label">Контекст RAG</span>
            <div class="rag-context">${risk.rag_context}</div>
          </div>` : ''}
        </div>
      </div>
    `;
    return card;
  },

  setFilter(filter, btn) {
    this.activeFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    this.applyFilter(filter);
  },

  applyFilter(filter) {
    document.querySelectorAll('.risk-card').forEach(card => {
      card.classList.toggle('hidden', filter !== 'all' && card.dataset.level !== filter);
    });
  },

  exportJSON() {
    if (!this.currentResult) return;
    const blob = new Blob([JSON.stringify(this.currentResult, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `analysis_${this.currentResult.analysis_id.slice(0, 8)}.json`;
    a.click();
  }
};
