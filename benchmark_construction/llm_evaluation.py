"""Run the signature or context level replacement API evaluation.

The script consumes examples constructed from the validated final dataset and
calls an OpenAI compatible chat completions endpoint. Results are appended to
JSONL so interrupted runs can be resumed safely.
"""

import argparse
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from llm_evaluation_data import context_level_dataset, signature_level_dataset
from openai import OpenAI
from tqdm import tqdm

SYSTEM_PROMPT = """You are an expert in library API evolution. Given a library version update and a legacy API, identify the API in the new library version that should replace the legacy API.

Return exactly one JSON object and no additional text:
{"replacement_api": "<API signature>"}

The replacement must belong to the specified library and be available in the new version. If uncertain, return your single best recommendation."""

JAVA_PROMPT = """A project updates the following Java library:

Library: {library}
Old version: {old_version}
New version: {new_version}

The following legacy API is deprecated or removed:

Legacy API: {legacy_api}

Recommend the replacement API in the new version.

Represent the replacement using its fully qualified API signature. Include parameter types in the same source-level notation as the legacy API when the replacement has parameters. Use this format:

package.Class.method(parameterType1,parameterType2)"""

PYTHON_PROMPT = """A project updates the following Python library:

Library: {library}
Old version: {old_version}
New version: {new_version}

The following legacy API is deprecated or removed:

Legacy API: {legacy_api}

Recommend the replacement API in the new version.

Represent the replacement using its public fully qualified name in this format:

module.submodule.api"""

JAVA_CONTEXT_PROMPT = """A project updates the following Java library:

Library: {library}
Old version: {old_version}
New version: {new_version}

The following legacy API is deprecated or removed:

Legacy API: {legacy_api}

The legacy API call occurs in the following client code context:

```java
{context}
```

Recommend the replacement API in the new version.

Represent the replacement using its fully qualified API signature. Include parameter types in the same source-level notation as the legacy API when the replacement has parameters. Use this format:

package.Class.method(parameterType1,parameterType2)"""

PYTHON_CONTEXT_PROMPT = """A project updates the following Python library:

Library: {library}
Old version: {old_version}
New version: {new_version}

The following legacy API is deprecated or removed:

Legacy API: {legacy_api}

The legacy API call occurs in the following client code context:

```python
{context}
```

Recommend the replacement API in the new version.

Represent the replacement using its public fully qualified name in this format:

module.submodule.api"""


def write_jsonl_row(file: Any, row: dict[str, Any]) -> None:
    file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    file.flush()


