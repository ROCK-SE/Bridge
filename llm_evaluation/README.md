# LLM Evaluation

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).

`evaluate.py` evaluate LLMs via Ollama APIs on the recommending replacement API and updating code to a newer dependency version tasks. It has the following command line options:
```
usage: python evaluate.py [-h] -m MODEL [-p] [-i] -g GROUP [-b BATCH_SIZE] -l LANG

Evaluate LLMs on the recommending replacement API and updating code to a newer dependency version tasks

options:
  -h, --help            show this help message and exit
  -m MODEL, --model MODEL
                        a list of model names separated by comma(,)
  -p, --pair            the recommending replacement API task
  -i, --instance        the updating code to a newer dependency version task
  -g GROUP, --group GROUP
                        groups exact/full separated by comma(,)
  -b BATCH_SIZE, --batch_size BATCH_SIZE
                        the number of API update pairs in each batch request to reduce tokens
  -l LANG, --lang LANG  languages java/python separated by comma(,)
```
Run the following command to evaluate GPT-4.1, Claude-3.7-Sonnet, DeepSeek-V3, and Qwen-Plus.
```shell
python -u evaluate.py --model gpt-4.1,claude-3.7-sonnet,deepseek-v3,qwen-plus -l java,python -g exact,full --pair --instance
```
It produces the following 24 files in the [result](../result/) folder.
- `{gpt-4.1,claude-3.7-sonnet,deepseek-v3,qwen-plus}-{java,python}-pair-{exact,full}.json`. Each record has the following fields: `package`, `old_version`, `old_api`, `new_version`, `new_api`, and `output`.
- `{gpt-4.1,claude-3.7-sonnet,deepseek-v3,qwen-plus}-{java,python}-instance-exact.json`. Each record has the following fields: `package`, `old_api`, `new_api`, `old_version`, `new_version`, `commit`, `old_code`, `old_args`, `new_code`, `new_args`, `major`, `update_type`, and `output`.

Then, run `result-analysis.ipynb` to obtain the evaluation results.
