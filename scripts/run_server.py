import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if __name__ == "__main__":
    import uvicorn

    print("Starting FastAPI server...")
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000, reload=True)