def summarize(
    examples: list[dict], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    selected = [results[e["query_id"]] for e in examples if e["query_id"] in results]
    completed = [row for row in selected if row.get("request_error") is None]
    correct = sum(bool(row.get("exact_match")) for row in completed)
    parse_failures = sum(bool(row.get("parse_error")) for row in completed)
    request_failures = sum(bool(row.get("request_error")) for row in selected)
    return {
        "examples": len(examples),
        "responses": len(selected),
        "completed_responses": len(completed),
        "correct": correct,
        "exact_match_accuracy": correct / len(completed) if completed else None,
        "parse_failures": parse_failures,
        "request_failures": request_failures,
    }


def load_examples(language: str, level: str) -> list[dict[str, Any]]:
    path = f"../benchmark/llm_evaluation/{language}_{level}_level.jsonl"
    if not os.path.exists(path):
        if level == "signature":
            signature_level_dataset(language)
        else:
            context_level_dataset(language)

    samples = []
    required_fields = {
        "query_id",
        "language",
        "library",
        "old_version",
        "new_version",
        "legacy_api",
        "reference_replacement",
    }
    if level == "context":
        required_fields.add("context")

    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from error

            missing = required_fields.difference(row)
            if missing:
                fields = ", ".join(sorted(missing))
                raise ValueError(f"Missing fields at {path}:{line_number}: {fields}")
            if row["language"] != language:
                raise ValueError(
                    f"Unexpected language at {path}:{line_number}: "
                    f"{row['language']!r}"
                )
            if level == "context" and (
                not isinstance(row["context"], str) or not row["context"].strip()
            ):
                raise ValueError(f"Empty context at {path}:{line_number}")
            samples.append(row)
    return samples


def sample_examples(
    examples: list[dict], limit: int | None = None, seed: int = 42
) -> list[dict]:
    if limit is None or limit >= len(examples):
        return examples
    rng = random.Random(seed)
    return sorted(rng.sample(examples, limit), key=lambda example: example["query_id"])


def safe_model_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_") or "model"


def read_latest_results(path: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not os.path.exists(path):
        return latest
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from error
            latest[row["query_id"]] = row
    return latest


def build_user_prompt(example: dict, level: str) -> str:
    if level == "context":
        template = (
            JAVA_CONTEXT_PROMPT
            if example["language"] == "java"
            else PYTHON_CONTEXT_PROMPT
        )
    else:
        template = JAVA_PROMPT if example["language"] == "java" else PYTHON_PROMPT

    values = {
        "library": example["library"],
        "old_version": example["old_version"],
        "new_version": example["new_version"],
        "legacy_api": example["legacy_api"],
    }
    if level == "context":
        values["context"] = example["context"]
    return template.format(**values)


def parse_response(content: str) -> tuple[str | None, str | None]:
    """Strictly parse the requested JSON response.

    Additional prose, Markdown fences, additional fields, and multiple candidates
    are format errors and are scored as incorrect.
    """
    try:
        payload = json.loads(content.strip())
    except json.JSONDecodeError as error:
        return None, f"invalid JSON: {error.msg}"

    if not isinstance(payload, dict):
        return None, "response is not a JSON object"
    if set(payload) != {"replacement_api"}:
        return None, "response must contain only the replacement_api field"
    prediction = payload["replacement_api"]
    if not isinstance(prediction, str) or not prediction.strip():
        return None, "replacement_api must be a nonempty string"
    return prediction.strip(), None


def normalize_signature(signature: str, language: str) -> str:
    signature = signature.strip()
    if language == "java":
        # Java signatures in the dataset use source-level parameter notation.
        signature = re.sub(r"\s+", "", signature)
        owner, separator, parameters = signature.partition("(")
        if separator:
            # java.lang types may be written with or without their implicit prefix.
            parameters = re.sub(r"\bjava\.lang\.(?=[A-Z])", "", parameters)
            return f"{owner}({parameters}"
        return signature
    return signature


def score_prediction(
    prediction: str | None,
    reference_replacement: str,
    language: str,
) -> tuple[str | None, bool]:
    if prediction is None:
        return None, False
    normalized = normalize_signature(prediction, language)
    reference = normalize_signature(reference_replacement, language)
    return normalized, normalized == reference


def response_usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def evaluate_one(client: Any, example: dict, args) -> dict[str, Any]:
    user_prompt = build_user_prompt(example, args.level)
    request: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": args.max_tokens,
    }
    if not args.omit_temperature:
        request["temperature"] = args.temperature
    if args.json_mode:
        request["response_format"] = {"type": "json_object"}
    if args.model.startswith("deepseek-v4") or args.model.startswith("glm"):
        request["extra_body"] = {"thinking": {"type": "disabled"}}

    started = time.perf_counter()
    base = {
        **example,
        "model": args.model,
        # "system_prompt": SYSTEM_PROMPT,
        # "user_prompt": user_prompt,
    }
    try:
        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content or ""
        prediction, parse_error = parse_response(content)
        normalized_prediction, exact_match = score_prediction(
            prediction, example["reference_replacement"], example["language"]
        )
        return {
            **base,
            "raw_response": content,
            "prediction": prediction,
            "normalized_prediction": normalized_prediction,
            "parse_error": parse_error,
            "exact_match": exact_match,
            "request_error": None,
            "latency_seconds": round(time.perf_counter() - started, 3),
            **response_usage(response),
        }
    except Exception as error:  # Provider SDK exceptions vary by endpoint.
        return {
            **base,
            "raw_response": None,
            "prediction": None,
            "normalized_prediction": None,
            "parse_error": None,
            "exact_match": False,
            "request_error": f"{type(error).__name__}: {error}",
            "latency_seconds": round(time.perf_counter() - started, 3),
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }


def run(args: argparse.Namespace) -> None:
    examples = sample_examples(
        load_examples(args.language, args.level), args.limit, args.seed
    )
    print(f"Select {len(examples):,} {args.level}-level examples")

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Environment variable {args.api_key_env} is not set")

    output_file = f"{args.language}_{args.level}_{safe_model_name(args.model)}.jsonl"
    output_path = f"../benchmark/llm_evaluation/{output_file}"
    if args.overwrite and os.path.exists(output_path):
        with open(output_path, "w") as f:
            pass

    latest = read_latest_results(output_path)

    # Successful requests, including format errors, are final. Transport and
    # provider errors are retried when the script is resumed.
    pending = [
        example
        for example in examples
        if example["query_id"] not in latest
        or latest[example["query_id"]].get("request_error") is not None
    ]
    print(f"Evaluating {len(pending):,} pending examples with {args.model}")

    client_options: dict[str, Any] = {
        "api_key": api_key,
        "timeout": args.timeout,
        "max_retries": args.max_retries,
    }
    if args.base_url:
        client_options["base_url"] = args.base_url
    client = OpenAI(**client_options)

    with open(output_path, "a", encoding="utf-8") as outf:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(evaluate_one, client, example, args): example
                for example in pending
            }
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"{args.level.capitalize()} evaluation",
            ):
                row = future.result()
                latest[row["query_id"]] = row
                write_jsonl_row(outf, row)

    summary = {
        "language": args.language,
        "model": args.model,
        "evaluation_level": args.level,
        "seed": args.seed,
        **summarize(examples, latest),
    }
    summary_file = output_file.rsplit(".", 1)[0] + ".summary.json"
    summary_path = f"../benchmark/llm_evaluation/{summary_file}"
    with open(summary_path, "w") as outf:
        outf.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate an OpenAI-compatible LLM on replacement API recommendation."
    )
    parser.add_argument(
        "--level",
        choices=("signature", "context"),
        required=True,
        help="Input setting to evaluate",
    )
    parser.add_argument("--language", choices=("java", "python"), required=True)
    parser.add_argument(
        "--model", required=True, help="Model identifier sent to the API"
    )
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--omit-temperature",
        action="store_true",
        help="Do not send temperature to endpoints that reject this parameter",
    )
    parser.add_argument(
        "--json-mode",
        action="store_true",
        help="Request JSON mode from endpoints that support response_format",
    )
    parser.add_argument(
        "--limit", type=int, help="Evaluate a reproducible random subset"
    )
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    return parser


if __name__ == "__main__":
    parsed_args = build_parser().parse_args()
    run(parsed_args)
