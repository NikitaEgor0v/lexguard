// Analysis workflow and Results rendering
window.analysis = {
  currentResult: null,
  activeFilter: 'all',
  activeCategoryFilter: 'all',
  highlightMode: false,
  selectedSegmentId: null,
  categoryLabels: {
    all: 'Все категории',
    financial: 'Финансы',
    legal: 'Право',
    operational: 'Операции',
    reputational: 'Репутация',
    intellectual: 'Интелл. собственность',
    uncategorized: 'Без категории',
  },
  
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
    this.selectedSegmentId = null;
    
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

    this.renderExecutiveSummary(data);
    this.renderCategoryFilters(data.risks);
    this.renderHighlightMap(data.risks);
    this.updateHighlightModeUI();

    // Risk list
    const list = document.getElementById('riskList');
    list.innerHTML = '';
    data.risks.forEach((risk, idx) => {
      list.appendChild(this.createRiskCard(risk, idx));
    });

    this.applyFilters();
    window.chat.initSession(data.analysis_id, data.risks);
    if (window.historyAPI) window.historyAPI.setActive(data.analysis_id);
  },

  normalizeCategory(rawCategory) {
    const value = (rawCategory || '').toLowerCase().trim();
    if (value === 'финансовый') return 'financial';
    if (value === 'правовой') return 'legal';
    if (value === 'операционный') return 'operational';
    if (value === 'репутационный') return 'reputational';
    if (value === 'интеллектуальный') return 'intellectual';
    return 'uncategorized';
  },

  renderExecutiveSummary(data) {
    const wrap = document.getElementById('executiveSummary');
    const textEl = document.getElementById('executiveSummaryText');
    if (!wrap || !textEl) return;

    if (data.executive_summary && String(data.executive_summary).trim()) {
      textEl.textContent = data.executive_summary;
      wrap.style.display = 'block';
      return;
    }

    const riskyItems = data.risks.filter(item => item.is_risky);
    if (riskyItems.length === 0) {
      textEl.textContent = 'Договор выглядит низкорисковым: критичные формулировки не выявлены. Рекомендуется финальная ручная проверка перед подписанием.';
      wrap.style.display = 'block';
      return;
    }

    let riskBand = 'среднерисковый';
    if (data.summary.high_risk_count > 0 || data.summary.risk_score >= 0.6) {
      riskBand = 'высокорисковый';
    } else if (data.summary.risk_score <= 0.3) {
      riskBand = 'низкорисковый';
    }

    const categoryCounts = {};
    riskyItems.forEach(item => {
      const category = this.normalizeCategory(item.risk_category);
      categoryCounts[category] = (categoryCounts[category] || 0) + 1;
    });

    const topCategories = Object.entries(categoryCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([key, count]) => `${this.categoryLabels[key]} (${count})`);

    const topCritical = riskyItems
      .filter(item => item.risk_level === 'high')
      .slice(0, 2)
      .map(item => `п. ${item.segment_id}: ${item.risk_description || 'требует ручной проверки'}`);

    const keyTopicsText = topCategories.length
      ? `Ключевые зоны риска: ${topCategories.join(', ')}.`
      : 'Ключевые зоны риска требуют ручной группировки.';
    const criticalText = topCritical.length
      ? `Приоритетно проверить: ${topCritical.join('; ')}.`
      : 'Критичных пунктов не обнаружено, основной фокус на средних рисках.';

    textEl.textContent = `Договор классифицирован как ${riskBand}: обнаружено ${riskyItems.length} риск-сегментов из ${data.summary.total_segments}. ${keyTopicsText} ${criticalText}`;
    wrap.style.display = 'block';
  },

  renderCategoryFilters(risks) {
    const container = document.getElementById('categoryFilters');
    if (!container) return;

    const counts = { all: risks.length };
    risks.forEach(item => {
      const category = this.normalizeCategory(item.risk_category);
      counts[category] = (counts[category] || 0) + 1;
    });

    const ordered = ['all', 'financial', 'legal', 'operational', 'intellectual', 'reputational', 'uncategorized']
      .filter(key => key === 'all' || counts[key] > 0);

    if (!ordered.includes(this.activeCategoryFilter)) {
      this.activeCategoryFilter = 'all';
    }

    container.innerHTML = ordered.map(key => {
      const activeClass = key === this.activeCategoryFilter ? 'active' : '';
      const label = this.categoryLabels[key] || key;
      const count = counts[key] || 0;
      return `<button class="filter-btn category-btn ${activeClass}" data-category="${key}" onclick="window.analysis.setCategoryFilter('${key}', this)">${label} · ${count}</button>`;
    }).join('');
  },

  updateHighlightModeUI() {
    const wrap = document.getElementById('highlightWrap');
    const btn = document.getElementById('highlightModeBtn');
    if (!wrap || !btn) return;
    wrap.style.display = this.highlightMode ? 'grid' : 'none';
    btn.textContent = this.highlightMode ? 'Скрыть разметку' : 'Режим разметки';
  },

  toggleHighlightMode() {
    this.highlightMode = !this.highlightMode;
    this.updateHighlightModeUI();
  },

  renderHighlightMap(risks) {
    const list = document.getElementById('highlightSourceList');
    const detail = document.getElementById('highlightDetail');
    if (!list || !detail) return;

    list.innerHTML = '';
    if (!Array.isArray(risks) || risks.length === 0) {
      detail.textContent = 'Сегменты отсутствуют.';
      return;
    }

    risks.forEach((risk) => {
      const card = document.createElement('div');
      card.className = `highlight-segment ${risk.risk_level}`;
      card.dataset.segmentId = String(risk.segment_id);

      const head = document.createElement('div');
      head.className = 'highlight-segment-head';
      const left = document.createElement('span');
      left.textContent = `#${risk.segment_id}`;
      const right = document.createElement('span');
      right.textContent = risk.risk_level.toUpperCase();
      head.appendChild(left);
      head.appendChild(right);

      const body = document.createElement('div');
      const preview = risk.text.length > 190 ? `${risk.text.slice(0, 190)}…` : risk.text;
      body.textContent = preview;

      card.appendChild(head);
      card.appendChild(body);
      card.addEventListener('click', () => this.selectHighlightedSegment(risk.segment_id));
      list.appendChild(card);
    });

    detail.textContent = 'Выберите сегмент слева, чтобы открыть объяснение риска и перейти к карточке.';
  },

  selectHighlightedSegment(segmentId) {
    if (!this.currentResult) return;
    this.selectedSegmentId = segmentId;

    document.querySelectorAll('.highlight-segment').forEach((el) => {
      el.classList.toggle('active', Number(el.dataset.segmentId) === segmentId);
    });

    const selected = this.currentResult.risks.find((item) => item.segment_id === segmentId);
    const detail = document.getElementById('highlightDetail');
    if (selected && detail) {
      const category = selected.risk_category || 'без категории';
      detail.innerHTML = [
        `<p><strong>Сегмент:</strong> #${selected.segment_id}</p>`,
        `<p><strong>Категория:</strong> ${this.escapeHtml(category)}</p>`,
        `<p><strong>Уровень:</strong> ${this.escapeHtml(selected.risk_level)}</p>`,
        `<p><strong>Описание:</strong> ${this.escapeHtml(selected.risk_description || 'Требует ручной проверки.')}</p>`,
        `<p><strong>Рекомендация:</strong> ${this.escapeHtml(selected.recommendation || 'Нет авто-рекомендации.')}</p>`,
      ].join('');
    }

    this.focusRiskCard(segmentId);
  },

  focusRiskCard(segmentId) {
    this.activeFilter = 'all';
    this.activeCategoryFilter = 'all';
    this.applyFilters();

    const allCards = Array.from(document.querySelectorAll('.risk-card'));
    const target = allCards.find((el) => {
      const idNode = el.querySelector('.risk-id');
      return idNode && idNode.textContent === `#${segmentId}`;
    });
    if (!target) return;

    target.classList.add('expanded');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },

  escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },

  createRiskCard(risk, idx) {
    const card = document.createElement('div');
    card.className = `risk-card ${risk.risk_level}`;
    card.style.animationDelay = (idx * 0.04) + 's';
    card.dataset.level = risk.risk_level;
    card.dataset.category = this.normalizeCategory(risk.risk_category);

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
    document.querySelectorAll('.filters .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    this.applyFilters();
  },

  setCategoryFilter(filter, btn) {
    this.activeCategoryFilter = filter;
    document.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    this.applyFilters();
  },

  applyFilters() {
    const levelFilter = this.activeFilter;
    const categoryFilter = this.activeCategoryFilter;

    document.querySelectorAll('.filters .filter-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.filter === levelFilter);
    });
    document.querySelectorAll('.category-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.category === categoryFilter);
    });

    document.querySelectorAll('.risk-card').forEach(card => {
      const levelOk = levelFilter === 'all' || card.dataset.level === levelFilter;
      const categoryOk = categoryFilter === 'all' || card.dataset.category === categoryFilter;
      card.classList.toggle('hidden', !(levelOk && categoryOk));
    });

    if (this.selectedSegmentId !== null) {
      const selectedVisible = Array.from(document.querySelectorAll('.risk-card')).some((card) => {
        const idNode = card.querySelector('.risk-id');
        return (
          !card.classList.contains('hidden') &&
          idNode &&
          idNode.textContent === `#${this.selectedSegmentId}`
        );
      });
      if (!selectedVisible) {
        this.selectedSegmentId = null;
        document.querySelectorAll('.highlight-segment').forEach((el) => el.classList.remove('active'));
      }
    }
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
