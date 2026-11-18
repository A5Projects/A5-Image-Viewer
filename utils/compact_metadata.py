"""Extract the Local Media Tools compact prompt summary from PNG text fields."""

import json
import re


def _json_object(text):
    # Local Media Tools also accepts JSON surrounded by a label or other text.
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        return None
    try:
        value = json.loads(text[first:last + 1])
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


_MODEL_FILE = re.compile(r"\.(safetensors|ckpt|pt|pth|bin)$", re.I)


def _loader_model(candidates):
    names = [v.strip() for v in candidates if isinstance(v, str) and v.strip()]
    return next((name for name in names if _MODEL_FILE.search(name)), names[0] if names else "")


def _set_prompt_fields(summary, texts):
    positives = []
    negatives = []
    for title, text in texts:
        target = negatives if "negative" in title.lower() else positives
        if text.strip() and text.strip() not in target:
            target.append(text.strip())
    # Some saved graphs have two untitled text encoders in positive/negative order.
    if not negatives and len(positives) > 1 and not any("positive" in title.lower() for title, _ in texts):
        positives, negatives = positives[:1], positives[1:]
    if positives:
        summary["positive_prompt"] = "\n---\n".join(positives)
    if negatives:
        summary["negative_prompt"] = "\n---\n".join(negatives)


def _workflow_summary(nodes):
    summary = {}
    texts = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = str(node.get("type", "")).lower()
        widgets = node.get("widgets_values")
        if not isinstance(widgets, list) or not widgets:
            continue
        first = widgets[0]
        if re.search(r"text ?encode|cliptextencode|t5", kind) and isinstance(first, str):
            texts.append((str(node.get("title", "")), first))
        if "ksamplerselect" in kind:
            summary["sampler"] = first
        if "basicscheduler" in kind:
            summary.update(zip(("scheduler", "steps", "denoise"), widgets))
        if "randomnoise" in kind:
            summary["seed"] = first
        if "fluxguidance" in kind:
            summary["cfg_scale"] = first
        if "loader" in kind:
            model = _loader_model(widgets)
            if model:
                summary["model"] = model
    _set_prompt_fields(summary, texts)
    return summary


def _graph_summary(graph):
    summary = {}
    texts = []
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        kind = str(node.get("class_type", "")).lower()
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if re.search(r"textencode|clip.*encode|t5.*encode", kind):
            prompt = inputs.get("text")
            if not isinstance(prompt, str):
                prompt = inputs.get("text_g")
            if isinstance(prompt, str):
                meta = node.get("_meta")
                title = meta.get("title", "") if isinstance(meta, dict) else ""
                texts.append((str(title), prompt))
        if "ksampler" in kind:
            for field in ("steps", "seed", "scheduler", "denoise"):
                if field in inputs:
                    summary[field] = inputs[field]
            if "cfg" in inputs or "guidance" in inputs:
                summary["cfg_scale"] = inputs.get("cfg", inputs.get("guidance"))
            if "sampler_name" in inputs:
                summary["sampler"] = inputs["sampler_name"]
        if re.search(r"empty.*latent.*image", kind):
            for field in ("width", "height"):
                if field in inputs:
                    summary[field] = inputs[field]
        if "loader" in kind:
            keys = ("ckpt_name", "model_name", "model", "unet_name", "vae_name", "checkpoint", "filename", "path")
            model = _loader_model(inputs.get(key) for key in keys)
            if model:
                summary["model"] = model
    _set_prompt_fields(summary, texts)
    return summary


def _invoke_summary(value):
    summary = {}
    fields = {
        "positive_prompt": ("prompt", "text", "positive_prompt"),
        "negative_prompt": ("negative_prompt", "neg"),
        "model": ("model", "model_name", "sd_model_name"),
        "sampler": ("sampler", "sampler_name"),
        "scheduler": ("scheduler",),
        "steps": ("steps",),
        "cfg_scale": ("cfg_scale", "cfg", "guidance"),
        "seed": ("seed",),
        "width": ("width",),
        "height": ("height",),
        "denoise": ("denoise", "denoising_strength"),
    }
    for field, names in fields.items():
        for name in names:
            item = value.get(name)
            if field == "model" and isinstance(item, dict):
                item = item.get("name") or item.get("model_name")
            if isinstance(item, (str, int, float)) and item != "":
                summary[field] = item
                break
    return summary


