import gzip
#提供与操作系统相关的功能，如文件路径操作等
import os
#用于数据处理和分析，最终输出csv文件
import pandas as pd
#joblib用于并行化处理 Parallel和delayed允许你并行执行任务 提高效率
from joblib import Parallel, delayed
#tqdm提供进度图，跟踪任务进度
from tqdm import tqdm
from woc.local import WocMapsLocal

woc = WocMapsLocal()

c2fbb_base_path = "/da7_data/basemaps/gz/c2fbbFull.V3.{id}.s"
c2P_base_path = "/da7_data/basemaps/gz/c2PFull.V3.{id}.s"
#一个包含多个Git平台URL前缀的列表，用于规范化URL，录入gitlab.com
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

#该函数用于标准化URL，将其转为小写，去除末尾的斜杠（/）和.git后缀，确保URL一致性
def normalize_url(url: str):
    url = url.lower().strip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url

#该函数将WoC中的URL恢复为实际的URL，如果URL中包含_,它会将_替换为/，并根据前缀构建合适的URL。
#如果该前缀不在已知列表URL_PREFIXES中，则默认使用Github
def restore_url(woc_uri: str):
    if woc_uri.count("_") < 1:
        return
    prefix = woc_uri.split("_", 1)[0]
    if prefix not in URL_PREFIXES:
        url = f"https://github.com/" + woc_uri.replace("_", "/", 1)
        return normalize_url(url)

#该函数根据文件扩展名筛选提交记录，并收集与提交相关的项目信息
#它从c2PFull.V3.{i}.s中读取每个提交和相关项目，建立commit_projs字典
#然后，它遍历c2fFull.V3.{i}.s文件，检查每个文件路径是否符合给定的扩展名。
#如果符合条件，则提取提交、文件路径和相关的项目URL
def extension_based_selection(i: int, extensions: list[str]):
    #i:一个整数，表示文件ID，通常是用于标识不同的数据文件版本或范围
    #extension:一个字符串列表，包含文件扩展名（如.py .xml）该参数用于筛选哪些文件类型发生了更改
    result = []#空列表，用于存储最终筛选出的结果
    c2fbb_path = c2fbb_base_path.format(id=i)
    c2P_path = c2P_base_path.format(id=i)
    #c2fbb_path是与文件差异相关的文件，包含了每个文件的提交记录，修改前后的blob以及文件路径
    #c2P_path是一个项目与提交的映射文件，存储了每个提交对应的项目
    commit_projs = {}#用于存储提交哈希与项目的映射关系
    err_line = 0#用于统计读取文件时发生的错误行数
    with gzip.open(c2P_path) as inf:#打开压缩文件c2P_path
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")#将每行分隔为多个字段，得到一个列表
                commit, projs = entries[0], entries[1:]
                #提取提交哈希（commit）和与之相关的项目（projs）
                commit_projs[commit] = projs
                #将提交哈希与项目列表建立映射关系，保存在字典commit_projs中
            except:
                err_line += 1
    print(f"{len(commit_projs)} commits in c2PFull.V3.{i}.s, {err_line} error line(s)")

    err_line = 0
    with gzip.open(c2fbb_path) as inf:#打开压缩文件c2ff_path
        for line in inf:
            try:
                line = line.decode(encoding="utf-8")
                entries = line.strip("\n").split(";")
                #按分号将每行分隔为多个字段，得到一个列表。
                #每行记录包含提交哈希、文件路径、修改前后blob等信息
                if len(entries) != 4:
                    #如果该行的字段数量不等于4，则跳过该行，这里假设有效的记录应该有四个字段
                    continue
                if (entries[2] == "") or (entries[3] == ""):
                    #如果修改前或修改后的blob是空的，也跳过该行
                    continue
                commit, filepath = entries[:2]
                #提取提交哈希（commit）和文件路径（filepath）
                if any(filepath.endswith(ext) for ext in extensions):
                    projs = [restore_url(p) for p in commit_projs.get(commit, [])]
                    #获取与该提交相关的项目URLs，并将其恢复为标准URL格式
                    projs = [p for p in projs if p]#移除无效的URL
                    if len(projs) > 0:#如果该提交与至少一个项目相关，继续处理
                        result.append(entries + projs)
                        #将该条记录（提交哈希、文件路径、blob、项目列表）添加到result中
            except:
                err_line += 1
    print(#统计并输出成功筛选到的提交记录数（修改了指定扩展名的文件），以及处理过程中出错的行数
        f"{len(result)} commits modified {'/'.join(extensions)} files in c2fbbFull.V3.{i}.s, {err_line} error line(s)"
    )
    return result
