import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from solvers.tier3_api import app
import os

# Serve the static files from the stitch folder
static_dir = os.path.join(os.path.dirname(__file__), "stitch")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    # Return the main dashboard HTML when visiting the root URL
    return FileResponse(os.path.join(static_dir, "main_ops_dashboard.html"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