def _parameters_summary(text):
    # A1111 allows the positive prompt to be plain text with no "Prompt:" label.
    text = text.replace("\r\n", "\n")
    start = re.search(r"(?im)^\s*(?:Steps|Sampler):", text) or re.search(r"\b(?:Steps|Sampler):", text, re.I)
    prompt_text = text[:start.start()]
    settings = text[start.start():]
    prompts = re.split(r"(?im)^\s*Negative prompt:\s*", prompt_text, maxsplit=1)
    summary = {"positive_prompt": re.sub(r"(?i)^\s*Prompt:\s*", "", prompts[0]).strip()}
    if len(prompts) > 1:
        summary["negative_prompt"] = prompts[1].strip()
    fields = (
        ("steps", r"Steps:\s*(\d+)", int),
        ("cfg_scale", r"CFG scale:\s*([\d.]+)", float),
        ("sampler", r"Sampler:\s*([^,\n]+)", str.strip),
        ("scheduler", r"Scheduler:\s*([^,\n]+)", str.strip),
        ("seed", r"Seed:\s*(\d+)", int),
        ("model", r"Model(?: name)?:\s*([^,\n]+)", str.strip),
        ("denoise", r"Denoising strength:\s*([\d.]+)", float),
    )
    for field, pattern, convert in fields:
        match = re.search(r"\b" + pattern, settings, re.I)
        if match:
            try:
                summary[field] = convert(match.group(1))
            except ValueError:
                continue
    size = re.search(r"\bSize:\s*(\d{1,10})x(\d{1,10})\b", settings, re.I)
    if size:
        summary["width"], summary["height"] = map(int, size.groups())
    return summary


def _fallback_model(text_fields):
    for text in text_fields.values():
        for pattern in (
            r'"(?:ckpt_name|model_name|model|unet_name|vae_name)"\s*:\s*"([^"]+)"',
            r"\bModel(?: name)?:\s*([^,\n]+)",
            r"(?<![A-Za-z0-9 _.\-])([A-Za-z0-9 _.\-]+\.(?:safetensors|ckpt|pt|pth|bin))",
        ):
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).strip()
    return ""


def compact_png_summary(text_fields, size):
    """Return the converter's compact JSON fields, or None for an ordinary PNG."""
    texts = {k: v for k, v in text_fields.items() if isinstance(k, str) and isinstance(v, str)}
    objects = [(k, obj) for k, v in texts.items() if (obj := _json_object(v)) is not None]
    parts = []
    workflow = next((obj for _, obj in objects if isinstance(obj.get("nodes"), list)), None)
    if workflow:
        parts.append(_workflow_summary(workflow["nodes"]))
    for _, obj in objects:
        graph = obj.get("prompt") if isinstance(obj.get("prompt"), dict) else obj
        if any(isinstance(node, dict) and node.get("class_type") for node in graph.values()):
            parts.append(_graph_summary(graph))
    for key, obj in objects:
        invoke_keys = ("invokeai_version", "positive_prompt", "negative_prompt", "generation_mode", "cfg_scale")
        if (
            "invokeai" in key.lower() or any(k in obj for k in invoke_keys)
            or ("steps" in obj and any(k in obj for k in ("model", "prompt", "sampler", "seed")))
            or ("model" in obj and any(k in obj for k in ("prompt", "text")))
        ):
            parts.append(_invoke_summary(obj))
            break
    for key, text in texts.items():
        if "parameters" in key.lower() and re.search(r"\b(?:Steps|Sampler):", text, re.I):
            parts.append(_parameters_summary(text))
            break
    if not parts:
        return None

    # Prefer workflow prompt text. Later sources can fill missing prompts and
    # refine sampler details, following the standalone converter's precedence.
    summary = {}
    for part in parts:
        for field, value in part.items():
            if isinstance(value, (str, int, float)) and value != "":
                if field in ("positive_prompt", "negative_prompt"):
                    summary.setdefault(field, value)
                else:
                    summary[field] = value
    if "model" not in summary:
        model = _fallback_model(texts)
        if model:
            summary["model"] = model
    if not summary.keys() - {"width", "height"}:
        return None
    summary.setdefault("width", size[0])
    summary.setdefault("height", size[1])
    return {"source_format": "ComfyUI compact", **summary}
