import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        ssl_certfile=os.environ["SSL_CERT_FILE"],
        ssl_keyfile=os.environ["SSL_KEY_FILE"],
        proxy_headers=False
    )