#返回最终筛选的结果，其中每一条记录包含提交哈希、文件路径、修改前后的blob以及与该提交相关的项目URLs




#该函数用来比较文件的差异（diff）
#通过WoC API获取文件的两个版本（变更前和变更后），然后用difflib计算它们的差异
# def file_diff(line: str):
#     #传入的参数是一个字符串，表示一个文件的记录。
#     #通常是一个由逗号分隔的字段，其中包含了提交哈希、文件路径、修改前后的blob信息等
#     try:
#         entries = line.split(",")#将line字符串按逗号分割为多个字段，并将其存储在列表entries中
#         new_blob = woc.show_content("blob", entries[2]).splitlines()#新blob的SHA值
#         old_blob = woc.show_content("blob", entries[3]).splitlines()#旧blob的SHA值
#         #woc.show_content()能够根据blob的SHA值返回文件的内容
#         #splitlines()将文件内容按行分割，返回一个按行存储的列表，方便后续的逐行比较
#         diff = difflib.unified_diff(old_blob, new_blob, "old", "new", lineterm="", n=3)
#         #difflib.unified_diff()是python标准库difflib中的一个方法，用于生成unifiediff格式的差异
#         #n=3 表示在输出差异时，保留上下各3行的上下文（可以帮助开发者更清楚地看到差异前后的内容）
#         return "\n".join(diff)
#     #将diff生成器中的每一行差异连接起来，使用换行符\n分隔，以形成一个完整的差异字符串，并返回该字符串
#     except:
#         return
#该方法将返回一个生成器，生成文件内容的差异。如果有差异，生成的diff内容讲师unified diff格式





#该函数是程序的主入口，它先检查目标文件是否存在，如果不存在（或update=True）
#则调用extension_based_selection函数来筛选相关提交，并将结果保存到文件
#并行计算：使用joblib的Parallel和delayed来并行执行entension_based_selection和file_diff，提高处理效率
#文件差异：对于每个提交记录，计算文件的差异，并将差异添加到数据中
#结果保存，最后使用pandas将结果保存为csv文件，包含commit，filepath，new blob，old blob，diff和project字段
def extension_main(extensions: list[str], num_workers: int = 1, update: bool = False):
    #num_workers:并行计算的工作线程数，默认为1。该参数用于Parallel，以控制并发执行任务的数量
    #update:一个布尔值，决定是否在数据已存在时重新更新，如果为True，会强制重新获取数据
    save_path = f"/data/play/YuSun/Java/c2fbb_{''.join(extensions)}"
    #根据传入的{extensions}构建一个保存文件的路径，路径的命名方式为c2fbbps{extensions}
    print(save_path, os.path.exists(save_path))
    #检查保存路径下的文件是否已经存在，如果不存在或需要更新，则会执行数据处理操作
    if (not os.path.exists(save_path)) or update:
        result = Parallel(n_jobs=num_workers)(
        #Parallel(n_jobs=num_workers)：使用 joblib 库的并行计算功能，将多个任务并行处理。
        #每个任务调用 extension_based_selection 函数，从 WoC 数据中筛选出与指定扩展名（extensions）相关的文件修改记录。
            delayed(extension_based_selection)(i, extensions) for i in tqdm(range(128))
            #为每个数字 i（从 0 到 127）调用 extension_based_selection，传递 extensions 用于筛选特定扩展名的文件。
            #tqdm(range(128))来显示处理进度，表示对128个任务进行迭代
        )#result:存储所有并行处理任务的返回结果。每个 extension_based_selection 函数的结果是一个包含筛选文件修改记录的列表。
        with open(save_path, "w") as outf:
            for r in result:
                for data in r:
                    outf.write(",".join(data) + "\n")
        #将所有筛选出的文件修改记录写入到 save_path 指定的文件中。
        #每条记录是一个由逗号分隔的字符串，表示提交哈希、文件路径、blob 的哈希值等信息。

    lines = []
    with open(save_path) as inf:
        lines = inf.read().splitlines()
    print(f"{len(lines)} lines")
    #读取保存的文件，lines列表将存储文件中的每一行
    #打印出文件中有多少行数据


    result = []


    for line in lines:
        entries = line.split(",")
        if len(entries) > 6:  # 确保每行至少有 6 个字段（包括 commit sha, filepath, new blob sha, old blob sha, project）
            continue
        result.append(entries[:5] + [entries[5]])  # 只保留 commit, filepath, new blob sha, old blob sha, project
    



    result = pd.DataFrame(
        result,
        columns=["commit", "filepath", "new blob", "old blob", "project"],
        #将处理后的结果转换为一个 pandas DataFrame，并指定列名（commit, filepath, new blob, old blob, diff, project）
    )
    result.to_csv(f"/data/play/YuSun/Java/c2fbb_{''.join(extensions)}.csv", index=False)
    #将 DataFrame 保存为 CSV 格式的文件，文件名由 extensions 决定，保存路径为 /data/play/kgao/c2fbbdp{''.join(extensions)}.csv

