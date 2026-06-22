/**
 * NutriCheck – Comparison Module
 * Handles multi-product comparison functionality
 */

const Comparison = {
    selectedIds: new Set(),

    /**
     * Load products for comparison selection
     */
    async load() {
        try {
            const res = await fetch('/api/history');
            if (!res.ok) throw new Error('Failed to load');
            const data = await res.json();
            this.renderSelection(data);
        } catch (err) {
            console.error('Comparison load error:', err);
        }
    },

    /**
     * Render product selection checkboxes
     */
    renderSelection(products) {
        const container = document.getElementById('compareSelection');

        if (!products || products.length < 2) {
            container.innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">⚖️</span>
                    <p>You need at least 2 analyzed products to compare. Analyze more labels first!</p>
                </div>
            `;
            return;
        }

        container.innerHTML = '';
        this.selectedIds.clear();

        products.forEach(p => {
            const item = document.createElement('label');
            item.className = 'compare-item';
            item.innerHTML = `
                <input type="checkbox" value="${p.id}">
                <span class="compare-item-name">${p.product_name || 'Unknown'}</span>
                <span class="compare-item-score" style="color: ${this.getScoreColor(p.health_score)}">${p.health_score}/100</span>
            `;

            const checkbox = item.querySelector('input');
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    this.selectedIds.add(p.id);
                    item.classList.add('selected');
                } else {
                    this.selectedIds.delete(p.id);
                    item.classList.remove('selected');
                }
                this.updateCompareButton();
            });

            container.appendChild(item);
        });
    },

    /**
     * Show/hide compare button based on selection
     */
    updateCompareButton() {
        const btn = document.getElementById('compareBtn');
        if (this.selectedIds.size >= 2) {
            btn.classList.remove('hidden');
            btn.textContent = `⚖️ Compare ${this.selectedIds.size} Products`;
        } else {
            btn.classList.add('hidden');
        }
    },

    /**
     * Run comparison
     */
    async compare() {
        const ids = Array.from(this.selectedIds);
        try {
            const res = await fetch('/api/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids })
            });
            if (!res.ok) throw new Error('Comparison failed');
            const data = await res.json();
            this.renderResults(data);
        } catch (err) {
            console.error('Compare error:', err);
        }
    },

    /**
     * Render comparison results
     */
    renderResults(products) {
        const container = document.getElementById('compareResults');
        container.classList.remove('hidden');
        container.innerHTML = '';

        // Find the winner (highest score)
        const maxScore = Math.max(...products.map(p => p.health_score || 0));
        const nutrients = ['calories', 'sugar', 'fat', 'sodium', 'protein', 'fiber'];
        const units = { calories: 'kcal', sugar: 'g', fat: 'g', sodium: 'mg', protein: 'g', fiber: 'g' };

        // For each nutrient, find best value
        const bestNutrient = {};
        const positiveNutrients = new Set(['protein', 'fiber']);

        nutrients.forEach(n => {
            const values = products.map(p => p[n] || 0);
            if (positiveNutrients.has(n)) {
                bestNutrient[n] = Math.max(...values);
            } else {
                bestNutrient[n] = Math.min(...values);
            }
        });

        products.forEach(p => {
            const isWinner = (p.health_score || 0) === maxScore && products.length > 1;
            const verdictClass = Dashboard.getVerdictClass(p.verdict);

            const card = document.createElement('div');
            card.className = `compare-product-card ${isWinner ? 'winner' : ''}`;

            let nutrientRows = nutrients.map(n => {
                const val = p[n] !== null && p[n] !== undefined ? p[n] : 'N/A';
                const isBest = val === bestNutrient[n] && val !== 'N/A';
                const isWorst = !isBest && val !== 'N/A';
                return `
                    <div class="compare-nutrient-row">
                        <span class="compare-nutrient-name">${n.charAt(0).toUpperCase() + n.slice(1)}</span>
                        <span class="compare-nutrient-value ${isBest ? 'best' : isWorst ? 'worst' : ''}">${val} ${val !== 'N/A' ? units[n] : ''}</span>
                    </div>
                `;
            }).join('');

            card.innerHTML = `
                ${isWinner ? '<div class="winner-badge">🏆 Best Pick</div>' : ''}
                <div class="compare-product-name">${p.product_name || 'Unknown'}</div>
                <div class="compare-score" style="color: ${this.getScoreColor(p.health_score)}">${p.health_score || 0}</div>
                <div class="compare-verdict ${verdictClass}">${p.verdict || ''}</div>
                <div class="compare-nutrients">${nutrientRows}</div>
            `;

            container.appendChild(card);
        });
    },

    /**
     * Get color for a score value
     */
    getScoreColor(score) {
        if (score >= 70) return '#00B894';
        if (score >= 40) return '#FDCB6E';
        return '#E17055';
    }
};
