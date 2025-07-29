# Statistics of MongoDB Collections
This folder contains the information of MongoDB collections. Due to the large size of some collections, we include only some collections in the [replication package](https://figshare.com/s/4def2e9e1a5d9027c8c3), noted as "Yes" in the Replication column. In the replication package, each collection has two files: `<collection_name>.bson.gz` and `<collection_name>.metadata.json.gz`. All collections are dumped into gzipped files on the da5 server of the World of Code infrastructure. We do not provide their locations on the server currently for the requirements of anonymity. Once the paper gets accepted, we will publicize their locations. The schema of each collection is stored in the [`schemas`](./schemas/) folder, where each json file is named after the corresponding collection's name.


| Collection                          | Size      | Number of Documents | Replication |
| ----------------------------------- | --------- | ------------------- | ----------- |
| blob_changes                        | 16.41 GB  | 7,330,747           | No          |
| java_dependency_updates             | 877.94 MB | 6,749,613           | Yes         |
| py_dependency_updates               | 1.00 GB   | 8,868,950           | Yes         |
| java_api_calls                      | 65.97 GB  | 45,646,201          | No          |
| py_api_calls                        | 28.70 GB  | 15,841,501          | No          |
| java_api_call_changes               | 171.25 MB | 263,378             | Yes         |
| py_api_call_changes                 | 237.95 MB | 227,555             | Yes         |
| java_candidate_api_update_instances | 87.67 MB  | 121,495             | Yes         |
| py_candidate_api_update_instances   | 98.23 MB  | 76,761              | Yes         |
| java_existent_api_update_instances  | 57.48 MB  | 57,636              | Yes         |
