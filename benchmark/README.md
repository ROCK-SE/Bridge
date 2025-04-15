## Benchmark Statistics

This benchmark is constructed based on the V3 version of World of Code (Mid May, 2024).

| Configuration File | #ModifyCommits | #UniqueBlobs | #UpdateCommits | #Updates   | #Packages | #Releases |
| ------------------ | -------------- | ------------ | -------------- | ---------- | --------- | --------- |
| setup.cfg          | 1,229,076      | 719,294      | 29,832         | 64,098     | 1,976     | 14,333    |
| pyproject.toml     | 2,956,927      | 2,045,404    | 64,965         | 103,115    | 2,623     | 18,026    |
| setup.py           | 8,528,862      | 5,525,611    | 238,418        | 366,487    | 8,154     | 84,926    |
| requirements.txt   | 17,264,495     | 10,189,499   | 7,719,071      | 13,473,774 | 31,419    | 340,392   |
| pom.xml            | 97,785,879     | 63,959,850   | 6,103,952      | 15,314,119 | 67,923    | 1,105,308 |

- `#ModifyCommits`: the number of commits that modify the dependency configuration file. Derived from `<target file>_commits.csv` files in the  Commit Filtering stage.
- `#UniqueBlobs`: the number of unique configuration file blobs involved in the modifying commits. Derived from `<target file>_dependencies.json` files in the Dependency Parsing stage.
- `#UpdateCommits`: the number of commits that perform dependency version updates. Derived from `<target file>_updates.csv` files in the Version Update Extraction stage.


The following table presents the number of different types of update based on the differences among the major, minor, and patch part.

| Configuration File | Major              | Minor             | Patch             | Dev               | Total      |
| ------------------ | ------------------ | ----------------- | ----------------- | ----------------- | ---------- |
| setup.cfg          | 8,311(12.97%)      | 23,648(36.89%)    | 16,873(26.32%)    | 15,266(23.82%)    | 64,098     |
| pyproject.toml     | 12,640(12.26%)     | 31,306(30.36%)    | 27,741(26.90%)    | 31,428(30.48%)    | 103,115    |
| setup.py           | 60,605(16.54%)     | 128,781(35.14%)   | 94,377(25.75%)    | 82,724(22.57%)    | 366,487    |
| requirements.txt   | 2,934,473(21.78%)  | 5,699,163(42.30%) | 3,242,361(24.06%) | 1,597,777(11.86%) | 13,473,774 |
| pom.xml            | 1,802,688 (11.77%) | 6,744,627(44.04%) | 6,208,775(40.64%) | 558,029(3.6%)     | 15,314,119 |
