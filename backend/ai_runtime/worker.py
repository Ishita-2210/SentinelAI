"""Private stdin/stdout worker used only by the local Python backend."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
protocol = sys.stdout

def send(value):
    protocol.write(json.dumps(value)+"\n")
    protocol.flush()

def prepare_llm_inputs(tokenizer, request, max_tokens=1536):
    """Fit whole records while retaining the complete system prompt/question."""
    messages = request["messages"]
    context = request.get("context_events")
    if context is not None:
        context = list(context)
    while True:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt", truncation=False)
        if inputs["input_ids"].shape[1] <= max_tokens:
            break
        if not context:
            raise ValueError("Question and system prompt exceed the local context budget")
        context.pop()
        messages = [messages[0], {"role":"user", "content":
            "Events: "+json.dumps(context)+"\nQuestion: "+request["question"]}]
    allowed = [event["id"] for event in context] if context is not None else request.get("allowed_event_ids")
    return inputs, allowed


def main():
    config = json.loads(sys.stdin.readline())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if config["kind"] == "vlm":
                overlay = config.get("runtime_path")
                if overlay:
                    overlay = Path(overlay)
                    if not (overlay/"transformers").is_dir():
                        raise RuntimeError("Compatible Florence runtime missing: "+str(overlay))
                    sys.path.insert(0, str(overlay))
            import torch
            torch.set_num_threads(config["cpu_threads"])
            if config["kind"] == "vlm":
                from backend.vlm_runtime.verifier import VisualVerifier
                model = VisualVerifier(base_model_id=config["model_id"],
                    adapter_dir=config.get("adapter_dir"), device="cpu",
                    max_new_tokens=config["max_new_tokens"])
                if not model.is_ready:
                    raise RuntimeError("Florence did not load")
                meta = dict(adapter_loaded=model.adapter_loaded, device="cpu",
                            adapter_requested=config.get("adapter_dir"),
                            adapter_warning=("Requested adapter unavailable; using base model"
                                if config.get("adapter_dir") and not model.adapter_loaded else None))
            else:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(config["model_id"], local_files_only=True)
                model = AutoModelForCausalLM.from_pretrained(config["model_id"],
                    local_files_only=True, torch_dtype=torch.float32).to("cpu").eval()
                meta = dict(device="cpu", dtype="float32")
        send(dict(type="ready", meta=meta))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        send(dict(type="load_error", error=str(exc)))
        return
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if config["kind"] == "vlm":
                    import io
                    from PIL import Image
                    image_bytes = Path(request["image_path"]).read_bytes()
                    digest = hashlib.sha256(image_bytes).hexdigest()
                    if request.get("evidence_sha256") and digest != request["evidence_sha256"]:
                        raise ValueError("Evidence changed after verification was queued")
                    with Image.open(io.BytesIO(image_bytes)) as image:
                        result = model.verify(image, request["question"])
                    data = dict(answer=result.answer, raw_text=result.raw_text,
                                confidence=None, adapter_loaded=result.adapter_loaded,
                                error=result.error, model_id=config["model_id"], task=result.task,
                                evidence_sha256=digest)
                    if result.error: raise RuntimeError(result.error)
                else:
                    inputs, allowed = prepare_llm_inputs(tokenizer, request)
                    constrained = {}
                    if allowed is not None:
                        if len(allowed)>20 or any(type(x) is not int or x<1 for x in allowed):
                            raise ValueError("Invalid allowed event IDs")
                        candidates = [json.dumps({"event_ids":[x]},separators=(",",":")) for x in allowed]
                        candidates.append('{"event_ids":[]}')
                        sequences = [tokenizer.encode(text,add_special_tokens=False) for text in candidates]
                        prompt_length = inputs["input_ids"].shape[1]
                        def allowed_tokens(batch_id, token_ids):
                            prefix=token_ids[prompt_length:].tolist()
                            next_tokens=set()
                            for sequence in sequences:
                                if sequence[:len(prefix)]==prefix:
                                    next_tokens.add(sequence[len(prefix)] if len(prefix)<len(sequence) else tokenizer.eos_token_id)
                            return list(next_tokens) or [tokenizer.eos_token_id]
                        constrained["prefix_allowed_tokens_fn"]=allowed_tokens
                    with torch.inference_mode():
                        tokens = model.generate(**inputs, max_new_tokens=config["max_new_tokens"],
                            do_sample=False, num_beams=1, pad_token_id=tokenizer.eos_token_id,**constrained)
                    answer = tokenizer.decode(tokens[0, inputs["input_ids"].shape[1]:],
                                              skip_special_tokens=True).strip()
                    data = dict(text=answer, input_tokens=inputs["input_ids"].shape[1],
                                generated_tokens=tokens.shape[1]-inputs["input_ids"].shape[1],
                                model_id=config["model_id"])
            send(dict(type="result", id=request["id"], data=data))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            send(dict(type="result", id=request.get("id"), error=str(exc)))
if __name__ == "__main__":
    main()
