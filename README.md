# flow-ops-ai-server

Basic FastAPI server setup.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.
