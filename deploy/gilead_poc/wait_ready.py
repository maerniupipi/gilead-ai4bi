"""Wait for actual API readiness and the frontend before advertising URLs."""

import sys
import time

import httpx


def main() -> None:
    backend, frontend = map(int, sys.argv[1:3])
    deadline = time.monotonic() + 90
    with httpx.Client(timeout=3, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                api = client.get(f"http://127.0.0.1:{backend}/api/v2/health/ready")
                page = client.get(f"http://127.0.0.1:{frontend}/")
                if api.status_code == page.status_code == 200:
                    print("前端与后端健康检查通过。")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise SystemExit("启动未就绪，请查看前面的服务日志。")


if __name__ == "__main__":
    main()
