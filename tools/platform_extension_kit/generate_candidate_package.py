"""Generate a review-only Platform Package skeleton from an approved candidate fact."""
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

def main():
    p=argparse.ArgumentParser(); p.add_argument("--package-id",required=True); p.add_argument("--image-ref",required=True); p.add_argument("--image-digest",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    if not a.package_id.replace("-","").replace("_","").isalnum() or not a.image_digest.startswith("sha256:"): raise SystemExit("非法候选 Package 参数")
    root=Path(a.output).resolve()/a.package_id; root.mkdir(parents=True,exist_ok=True)
    (root/"manifest.yaml").write_text(yaml.safe_dump({"id":a.package_id,"version":"0.1.0-candidate","state":"PENDING_INTEGRATION"},allow_unicode=True))
    (root/"image.lock.yaml").write_text(yaml.safe_dump({"image":a.image_ref,"digest":a.image_digest},allow_unicode=True))
    (root/"README.md").write_text("# 候选 Platform Package\n\n仅用于受控接入测试；审核发布前不能执行 REAL 任务。\n")
if __name__ == "__main__": main()
