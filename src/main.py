import os
import uvicorn

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    uvicorn.run("src.__init__:create_app", host="0.0.0.0", port=port, factory=True, reload=True)
