/**
 * NutriCheck – Main Application Controller
 * Handles navigation, file upload, API calls, and view orchestration
 */

const App = {
    currentAnalysis: null,

    /**
     * Initialize the application
     */
    init() {
        this.bindNavigation();
        this.bindUpload();
        this.bindActions();
        this.showSection('upload');
    },

    // ==========================================
    //  NAVIGATION
    // ==========================================

    bindNavigation() {
        // Sidebar nav links
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const section = link.dataset.section;
                this.showSection(section);
            });
        });

        // Mobile menu toggle
        const toggle = document.getElementById('menuToggle');
        toggle.addEventListener('click', () => {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('open');
            this.toggleOverlay();
        });
    },

    showSection(name) {
        // Hide all sections
        document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));

        // Show target
        const target = document.getElementById(`section-${name}`);
        if (target) target.classList.remove('hidden');

        // Update nav active state
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        const activeLink = document.querySelector(`[data-section="${name}"]`);
        if (activeLink) activeLink.classList.add('active');

        // Update header
        const titles = {
            upload: 'Analyze Label',
            history: 'Analysis History',
            compare: 'Compare Products'
        };
        const subtitles = {
            upload: 'Upload a food label image to analyze its nutritional content',
            history: 'View all your past analyses',
            compare: 'Compare nutritional profiles across products'
        };
        document.getElementById('pageTitle').textContent = titles[name] || '';
        document.querySelector('.header-subtitle').textContent = subtitles[name] || '';

        // Load data for section
        if (name === 'history') History.load();
        if (name === 'compare') Comparison.load();

        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');
        this.removeOverlay();
    },

    toggleOverlay() {
        let overlay = document.querySelector('.sidebar-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'sidebar-overlay active';
            overlay.addEventListener('click', () => {
                document.getElementById('sidebar').classList.remove('open');
                this.removeOverlay();
            });
            document.body.appendChild(overlay);
        } else {
            overlay.classList.toggle('active');
        }
    },

    removeOverlay() {
        const overlay = document.querySelector('.sidebar-overlay');
        if (overlay) overlay.classList.remove('active');
    },

    // ==========================================
    //  FILE UPLOAD
    // ==========================================

    bindUpload() {
        const area = document.getElementById('uploadArea');
        const input = document.getElementById('fileInput');

        // Click to browse
        area.addEventListener('click', () => input.click());

        // File selected
        input.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.previewFile(e.target.files[0]);
            }
        });

        // Drag & drop
        area.addEventListener('dragover', (e) => {
            e.preventDefault();
            area.classList.add('dragover');
        });

        area.addEventListener('dragleave', () => {
            area.classList.remove('dragover');
        });

        area.addEventListener('drop', (e) => {
            e.preventDefault();
            area.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                this.previewFile(e.dataTransfer.files[0]);
            }
        });
    },

    previewFile(file) {
        // Validate
        const allowed = ['image/png', 'image/jpeg', 'image/bmp', 'image/webp'];
        if (!allowed.includes(file.type)) {
            alert('Please upload a valid image file (PNG, JPG, BMP, or WebP)');
            return;
        }
        if (file.size > 8 * 1024 * 1024) {
            alert('File too large. Maximum size is 8MB.\nPlease compress or resize the image first.\nTip: take a close-up screenshot of just the nutrition label.');
            return;
        }

        this.selectedFile = file;

        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('previewImage').src = e.target.result;
            document.getElementById('previewContainer').classList.remove('hidden');
            document.getElementById('uploadArea').classList.add('hidden');
            document.getElementById('resultsSection').classList.add('hidden');
        };
        reader.readAsDataURL(file);
    },

    // ==========================================
    //  ACTIONS
    // ==========================================

    bindActions() {
        // Analyze button
        document.getElementById('analyzeBtn').addEventListener('click', () => {
            this.analyzeImage();
        });

        // Clear button
        document.getElementById('clearBtn').addEventListener('click', () => {
            this.clearPreview();
        });

        // Download PDF
        document.getElementById('downloadPdfBtn').addEventListener('click', () => {
            if (this.currentAnalysis) {
                this.downloadPdf(this.currentAnalysis.id);
            }
        });

        // New analysis
        document.getElementById('newAnalysisBtn').addEventListener('click', () => {
            this.clearPreview();
            document.getElementById('resultsSection').classList.add('hidden');
        });

        // Refresh history
        document.getElementById('refreshHistoryBtn').addEventListener('click', () => {
            History.load();
        });

        // Compare button
        document.getElementById('compareBtn').addEventListener('click', () => {
            Comparison.compare();
        });
    },

    clearPreview() {
        document.getElementById('previewContainer').classList.add('hidden');
        document.getElementById('uploadArea').classList.remove('hidden');
        document.getElementById('fileInput').value = '';
        this.selectedFile = null;
    },

    // ==========================================
    //  API CALLS
    // ==========================================

    async analyzeImage() {
        if (!this.selectedFile) return;

        // Show loading
        document.getElementById('previewContainer').classList.add('hidden');
        const loading = document.getElementById('loadingOverlay');
        loading.classList.remove('hidden');

        // Progress steps — spaced to reflect actual OCR timing (20-60s on CPU)
        const steps = [
            'Uploading image...',
            'Preprocessing image for OCR...',
            'Running OCR — this takes 20-50s on CPU...',
            'Parsing nutrition table...',
            'Calculating health score...',
            'Almost done...'
        ];
        const stepEl = document.getElementById('loadingStep');
        stepEl.textContent = steps[0];
        let stepIndex = 0;
        // Advance quickly at first, then slow down during the long OCR phase
        const stepDelays = [1500, 3000, 15000, 10000, 5000];
        let stepTimer;
        const scheduleNext = (idx) => {
            if (idx >= stepDelays.length) return;
            stepTimer = setTimeout(() => {
                stepIndex = idx + 1;
                stepEl.textContent = steps[stepIndex] || steps[steps.length - 1];
                scheduleNext(stepIndex);
            }, stepDelays[idx]);
        };
        scheduleNext(0);

        // Upload and analyze
        const formData = new FormData();
        formData.append('image', this.selectedFile);

        try {
            // 195s client timeout — server allows 210s, giving a buffer
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 195000);

            const res = await fetch('/api/analyze', {
                method: 'POST',
                body: formData,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            clearTimeout(stepTimer);

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.error || 'Analysis failed');
            }

            const data = await res.json();
            this.showResults(data);

        } catch (err) {
            clearTimeout(stepTimer);
            loading.classList.add('hidden');
            this.clearPreview();
            if (err.name === 'AbortError') {
                alert('Analysis timed out — the image may be too large or complex.\n\nTips:\n• Use a close-up photo of just the nutrition label\n• Try a JPEG screenshot instead of a raw camera photo\n• Make sure the label is well-lit and text is sharp');
            } else {
                alert(`Error: ${err.message}`);
            }
        }
    },

    showResults(data) {
        this.currentAnalysis = data;

        // Hide loading, show results
        document.getElementById('loadingOverlay').classList.add('hidden');
        document.getElementById('uploadArea').classList.add('hidden');
        document.getElementById('previewContainer').classList.add('hidden');
        document.getElementById('resultsSection').classList.remove('hidden');

        // Render dashboard
        Dashboard.renderResults(data);
    },

    async downloadPdf(id) {
        try {
            const res = await fetch(`/api/report/${id}`);
            if (!res.ok) throw new Error('PDF generation failed');

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `nutricheck_report_${id}.pdf`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            alert(`Error: ${err.message}`);
        }
    }
};

// ==========================================
//  INIT
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
