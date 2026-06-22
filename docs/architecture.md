# NutriCheck – System Architecture

## High-Level Architecture

```mermaid
graph TB
    subgraph "Frontend (Browser)"
        UI[HTML/CSS/JS SPA]
        UP[Upload Module]
        DB_UI[Dashboard Module]
        HIST[History Module]
        COMP[Compare Module]
    end

    subgraph "Backend (Flask)"
        API[REST API Layer]
        AS[Analysis Service]
        IMG[Image Processor<br/>OpenCV]
        OCR[OCR Service<br/>EasyOCR]
        NP[Nutrient Parser<br/>Regex Engine]
        HS[Health Scorer<br/>Nutri-Score Model]
        PDF[PDF Generator<br/>ReportLab]
    end

    subgraph "Data Layer"
        SQLite[(SQLite Database)]
        FS[File System<br/>Uploads & Reports]
    end

    UI --> API
    UP --> API
    DB_UI --> API
    HIST --> API
    COMP --> API

    API --> AS
    API --> PDF
    AS --> IMG
    AS --> OCR
    AS --> NP
    AS --> HS
    AS --> SQLite
    PDF --> FS
    AS --> FS

    style UI fill:#6C5CE7,color:#fff
    style API fill:#74B9FF,color:#fff
    style AS fill:#00B894,color:#fff
    style SQLite fill:#FDCB6E,color:#333
```

## Data Flow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant A as Flask API
    participant IP as Image Processor
    participant O as EasyOCR
    participant NP as Nutrient Parser
    participant HS as Health Scorer
    participant DB as SQLite

    U->>F: Upload food label image
    F->>A: POST /api/analyze (multipart)
    A->>IP: Preprocess image
    IP-->>A: Cleaned image
    A->>O: Extract text (OCR)
    O-->>A: Raw text blocks
    A->>NP: Parse nutrients
    NP-->>A: Structured nutrients
    A->>HS: Calculate health score
    HS-->>A: Score + Verdict + Explanation
    A->>DB: Save analysis
    DB-->>A: Row ID
    A-->>F: JSON response
    F->>F: Render dashboard
    F-->>U: Display results
```

## Folder Structure

```
NutriCheck/
├── app.py                      # Flask entry point & routes
├── config.py                   # Configuration constants
├── database.py                 # SQLite schema & CRUD
├── requirements.txt            # Python dependencies
├── models/
│   ├── health_scorer.py        # Nutri-Score hybrid model
│   └── nutrient_parser.py      # OCR text → nutrients
├── services/
│   ├── analysis_service.py     # Pipeline orchestrator
│   ├── image_processor.py      # OpenCV preprocessing
│   ├── ocr_service.py          # EasyOCR wrapper
│   └── pdf_service.py          # ReportLab PDF generation
├── static/
│   ├── css/style.css           # Dark glassmorphism theme
│   ├── js/
│   │   ├── app.js              # Main controller
│   │   ├── dashboard.js        # Gauge & nutrient rendering
│   │   ├── comparison.js       # Product comparison
│   │   └── history.js          # History management
│   ├── uploads/                # User-uploaded images
│   └── reports/                # Generated PDF reports
├── templates/
│   └── index.html              # SPA shell
└── docs/
    ├── architecture.md         # This file
    └── api.md                  # API documentation
```

## Database Schema

```mermaid
erDiagram
    ANALYSES {
        int id PK
        text product_name
        text image_path
        real calories
        real sugar
        real fat
        real sodium
        real protein
        real fiber
        int health_score
        text verdict
        text explanation
        text recommendation
        text raw_ocr_text
        datetime created_at
    }
```

## Health Scoring Model

```mermaid
graph LR
    subgraph "Negative Points (0-40)"
        CAL[Calories] --> N1[0-10 pts]
        SUG[Sugar] --> N2[0-10 pts]
        FAT[Fat] --> N3[0-10 pts]
        SOD[Sodium] --> N4[0-10 pts]
    end

    subgraph "Positive Points (0-15)"
        PRO[Protein] --> P1[0-7.5 pts]
        FIB[Fiber] --> P2[0-7.5 pts]
    end

    N1 & N2 & N3 & N4 --> CALC["Score = 100 - Negative + Positive"]
    P1 & P2 --> CALC

    CALC --> V{Score}
    V -->|"≥ 70"| H[Healthy Choice ✅]
    V -->|"40-69"| M[Moderate ⚠️]
    V -->|"< 40"| L[Limit ❌]

    style H fill:#00B894,color:#fff
    style M fill:#FDCB6E,color:#333
    style L fill:#E17055,color:#fff
```
