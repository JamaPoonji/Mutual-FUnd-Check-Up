"""python -m api  serves the start page and POST /api/analyze on port 8000."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.app:app", host="127.0.0.1", port=8000)
