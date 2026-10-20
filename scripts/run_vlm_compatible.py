"""Use the isolated evaluation overlay without upgrading the main environment."""
import runpy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
overlay=root/"data/evaluation/vlm_runtime"
if not (overlay/"transformers").is_dir():
    raise SystemExit("Install the isolated runtime as documented in docs/ACCURACY_EVALUATION.md")
sys.path.insert(0,str(overlay))
sys.argv=[str(root/"scripts/evaluate_vlm.py")]+sys.argv[1:]
runpy.run_path(str(root/"scripts/evaluate_vlm.py"),run_name="__main__")
