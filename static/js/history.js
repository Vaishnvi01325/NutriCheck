/**
 * NutriCheck – History Module
 * Manages analysis history display and interactions
 */

const History = {
    data: [],

    /**
     * Load history from API
     */
    async load() {
        try {
            const res = await fetch('/api/history');
            if (!res.ok) throw new Error('Failed to fetch history');
            this.data = await res.json();
            this.render();
        } catch (err) {
            console.error('History load error:', err);
            this.renderEmpty('Failed to load history');
        }
    },

    /**
     * Render history cards
     */
    render() {
        const grid = document.getElementById('historyGrid');

        if (!this.data || this.data.length === 0) {
            this.renderEmpty();
            return;
        }

        grid.innerHTML = '';
        this.data.forEach(item => {
            const card = this.createCard(item);
            grid.appendChild(card);
        });
    },

    /**
     * Create a history card element
     */
    createCard(item) {
        const card = document.createElement('div');
        card.className = 'history-card';
        card.dataset.id = item.id;

        const verdictClass = Dashboard.getVerdictClass(item.verdict);
        const date = new Date(item.created_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });

        card.innerHTML = `
            <img class="history-thumb" 
                 src="${item.image_url || '/static/images/placeholder.png'}" 
                 alt="${item.product_name}"
                 onerror="this.style.display='none'">
            <div class="history-info">
                <div class="history-name">${item.product_name || 'Unknown Product'}</div>
                <div class="history-date">${date}</div>
                <span class="history-score-badge ${verdictClass}">
                    ⚡ ${item.health_score}/100
                </span>
            </div>
            <div class="history-actions">
                <button class="history-action-btn" title="Delete" data-delete="${item.id}">🗑️</button>
            </div>
        `;

        // Click card to view results
        card.addEventListener('click', (e) => {
            if (e.target.closest('[data-delete]')) return;
            this.viewAnalysis(item.id);
        });

        // Delete button
        const delBtn = card.querySelector('[data-delete]');
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.deleteAnalysis(item.id);
        });

        return card;
    },

    /**
     * View a past analysis
     */
    async viewAnalysis(id) {
        try {
            const res = await fetch(`/api/analysis/${id}`);
            if (!res.ok) throw new Error('Not found');
            const data = await res.json();

            // Switch to upload section and show results
            App.showSection('upload');
            App.showResults(data);
        } catch (err) {
            console.error('View analysis error:', err);
        }
    },

    /**
     * Delete an analysis
     */
    async deleteAnalysis(id) {
        if (!confirm('Delete this analysis?')) return;

        try {
            const res = await fetch(`/api/analysis/${id}`, { method: 'DELETE' });
            if (res.ok) {
                this.data = this.data.filter(a => a.id !== id);
                this.render();
            }
        } catch (err) {
            console.error('Delete error:', err);
        }
    },

    /**
     * Render empty state
     */
    renderEmpty(msg) {
        const grid = document.getElementById('historyGrid');
        grid.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📋</span>
                <p>${msg || 'No analyses yet. Upload a food label to get started!'}</p>
            </div>
        `;
    }
};
