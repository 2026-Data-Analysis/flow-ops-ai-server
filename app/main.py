from fastapi import FastAPI

app = FastAPI(title="Flow Ops AI Server")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Flow Ops AI Server is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
