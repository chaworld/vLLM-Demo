"""把模型權重下載到 HF_HOME 指定的快取目錄;可在容器內或宿主機直接執行。"""

from __future__ import annotations

import os
import sys

from huggingface_hub import snapshot_download

DEFAULT_MODEL_REPO = "Qwen/Qwen3.5-0.8B"


def main() -> int:
    repo_id = os.environ.get("MODEL_REPO", DEFAULT_MODEL_REPO)
    print(f"開始下載 {repo_id}(快取目錄 {os.environ.get('HF_HOME', '預設')})", flush=True)
    try:
        path = snapshot_download(repo_id=repo_id)
    except Exception as exc:  # 下載失敗時給出明確訊息,避免只留下堆疊
        print(f"下載失敗:{exc}", file=sys.stderr)
        return 1
    print(f"權重已就緒:{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
