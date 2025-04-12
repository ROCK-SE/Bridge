## Benchmark Statistics

This benchmark is constructed based on the V3 version of World of Code (Mid May, 2024).

| Configuration File | #ModifyCommits | #UniqueBlobs | #UpdateCommits | #Packages | #Updates   |
| ------------------ | -------------- | ------------ | -------------- | --------- | ---------- |
| setup.cfg          | 1,229,076      | 719,294      | 29,832         | 1,976     | 64,098     |
| pyproject.toml     | 2,956,927      | 2,045,404    | 64,965         | 2,623     | 103,115    |
| setup.py           | 8,528,862      | 5,525,611    | 238,418        | 8,154     | 366,487    |
| requirements.txt   | 17,264,495     | 10,189,499   | 7,719,071      | 31,419    | 13,473,774 |
| pom.xml            | 97,785,879     | 63,959,850   | 6,103,952      | 67,923    | 15,314,119 |

- `#ModifyCommits`: the number of commits that modify the dependency configuration file. Derived from `<target file>_commits.csv` files in the  Commit Filtering stage.
- `#UniqueBlobs`: the number of unique configuration file blobs involved in the modifying commits. Derived from `<target file>_dependencies.json` files in the Dependency Parsing stage.
- `#UpdateCommits`: the number of commits that perform dependency version updates. Derived from `<target file>_updates.csv` files in the Version Update Extraction stage.
