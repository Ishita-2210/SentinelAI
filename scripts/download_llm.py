"""Explicit cache setup; runtime inference never downloads models."""
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download,HfApi
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--model-id",default="HuggingFaceTB/SmolLM2-135M-Instruct")
    ap.add_argument("--download",action="store_true",help="Explicitly allow the one-time weights download")
    ap.add_argument("--max-download-mb",type=float,default=400)
    args=ap.parse_args()
    patterns=["model*.safetensors*","config.json","generation_config.json","tokenizer*",
              "special_tokens_map.json","vocab.json","merges.txt","*.model"]
    try:
        cached=Path(snapshot_download(args.model_id,local_files_only=True,allow_patterns=patterns))
        if list(cached.glob("*.safetensors")):
            print("Using local cache:",cached);return
    except Exception:pass
    if not args.download:
        raise SystemExit("Model not cached. Pass --download to permit the one-time download; no event/image data is sent.")
    info=HfApi().model_info(args.model_id,files_metadata=True)
    weights=[f for f in info.siblings if "/" not in f.rfilename and f.rfilename.endswith(".safetensors")]
    size=sum(f.size or 0 for f in weights)
    if not size:raise SystemExit("Cannot verify root safetensors size; refusing an unbounded download")
    print("Weight download MB:",round(size/1000000,1),"; reserve additional cache/tokenizer space.",flush=True)
    if size>args.max_download_mb*1000000:
        raise SystemExit("Model exceeds explicit --max-download-mb limit")
    print(snapshot_download(args.model_id,allow_patterns=patterns))
if __name__=="__main__":main()
