import argparse
import json

from openai import OpenAI
from tqdm import tqdm, trange

config = json.load(open("config.json"))
client = OpenAI(base_url=config["BASE_URL"], api_key=config["API_KEY"])


def build_pair_prompt(pairs: list[dict]):
    prompt_instructions = (
        "You are an API migration assistant specializing in Java library upgrades. For each numbered item below, "
        "provide the corresponding replacement API's fully qualified name. "
        "Each item is formatted as `groupId:artifactId,old_version,old_api,new_version`. "
        "Your response should be a numbered list, with each line containing only "
        "the replacement API for the corresponding input item. **Do not add any extra text or explanations**."
    )

    items = []
    for i, pair in enumerate(pairs, start=1):
        items.append(
            f"{i}. {pair['package']},{pair['old_version']},{pair['old_api']},{pair['new_version']}"
        )
    formatted_items = "\n".join(items)
    full_prompt = f"{prompt_instructions}\n\n{formatted_items}"

    return full_prompt


def build_instance_prompt(pair: dict):
    prompt_instructions = (
        "You are an API migration assistant specializing in Java library upgrades. "
        "Given a code snippet that uses deprecated APIs from an older version of a Java library, "
        "rewrite the code to use the equivalent APIs in the new library version.\n"
        "Library: {package}\n"
        "Old version: {old_version}\n"
        "New version: {new_version}\n"
        "```\n"
        "{old_code}\n"
        "```\n"
        "Requirements:\n"
        "1. Use only APIs available in {package} version {new_version}\n"
        "2. Maintain identical functionality\n"
        "3. Include necessary import statements if they need to change\n"
        "4. Provide ONLY the refactored code with no additional explanations or markdown formatting."
    )
    return prompt_instructions.format(
        package=pair["package"],
        old_version=pair["old_version"],
        new_version=pair["new_version"],
        old_code=pair["old_code"],
    )


def pair_response(model_name: str, pairs: list[dict]):
    res = []
    try:
        prompt = build_pair_prompt(pairs)
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model_name,
            temperature=0,
        )
        content = response.choices[0].message.content
        if "</think>" in content:
            content = content.split("</think>", 1)[-1].strip()
        content = content.split("\n")
        for i in range(min(len(pairs), len(content))):
            res.append(pairs[i] | {"output": content[i].split(" ", 1)[-1]})
        return res

    except Exception as e:
        print(f"[{model_name} Error]: {e}")
        return []


def instance_response(model_name: str, pair: dict) -> dict:
    try:
        prompt = build_instance_prompt(pair)
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model_name,
            temperature=0,
        )
        content = response.choices[0].message.content
        if "</think>" in content:
            content = content.split("</think>", 1)[-1].strip()
        return pair | {"output": content}
    except Exception as e:
        print(f"[{model_name} Error]: {e}")
        return pair


def pairs_main(model_name: str, lang: str, group: str, batch_size: int = 10):
    pairs = json.load(open(f"../benchmark/final/{lang}_sampled_api_pairs_{group}.json"))
    print(f"{len(pairs)} {lang} update pairs in {group} group")
    res = []
    for i in trange(0, len(pairs), batch_size):
        res.extend(pair_response(model_name, pairs[i : i + batch_size]))
    with open(f"../result/{model_name}-{lang}-pair-{group}.json", "w") as outf:
        json.dump(res, outf, indent=2)


def instance_main(model_name: str, lang: str, group: str):
    pairs = json.load(
        open(f"../benchmark/final/{lang}_sampled_update_instances_{group}.json")
    )
    print(f"{len(pairs)} {lang} update instances in {group} group")
    res = []
    for i in trange(0, len(pairs)):
        res.append(instance_response(model_name, pairs[i]))
    with open(f"../result/{model_name}-{lang}-instance-{group}.json", "w") as outf:
        json.dump(res, outf, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python evaluate.py",
        description="Evaluate LLMs on the recommending replacement API and updating code to a newer dependency version tasks",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        required=True,
        help="a list of model names separated by comma(,)",
    )
    parser.add_argument(
        "-p",
        "--pair",
        action="store_true",
        help="the recommending replacement API task",
    )
    parser.add_argument(
        "-i",
        "--instance",
        action="store_true",
        help="the updating code to a newer dependency version task",
    )
    parser.add_argument(
        "-g",
        "--group",
        type=str,
        required=True,
        help="groups exact/full separated by comma(,)",
    )
    parser.add_argument(
        "-b",
        "--batch_size",
        type=int,
        default=10,
        help="the number of API update pairs in each batch request to reduce tokens",
    )
    parser.add_argument(
        "-l",
        "--lang",
        type=str,
        required=True,
        help="languages java/python separated by comma(,)",
    )

    args = parser.parse_args()

    for lang in args.lang.split(","):
        for model in args.model.split(","):
            if args.pair:
                for group in args.group.split(","):
                    print(f"Evaluating {model} on {lang} {group} pair dataset")
                    pairs_main(model, lang, group, args.batch_size)
            if args.instance:
                group = "exact"
                print(f"Evaluating {model} on {lang} {group} instance dataset")
                instance_main(model, lang, group)
