# MemoryOS — Personal Cognitive Memory Engine

MemoryOS is a personal, privacy-first RAG-powered second brain that runs locally on your computer. It records your digital activity, strips secrets and credentials, indexes content in real time with SQLite FTS5, and provides instant full-text search.

---

## Quick Start on Windows

### 1. Requirements
- Windows 11 (PowerShell or Command Prompt)
- Python 3.12 (Managed via `.venv` or `uv`)

### 2. Start the Backend Server
Run the startup script in PowerShell:
```powershell
.\start_backend.ps1
```
Or directly using the virtual environment:
```powershell
.\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000 --reload
```

When started, MemoryOS will output:
- **API URL:** `http://127.0.0.1:8000`
- **Interactive Swagger Docs:** `http://127.0.0.1:8000/docs`
- **Data Directory:** `%APPDATA%\MemoryOS\`
- **Database Path:** `%APPDATA%\MemoryOS\memoryos.db`
- **Generated Security Token:** Saved in `%APPDATA%\MemoryOS\token.txt`

---

## Browser Extension Setup (Chrome / Edge / Brave)

1. Open your browser and navigate to the extensions management page:
   - **Chrome:** `chrome://extensions`
   - **Edge:** `edge://extensions`
   - **Brave:** `brave://extensions`
2. Enable **"Developer mode"** (toggle in the top-right or left sidebar).
3. Click **"Load unpacked"** and select the folder:
   ```
   E:\rag two\extension
   ```
4. Click the MemoryOS extension icon in your browser toolbar:
   - Copy the security token from `%APPDATA%\MemoryOS\token.txt` (or view it in your console) and paste it into the **Security Token** input in the popup, then click **Save**.
   - The status badge will turn **GREEN (Online)**.

---

## Testing & Verification Checklist

### 1. Confirm Backend is Running
Open a browser tab or PowerShell and query the health endpoint:
```powershell
curl http://127.0.0.1:8000/api/health
```
Expected output:
```json
{"status":"ok","service":"MemoryOS","version":"1.0.0"}
```

### 2. Check Security Token Protection
Querying protected endpoints without the token header will return `401 Unauthorized`:
```powershell
curl http://127.0.0.1:8000/api/status
```

Retrieve your token:
```powershell
Get-Content "$env:APPDATA\MemoryOS\token.txt"
```

Query with your security token header:
```powershell
$token = (Get-Content "$env:APPDATA\MemoryOS\token.txt").Trim()
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/status" -Headers @{"X-MemoryOS-Key" = $token}
```

### 3. Verify Event Ingestion from Browser
1. Browse to any public website (e.g. Wikipedia, Python docs, news article).
2. Open the MemoryOS extension popup; notice the **"Buffered Events"** counter increments.
3. Check the recent events recorded in your local database:
```powershell
$token = (Get-Content "$env:APPDATA\MemoryOS\token.txt").Trim()
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/events/recent?limit=5" -Headers @{"X-MemoryOS-Key" = $token}
```

### 4. Search Memory
Perform a keyword search using the SQLite FTS5 BM25 search engine:
```powershell
$token = (Get-Content "$env:APPDATA\MemoryOS\token.txt").Trim()
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/search?q=python" -Headers @{"X-MemoryOS-Key" = $token}
```

### 5. Instant Recording Pause & Incognito Protection
- Toggle **"Recording State"** to OFF in the extension popup. Subsequent browsing activity will not be recorded.
- Open an **Incognito / InPrivate** tab: the extension automatically skips incognito tabs completely.

---

## Running Automated Tests

Run the full pytest suite:
```powershell
.\.venv\Scripts\pytest -v tests
```
