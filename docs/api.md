# NutriCheck – REST API Documentation

Base URL: `http://localhost:5000`

---

## POST `/api/analyze`

Upload a food label image for analysis.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | File | Yes | Image file (PNG, JPG, JPEG, BMP, WebP, max 16MB) |

**Response:** `200 OK`
```json
{
  "id": 1,
  "product_name": "Granola Bar",
  "image_url": "/static/uploads/label_1707990000.jpg",
  "calories": 250,
  "sugar": 12,
  "fat": 8,
  "sodium": 180,
  "protein": 5,
  "fiber": 3,
  "health_score": 62,
  "verdict": "Consume in Moderation",
  "explanation": "Moderate sugar level (12g) contributes to a lower score.",
  "recommendation": "This product is acceptable in moderate quantities..."
}
```

**Errors:** `400` (no file / invalid type), `500` (analysis failed)

---

## GET `/api/history`

Return all past analyses, most recent first.

**Response:** `200 OK` — Array of analysis objects (same shape as analyze response).

---

## GET `/api/analysis/:id`

Return a single analysis by ID.

**Response:** `200 OK` — Analysis object, or `404` if not found.

---

## DELETE `/api/analysis/:id`

Delete an analysis.

**Response:** `200 OK` — `{ "message": "Deleted successfully" }`, or `404`.

---

## POST `/api/compare`

Compare multiple products.

**Request:** `application/json`
```json
{
  "ids": [1, 2, 3]
}
```

**Response:** `200 OK` — Array of analysis objects for the given IDs.

**Errors:** `400` (missing ids / fewer than 2)

---

## GET `/api/report/:id`

Generate and download a PDF report.

**Response:** `application/pdf` file download, or `404` / `500` on error.