#主程序
#功能：这部分是命令行接口（CLI）部分，允许用户通过命令行传递参数
#参数：
# -n或--num_workers:指定并行任务的数量
# -e或--extensions：指定要筛选的文件扩展名，多个扩展名用逗号分隔
#执行：
#根据传入的扩展名调用extension_main函数来筛选提交并生成CSV文件
if __name__ == "__main__":
    import argparse
    #argparse 是 Python 的标准库，用于解析命令行参数。
    #通过 argparse，用户可以在命令行运行脚本时传递参数，脚本根据这些参数执行相应的操作 

    parser = argparse.ArgumentParser(
        #ArgumentParser()：创建一个 ArgumentParser 对象，用来处理命令行参数。
        prog="python project_commits_copy.py",
        description="Select commits and projects that modify files with specific extensions or using specific libraries/packages/frameworks",
        #prog="python project_commits.py"：指定脚本的名称，会在帮助信息中显示。
        #description="..."：提供对该脚本的描述，帮助信息中会显示，帮助用户理解脚本的功能。
    )
    parser.add_argument(
        "-n", "--num_workers", type=int, default=1, help="number of threads"
        #-n / --num_workers：这是一个命令行选项，用户可以传入一个整数值来指定并行计算的工作线程数。

    )
    parser.add_argument(
        #-e / --extensions：这是一个命令行选项，允许用户指定一个由逗号分隔的文件扩展名列表。
        #例如，".py,.java,.cpp"，表示要选择 .py、.java 和 .cpp 这些文件扩展名
        "-e",
        "--extensions",
        type=str,
        #表示该参数需要是一个字符串
        help="selection using file extensions separated by ,",
    )

    args = parser.parse_args()
    #parse_args()：解析命令行传入的参数，将解析结果存储在 args 变量中。
    #args 是一个包含所有命令行参数的对象，用户传入的参数可以通过 args 访问

    if args.extensions:
        extensions = args.extensions.split(",")
        #args.extensions.split(",")：将用户传入的扩展名字符串按逗号分割成一个列表。
        #例如，".py,.java" 会被拆分成 [".py", ".java"]
        print(extensions)
        extension_main(extensions, args.num_workers)
        #调用之前定义的 extension_main 函数，传递扩展名列表和并行工作线程数（args.num_workers）。
        #该函数会根据这些扩展名筛选相关的文件，并进行后续处理。
#总结
#该程序筛选在特定扩展名（如.py,.xml等）文件上发生过变更的提交
#它提取相关的项目信息，提交SHA、文件路径、以及变更的差异diff
#最后，将结果保存到csv文件中，方便进一步分析和处理

#运行脚本：
#python project_commits_code.py -e "pom.xml" -n 4
 