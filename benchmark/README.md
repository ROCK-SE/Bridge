## Benchmark Statistics

This benchmark is constructed based on the V3 version of World of Code (Mid May, 2024).

| Configuration File | #ModifyCommits | #UniqueBlobs | #UpdateCommits |
| ------------------ | -------------- | ------------ | -------------- |
| setup.cfg          | 1,229,076      | 719,294      | 30,392         |
| pyproject.toml     | 2,956,927      | 2,045,404    | 72,225         |
| setup.py           | 8,528,862      | 5,525,611    | 254,728        |
| requirements.txt   | 17,264,495     | 10,189,499   | 9,708,535      |
| pom.xml            | 97,785,879     | 63,959,850   | 8,385,661      |

- `#ModifyCommits`: the number of commits that modify the dependency configuration file. Derived from `<target file>_commits.csv` files in the  Commit Filtering stage.
- `#UniqueBlobs`: the number of unique configuration file blobs involved in the modifying commits. Derived from `<target file>_dependencies.json` files in the Dependency Parsing stage.
- `#UpdateCommits`: the number of commits that perform dependency version updates. Derived from `<target file>_updates.csv` files in the Version Update Extraction stage.
