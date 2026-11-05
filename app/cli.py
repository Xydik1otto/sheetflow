"""Console entry point: `sheetflow` boots the app with uvicorn."""
import os


def main() -> None:
    import uvicorn

    host = os.environ.get("SHEETFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("SHEETFLOW_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
