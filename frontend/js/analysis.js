// Analysis workflow and Results rendering
window.analysis = {
  currentResult: null,
  activeFilter: 'all',
  activeCategoryFilter: 'all',
  // Track which segment IDs have already been rendered (for incremental streaming)
  _renderedSegmentIds: new Set(),
  categoryLabels: {
    all: 'Все категории',
    financial: 'Финансы',
    legal: 'Право',
    operational: 'Операции',
    reputational: 'Репутация',
    intellectual: 'Интелл. собственность',
    uncategorized: 'Без категории',
  },
  
  currentPollingId: null,

  async start() {
    if (!window.upload.currentFile) return;
    
    window.app.hideError();
    this.setLoading(true);

    const formData = new FormData();
    formData.append('file', window.upload.currentFile);

    try {
      let result = null;
      const respRaw = await fetch('/api/v1/analyze', { 
        method: 'POST', 
        body: formData,
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
        
        document.getElementById('step1').className = 'loading-step done';
        document.getElementById('step2').className = 'loading-step done';
        document.getElementById('step3').className = 'loading-step active';
        this.setProgress(10, 'Инициализация LLM...');
        
        result = await this.pollResult(initData.analysis_id);
        if (!result) return;
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
    this.currentPollingId = analysis_id;
    this._renderedSegmentIds = new Set();
    // Track last known count to detect new batches arriving
    let lastKnownRiskCount = 0;

    const maxAttempts = 1200;
    for (let i = 0; i < maxAttempts; i++) {
        if (this.currentPollingId !== analysis_id) return null;
        
        await new Promise(r => setTimeout(r, 3000));
        
        if (this.currentPollingId !== analysis_id) return null;
        
        const res = await window.api.fetch(`/analyze/${analysis_id}`);
        
        if (res.status === 'completed' || res.analysis_id && !res.status) {
            // Final result — fetch full grouped data for complete render
            const grouped = await window.api.fetch(`/analyze/${analysis_id}/grouped`);
            return grouped.analysis_id ? grouped : res;
        }
        if (res.status === 'failed') {
            const msg = res.message || 'Произошёл сбой при анализе. Попробуйте снова.';
            throw new Error(msg);
        }
        
        if (res.status === 'processing') {
             let rawPct = res.progress_percent || 0;
             let pct = 10 + Math.floor(rawPct * 0.9);
             let label = res.progress_label || 'Обработка в фоне...';
             this.setProgress(pct, label);
             
             document.getElementById('step1').className = 'loading-step done';
             document.getElementById('step2').className = 'loading-step done';
             
             if (rawPct > 0) {
                 document.getElementById('step3').className = 'loading-step done';
                 document.getElementById('step4').className = 'loading-step active';
                 if (rawPct >= 95) {
                     document.getElementById('step4').className = 'loading-step done';
                     document.getElementById('step5').className = 'loading-step active';
                 }
             } else {
                 document.getElementById('step3').className = 'loading-step active';
             }

             // ── Incremental rendering: fetch partial grouped results ──
             if (rawPct > 0) {
                 try {
                     const partial = await window.api.fetch(`/analyze/${analysis_id}/grouped`);
                     if (partial && partial.groups && partial.groups.length > 0) {
                         const allRisks = partial.groups.flatMap(g => g.risks || []);
                         if (allRisks.length > lastKnownRiskCount) {
                             lastKnownRiskCount = allRisks.length;
                             this._renderPartialResults(partial);
                         }
                     }
                 } catch (_) {
                     // Partial results not available yet — that's ok
                 }
             }
        }
    }
    throw new Error('Превышено время ожидания результатов (60 минут)');
  },

  /** Render partial results while analysis is still running */
  _renderPartialResults(partial) {
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';

    // Show summary section with partial counts
    const summarySection = document.getElementById('summarySection');
    summarySection.style.display = 'flex';

    const s = partial.summary;
    if (s) {
        document.getElementById('statTotal').textContent = `${partial.analyzed_segments || '?'}/${partial.total_segments || '?'}`;
        document.getElementById('statRisky').textContent = s.risky_segments || 0;
        document.getElementById('statHigh').textContent = s.high_risk_count || 0;
        document.getElementById('statMedium').textContent = s.medium_risk_count || 0;
        document.getElementById('resultsFilename').textContent = partial.filename || '';

        const score = s.risk_score || 0;
        const scoreEl = document.getElementById('scoreValue');
        scoreEl.textContent = score.toFixed(2);
        const fill = document.getElementById('scoreFill');
        fill.style.width = (score * 100) + '%';
        if (score > 0.6) { fill.style.background = 'var(--high)'; scoreEl.style.color = 'var(--high)'; }
        else if (score > 0.3) { fill.style.background = 'var(--medium)'; scoreEl.style.color = 'var(--medium)'; }
        else { fill.style.background = 'var(--accent)'; scoreEl.style.color = 'var(--accent)'; }
    }

    // Hide executive summary until analysis is fully complete
    const execWrap = document.getElementById('executiveSummary');
    if (execWrap) {
        const textEl = document.getElementById('executiveSummaryText');
        if (textEl) textEl.textContent = 'Сводка будет доступна после завершения анализа всех сегментов…';
        execWrap.style.display = 'block';
    }

    // Append only new risk cards
    const list = document.getElementById('riskList');
    const allRisks = partial.groups.flatMap(g => (g.risks || []).map(r => typeof r === 'object' && r.segment_id ? r : null)).filter(Boolean);

    allRisks.forEach((risk) => {
        if (this._renderedSegmentIds.has(risk.segment_id)) return;
        this._renderedSegmentIds.add(risk.segment_id);
        const card = this.createRiskCard(risk, this._renderedSegmentIds.size - 1);
        list.appendChild(card);
        this._attachAcceptNormHandlers([risk], card);
    });

    // Rebuild category filters based on what we have so far
    this.renderCategoryFilters(allRisks);
    this.applyFilters();
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
    this._renderedSegmentIds = new Set();
    
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';
    document.getElementById('summarySection').style.display = 'flex';

    // If data came from /grouped endpoint it has `groups` instead of flat `risks`
    let risks = data.risks;
    if (!risks && data.groups) {
      risks = data.groups.flatMap(g => g.risks || []);
    }
    if (!risks) risks = [];
    // Store flat risks back for other methods
    data.risks = risks;

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
    this.renderCategoryFilters(risks);

    // Risk list
    const list = document.getElementById('riskList');
    list.innerHTML = '';
    risks.forEach((risk, idx) => {
      list.appendChild(this.createRiskCard(risk, idx));
    });
    this._attachAcceptNormHandlers(risks);

    this.applyFilters();
    const analysisId = data.analysis_id;
    window.chat.initSession(analysisId, risks);
    if (window.historyAPI) window.historyAPI.setActive(analysisId);
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

    const risks = data.risks || [];
    const riskyItems = risks.filter(item => item.is_risky);
    if (riskyItems.length === 0) {
      textEl.textContent = 'Договор выглядит низкорисковым: критичные формулировки не выявлены. Рекомендуется финальная ручная проверка перед подписанием.';
      wrap.style.display = 'block';
      return;
    }

    let riskBand = 'среднерисковый';
    const summary = data.summary;
    if (summary.high_risk_count > 0 || summary.risk_score >= 0.6) {
      riskBand = 'высокорисковый';
    } else if (summary.risk_score <= 0.3) {
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

    textEl.textContent = `Договор классифицирован как ${riskBand}: обнаружено ${riskyItems.length} риск-сегментов из ${summary.total_segments}. ${keyTopicsText} ${criticalText}`;
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
          ${risk.safe_redaction ? `
          <div class="risk-detail-row safe-redaction-row">
            <span class="risk-detail-label">Исправленный текст</span>
            <div class="safe-redaction-box">
              <div class="safe-redaction-text">${this.escapeHtml(risk.safe_redaction)}</div>
              <button class="safe-redaction-copy-btn" onclick="event.stopPropagation(); window.analysis.copySafeRedaction(this, ${JSON.stringify(risk.safe_redaction).replace(/</g, '\\u003c')})" title="Скопировать безопасную формулировку">
                <span class="copy-icon">📋</span> Скопировать
              </button>
            </div>
          </div>` : ''}
          ${risk.is_risky ? `
          <div class="risk-detail-row">
            <button class="btn-accept-norm" data-accept-norm data-segment-id="${risk.segment_id}" title="Принять эту формулировку как корпоративную норму">
              Принять как норму компании
            </button>
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
      const level = card.dataset.level;
      const levelOk = levelFilter === 'all' 
        || (levelFilter === 'risky' && ['high', 'medium', 'low'].includes(level))
        || level === levelFilter;
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

  copySafeRedaction(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
      const originalText = btn.innerHTML;
      btn.innerHTML = '<span class="copy-icon">✓</span> Скопировано';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.classList.remove('copied');
      }, 2000);
    }).catch(() => {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      const originalText = btn.innerHTML;
      btn.innerHTML = '<span class="copy-icon">✓</span> Скопировано';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.classList.remove('copied');
      }, 2000);
    });
  },

  _attachAcceptNormHandlers(risks, scope) {
    const root = scope || document.getElementById('riskList');
    if (!root) return;
    const buttons = root.querySelectorAll('button[data-accept-norm]');
    const byId = new Map(risks.map(r => [String(r.segment_id), r]));
    buttons.forEach(btn => {
      if (btn._normHandlerAttached) return;
      const id = btn.getAttribute('data-segment-id');
      const risk = byId.get(id);
      if (!risk) return;
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.openAcceptNormModal(risk.text, risk.risk_description || '');
      });
      btn._normHandlerAttached = true;
    });
  },

  openAcceptNormModal(segmentText, riskDescription) {
    let modal = document.getElementById('acceptNormModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'acceptNormModal';
      modal.className = 'modal-backdrop';
      modal.innerHTML = `
        <div class="auth-modal" style="max-width:520px;">
          <div class="auth-header">
            <div class="auth-title">Принять как норму компании</div>
            <div class="auth-subtitle">Этот сегмент будет сохранён как корпоративный эталон и при следующем анализе не будет считаться риском.</div>
          </div>
          <div class="auth-form-group">
            <label class="auth-label">Текст сегмента</label>
            <textarea id="normSegmentText" class="auth-input" rows="4" style="resize:vertical; font-size:12px;"></textarea>
          </div>
          <div class="auth-form-group">
            <label class="auth-label">Название правила</label>
            <input type="text" id="normTitle" class="auth-input" placeholder="Например: Стандартное расторжение">
          </div>
          <div class="auth-form-group">
            <label class="auth-label">Тип договора</label>
            <select id="normContractType" class="auth-input">
              <option value="любой">Любой (универсальный)</option>
              <option value="услуги">Услуги</option>
              <option value="подряд">Подряд</option>
              <option value="поставка">Поставка</option>
              <option value="аренда">Аренда</option>
              <option value="нда">NDA</option>
              <option value="лицензионный">Лицензионный</option>
              <option value="трудовой">Трудовой</option>
            </select>
          </div>
          <div class="auth-error" id="normError" style="display:none;"></div>
          <div style="display:flex; gap:8px; margin-top:16px;">
            <button class="btn-primary" id="normSubmitBtn" onclick="window.analysis.submitAcceptNorm()">Сохранить</button>
            <button class="btn-outline" onclick="document.getElementById('acceptNormModal').classList.remove('open')">Отмена</button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
    }

    document.getElementById('normSegmentText').value = segmentText;
    document.getElementById('normTitle').value = '';
    document.getElementById('normError').style.display = 'none';

    const contractType = this._detectCurrentContractType();
    const select = document.getElementById('normContractType');
    select.value = contractType || 'любой';

    modal.classList.add('open');
  },

  _detectCurrentContractType() {
    const filename = this.currentResult?.filename || '';
    return '';
  },

  async submitAcceptNorm() {
    const text = document.getElementById('normSegmentText').value.trim();
    const title = document.getElementById('normTitle').value.trim();
    const contractType = document.getElementById('normContractType').value;
    const errEl = document.getElementById('normError');
    const btn = document.getElementById('normSubmitBtn');

    if (!text) {
      errEl.textContent = 'Текст сегмента не может быть пустым';
      errEl.style.display = 'block';
      return;
    }
    if (!title) {
      errEl.textContent = 'Укажите название правила';
      errEl.style.display = 'block';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Сохранение...';
    errEl.style.display = 'none';

    const formData = new FormData();
    formData.append('text', text);
    formData.append('title', title);
    formData.append('contract_type', contractType);
    formData.append('description', 'Корпоративная норма (принятый риск)');

    try {
      await window.api.fetch('/documents/upload/text', {
        method: 'POST',
        body: formData
      });
      document.getElementById('acceptNormModal').classList.remove('open');
      if (window.documentsAPI) window.documentsAPI.loadList();
      this._showNormSavedNotice();
    } catch (e) {
      errEl.textContent = 'Ошибка: ' + e.message;
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Сохранить';
    }
  },

  _showNormSavedNotice() {
    const notice = document.createElement('div');
    notice.className = 'norm-saved-notice';
    notice.textContent = 'Корпоративная норма сохранена';
    document.body.appendChild(notice);
    requestAnimationFrame(() => notice.classList.add('visible'));
    setTimeout(() => {
      notice.classList.remove('visible');
      setTimeout(() => notice.remove(), 300);
    }, 2500);
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
