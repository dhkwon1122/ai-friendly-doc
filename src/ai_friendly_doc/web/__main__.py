"""웹 서버 실행 진입점: python -m ai_friendly_doc.web 또는 ai-friendly-doc-web"""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "12345"))
    uvicorn.run("ai_friendly_doc.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
