# Split all commits shas into 128 sections
python split_shas.py -f all_commits -c 0 -p c -n 128

# Get the modified files, new blobs, and old blobs for each commit
# Ensure the modified files have java or py extensions, \(.java;\|.py;\)
# New blob and old blob exists (some file modifications are file addition or deletion): [0-9a-f]\{40\};[0-9a-f]\{40\}
cd ../benchmark/updates
for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da7_data/basemaps/gz/c2fbbFull.V3.$i.s | grep "\(.java;\|.py;\)[0-9a-f]\{40\};[0-9a-f]\{40\}" | join -t\; - c.$i >c2fbb.$i &
    done
    wait
done
wait
cat c2fbb.{0..127} | sort -t\; -k1 >c2fbb
rm c2fbb.{0..127}
rm c.{0..127}
rm all_commits
echo $(cat c2fbb | wc -l) records in c2fbb
# 139,389,700 records in c2fbb

# Get all unique Python and Java blobs in obtained c2fbb
cat c2fbb | grep ".py;" | cut -d\; -f3,4 | tr -s ';' '\n' | sort -u >pyblobs
echo $(cat c2fbb | grep ".py;" | cut -d\; -f1 | sort -u | wc -l) commits modified $(cat pyblobs | wc -l) python blobs
# 3,500,391 commits modified 15,890,764 python blobs
cat c2fbb | grep ".java;" | cut -d\; -f3,4 | tr -s ';' '\n' | sort -u >javablobs
echo $(cat c2fbb | grep ".java;" | cut -d\; -f1 | sort -u | wc -l) commits modified $(cat javablobs | wc -l) java blobs
# 3,907,437 commits modified 46,356,165 java blobs
# 7,330,749 commits modified 62,246,912 java blobs

# Split all Python and Java blobs into 128 sections
cd -
python split_shas.py -f pyblobs -c 0 -p pyblob -n 128
python split_shas.py -f javablobs -c 0 -p javablob -n 128

# Get the offset and length of each blob object
cd ../benchmark/updates
for p in {py,java}; do
    for s in {0..31}; do
        for j in {0..3}; do
            i=$((j + s * 4))
            cat /data/All.blobs/blob_$i.idx | awk -F\; '{if(NF>5){print $5";"$2";"$3}else{print $4";"$2";"$3}}' | sort -t\; -T. -S 15G -k1,1 | join -t\; -o 1.1 1.2 1.3 - ${p}blob.$i >${p}blob_$i.idx &
        done
        wait
    done
done
rm pyblob.{0..127}
rm javablob.{0..127}
cat pyblob_{0..127}.idx >pyblob.idx
rm pyblob_{0..127}.idx
cat javablob_{0..127}.idx >javablob.idx
rm javablob_{0..127}.idx
