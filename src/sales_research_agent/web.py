"""MVP 本地浏览器入口，不引入额外 Web 框架依赖。"""

import asyncio
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from sales_research_agent.config import Settings

REQUIRED_FIELDS = ("customer_name", "scenario", "known_context", "research_goal")


def validate_web_payload(raw: dict[str, str]) -> dict[str, str]:
    """校验浏览器表单并返回可直接创建 Brief 的最小字段集合。"""
    if not all(raw.get(key, "").strip() for key in REQUIRED_FIELDS):
        raise ValueError(
            "customer_name, scenario, known_context, research_goal are required"
        )
    return {key: raw[key].strip() for key in REQUIRED_FIELDS}


def serve(settings: Settings, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动本地阻塞式浏览器入口，报告制品仍由本地文件系统保存。"""
    from sales_research_agent.cli import _start_live_run

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self._send(200, _form_page())
                return
            prefix = "/runs/"
            suffix = "/report.html"
            if self.path.startswith(prefix) and self.path.endswith(suffix):
                run_id = self.path[len(prefix) : -len(suffix)]
                if "/" not in run_id and run_id:
                    report = settings.run_root / run_id / "artifacts" / run_id / "reports" / "report.html"
                    if report.is_file():
                        self._send(200, report.read_text(encoding="utf-8"))
                        return
            self._send(404, "Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if self.path != "/research":
                self._send(404, "Not found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
                payload = validate_web_payload({key: values.get(key, [""])[0] for key in REQUIRED_FIELDS})
            except (UnicodeDecodeError, ValueError, TypeError):
                self._send(400, _error_page("输入不完整，请填写全部字段。"))
                return
            run_id = str(uuid4())
            try:
                asyncio.run(_start_live_run(settings, payload, run_id))
            except Exception:  # noqa: BLE001
                self._send(500, _error_page("调研运行失败，请查看本地运行日志和 inspect 汇总。"))
                return
            self._send(200, _success_page(run_id))

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"sales-research web: http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _form_page() -> str:
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>售前公网调研</title>
<body><main><h1>售前客户公网调研</h1><p>仅使用公网信息；每条事实都需要证据支持。</p>
<form method="post" action="/research"><label>客户名称<br><input name="customer_name" required></label><br>
<label>场景<br><textarea name="scenario" required></textarea></label><br>
<label>已知背景<br><textarea name="known_context" required></textarea></label><br>
<label>研究目标<br><textarea name="research_goal" required></textarea></label><br>
<button type="submit">开始调研</button></form></main></body></html>"""


def _success_page(run_id: str) -> str:
    safe_id = html.escape(run_id, quote=True)
    return f"<html lang='zh-CN'><meta charset='utf-8'><title>调研完成</title><body><h1>调研完成</h1><p>运行 ID：<code>{safe_id}</code></p><a href='/runs/{safe_id}/report.html'>打开 HTML 报告</a></body></html>"


def _error_page(message: str) -> str:
    return f"<html lang='zh-CN'><meta charset='utf-8'><title>调研失败</title><body><p>{html.escape(message)}</p><a href='/'>返回</a></body></html>"
