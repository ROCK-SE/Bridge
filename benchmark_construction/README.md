# Benchmark Construction

Before you proceed, you should first setup the environment for this step by following the instructions in the [INSTALL.md](../INSTALL.md).
Go through the README.md in each folder phase1-4 to run the framework.

To evaluate LLMs on the replacement API recommendation task, run the following commands:
```shell
# prepare the replacement API recommendation data
python llm_evaluation_data.py
OPENAI_API_KEY=<KEY> python llm_evaluation.py --level <LEVEL> --language <LANGUAGE> --model <MODEL NAME> --base-url <API ENDPOINT> --json-mode --workers <NUMBER OF WORKERS>
```
`LEVEL` can be `signature` or `context`, `LANGUAGE` can be `java` or `python`.
