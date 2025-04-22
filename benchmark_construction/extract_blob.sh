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

# Get all unique blobs in obtained c2fbb
cut -d\; -f3,4 c2fbb | tr -s ';' '\n' | sort -u >all_blobs
echo $(cut -d\; -f1 c2fbb | sort -u | wc -l) commits modified $(cat all_blobs | wc -l) java/python blobs
# 7,330,749 commits modified 62,246,912 java/python blobs

# Split all blobs into 128 sections
cd -
python split_shas.py -f all_blobs -c 0 -p blob -n 128

for s in {0..31}; do
    for j in {0..3}; do
        i=$((j + s * 4))
        cat /data/All.blobs/blob_$i.idx | awk -F\; '{if(NF>5){print $5";"$2";"$3}else{print $4";"$2";"$3}}' | sort -t\; -T. -S 15G -k1,1 | join -t\; -o 1.1 1.2 1.3 - blob.$i >blob_$i.idx &
    done
    wait
done
