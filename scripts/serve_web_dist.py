from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SpaRequestHandler(SimpleHTTPRequestHandler):
    def send_head(self):  # type: ignore[no-untyped-def]
        candidate = Path(self.translate_path(self.path))
        if not candidate.exists() and "Accept" in self.headers:
            accepts_html = "text/html" in self.headers.get("Accept", "")
            has_extension = bool(Path(self.path.split("?", 1)[0]).suffix)
            if accepts_html and not has_extension:
                self.path = "/index.html"
        return super().send_head()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the built Planora SPA with history fallback.")
    parser.add_argument("--directory", type=Path, default=Path("web/dist"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    handler = lambda *handler_args, **kwargs: SpaRequestHandler(  # noqa: E731
        *handler_args,
        directory=str(args.directory.resolve()),
        **kwargs,
    )
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
