# Installation Guide

## Benchmark Construction
Code in the `benchmark_construction` folder is developed on the World of Code da5 server. To run these code, you should have/create a [World of Code account](https://github.com/woc-hack/tutorial?tab=readme-ov-file#before-you-start). Then, put the following in your ssh configuration file (e.g., `~/.ssh/config`):
```
Host da5
	Hostname da5.eecs.utk.edu
	Port 22
	User YourUsername
```
Now you should be able to log into the `da5` server by typing `ssh da5` in your terminal.

We use [Miniconda](https://docs.anaconda.com/miniconda/install/) to manage Python development environment. The following commands create and activate a `LLM-DepUp` conda environment and install necessary packages to run code in the `benchmark_construction` folder.
```shell
conda create -n LLM-DepUp python==3.11
conda activate LLM-DepUp
pip install -r requirements-benchmark.txt
```
We aslo use [pre-commit](https://pre-commit.com/) to perform format checks.
```shell
pip install pre-commit
pre-commit install
```

## LLM Evaluation
After constructing the benchmark, you may transfer to datasets to local and evaluate LLMs. If so, create the same `LLM-DepUp` conda environment and `pre-commit` following above instructions. Then, install dependencies listed in `requirements-evaluation.txt`:
```shell
pip install -r requirements-benchmark.txt
```
We evaluate LLMs via the Ollama API. You should provide your `API_KEY` and `BASE_URL` in the `config.json` in the `llm_evaluation` folder. They are used to populate the `base_url` and `api_key` arguments in `openai.OpenAI()`.
