import gzip
import pandas as pd
from joblib import Parallel, delayed
from tqdm import tqdm
from woc.local import WocMapsLocal
import os

woc = WocMapsLocal()

c2fbb_base_path = "/da7_data/basemaps/gz/c2fbbFull.V3.{id}.s"
c2P_base_path = "/da7_data/basemaps/gz/c2PFull.V3.{id}.s"

URL_PREFIXES = [
    "gitlab.com",
    "bitbucket.org",
    "0xacab.org",
    "android.googlesource.com",
    "bioconductor.org",
    "blitiri.com.ar",
    "code.ill.fr",
    "code.qt.io",
    "drupal.com",
    "fedorapeople.org",
    "forgemia.inra.fr",
    "framagit.org",
    "gcc.git",
    "git.alpinelinux.org",
    "git.debian.org",
    "git.eclipse.org",
    "git.kernel.org",
    "git.openembedded.org",
    "git.pleroma.social",
    "git.postgresql.org",
    "git.savannah.gnu.org",
    "git.savannah.nongnu.org",
    "git.torproject.org",
    "git.unicaen.fr",
    "git.unistra.fr",
    "git.xfce.org",
    "git.yoctoproject.org",
    "git.zx2c4.com",
    "gitbox.apache.org",
    "gite.lirmm.fr",
    "gitlab.adullact.net",
    "gitlab.cerema.fr",
    "gitlab.common-lisp.net",
    "gitlab.fing.edu.uy",
    "gitlab.freedesktop.org",
    "gitlab.gnome.org",
    "gitlab.huma-num.fr",
    "gitlab.inria.fr",
    "gitlab.irstea.fr",
    "gitlab.ow2.org",
    "invent.kde.org",
    "kde.org",
    "notabug.org",
    "pagure.io",
    "repo.or.cz",
    "salsa.debian.org",
    "sourceforge.net",
]



# 该函数用于标准化URL，将其转为小写，去除末尾的斜杠（/）和.git后缀，确保URL一致性
def normalize_url(url: str):
    url = url.lower().strip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url

# 该函数将WoC中的URL恢复为实际的URL
def restore_url(woc_uri: str):
    if woc_uri.count("_") < 1:
        return
    prefix = woc_uri.split("_", 1)[0]
    if prefix not in URL_PREFIXES:
        url = f"https://github.com/" + woc_uri.replace("_", "/", 1)
        return normalize_url(url)

# 该函数根据文件名筛选提交记录，并收集与提交相关的项目信息
def extension_based_selection(i: int, target_files: list):
    result = []  # 用于存储最终筛选出的结果
    c2fbb_path = c2fbb_base_path.format(id=i)
    c2P_path = c2P_base_path.format(id=i)
    
    commit_projs = {}  # 用于存储提交哈希与项目的映射关系
    err_line = 0
    
    # 读取c2PFull.V3.{i}.s文件
    with gzip.open(c2P_path) as inf:
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")
                commit, projs = entries[0], entries[1:]
                commit_projs[commit] = projs
            except:
                err_line += 1
    print(f"{len(commit_projs)} commits in c2PFull.V3.{i}.s, {err_line} error line(s)")

    err_line = 0
    with gzip.open(c2fbb_path) as inf:
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")
                if len(entries) != 4 or (entries[2] == "") or (entries[3] == ""):
                    continue
                commit, filepath = entries[:2]
                
                # 严格匹配文件名，确保完全匹配如 "pom.xml" 等文件名
                if any(filepath == target for target in target_files):  
                    projs = [restore_url(p) for p in commit_projs.get(commit, [])]
                    projs = [p for p in projs if p]  # 移除无效的URL
                    if len(projs) > 0:
                        result.append(entries + projs)
            except:
                err_line += 1

    print(f"{len(result)} commits modified {', '.join(target_files)} files in c2fbbFull.V3.{i}.s, {err_line} error line(s)")
    return result

# 处理不同类型文件，保存到不同的CSV
def extension_main(target_files: list[str], num_workers: int = 1, update: bool = False):
    save_path = f"/data/play/YuSun/Modified/modified_files"
    print(save_path, os.path.exists(save_path))
    if (not os.path.exists(save_path)) or update:
        result = Parallel(n_jobs=num_workers)(
            delayed(extension_based_selection)(i, target_files) for i in tqdm(range(128))
        )
        
        # 先将所有文件按照文件类型分类
        result_dict = {target: [] for target in target_files}
        
        for r in result:
            for data in r:
                for target in target_files:
                    # 严格匹配文件名，确保文件名完全等于目标文件名
                    if data[1] == target:
                        result_dict[target].append(data)
                        break
        
        # 保存为不同的CSV文件
        for target, data in result_dict.items():
            if data:
                df = pd.DataFrame(
                    data,
                    columns=["commit", "filepath", "new blob", "old blob", "project"]
                )
                df.to_csv(f"{save_path}_{target}.csv", index=False)
                
    else:
        print(f"Data already exists at {save_path}, skipping update.")

# 主程序
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        prog="python project_commits_copy.py",
        description="Select commits and projects that modify files with specific extensions or using specific libraries/packages/frameworks"
    )
    
    parser.add_argument(
        "-n", "--num_workers", type=int, default=1, help="number of threads"
    )
    parser.add_argument(
        "-e", "--extensions", type=str, help="selection using file extensions separated by ,"
    )
    
    args = parser.parse_args()
    
    if args.extensions:
        extensions = args.extensions.split(",")
        print(extensions)
        extension_main(extensions, args.num_workers)
