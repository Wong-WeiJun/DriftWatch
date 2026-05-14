import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)1.1s %(asctime)s %(pathname)s:%(lineno)d] %(message)s',
    datefmt='%y%m%d %H:%M:%S',
) 
app = FastAPI(title="Driftwatch")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "flood-monitor"}





