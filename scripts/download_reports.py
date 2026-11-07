"""下载 data/manifest.json 里列出的财报 PDF，保存到 data/raw/。

已存在且校验通过的文件会跳过，所以可以重复运行。
"""

import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
RAW_DIR = ROOT / "data" / "raw"
USER_AGENT = "finance-rag-study/0.1"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(client: httpx.Client, url: str, target: Path) -> None:
    """先写临时文件，确认是 PDF 后再改名，避免留下下载一半的文件。"""
    tmp = target.with_suffix(".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with tmp.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    if tmp.read_bytes()[:5] != b"%PDF-":
        tmp.unlink()
        raise ValueError(f"下载到的不是 PDF：{url}")
    tmp.replace(target)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    reports = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with httpx.Client(
        timeout=180, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for report in reports:
            target = RAW_DIR / f"{report['doc_id']}.pdf"
            expected = report.get("sha256")
            if target.exists() and (not expected or sha256_of(target) == expected):
                print(f"跳过 {target.name}")
                continue
            download(client, report["url"], target)
            actual = sha256_of(target)
            if expected and actual != expected:
                raise ValueError(f"{target.name} 校验失败：{actual}")
            print(f"完成 {target.name} {target.stat().st_size / 1e6:.1f} MB {actual}")


if __name__ == "__main__":
    main()
