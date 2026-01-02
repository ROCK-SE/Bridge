# Split all version dumping commits shas for each configuration file into 128 sections
python split_shas.py

# Get the modified files, new blobs, and old blobs for each commit
# Ensure the modified files have java or py extensions, \(.java;\|.py;\)
# New blob and old blob exists (some file modifications are file addition or deletion): [0-9a-f]\{40\};[0-9a-f]\{40\}
cd ../../benchmark/Phase1
for f in setup.cfg pyproject.toml setup.py requirements.txt; do
    for s in {0..15}; do
        for j in {0..7}; do
            i=$((j + s * 8))
            zcat /da7_data/basemaps/gz/c2fbbFull.V3.$i.s | grep ".py;[0-9a-f]\{40\};[0-9a-f]\{40\}" | join -t\; - ${f}_commits.$i > ${f}_update_commits.$i &
        done
        wait
    done
    wait
    cat ${f}_update_commits.{0..127} | sort -t\; -k1 >${f}_update_commits
    rm ${f}_update_commits..{0..127}
    rm ${f}_commits.{0..127}
    # remove reocrds that have changed setup.py or file in site-packages folder
    # and remove leading or trailing slashes
    awk -F';' '$2 !~ /\/?setup\.py|site-packages\//' ${f}_update_commits | awk -F';' 'BEGIN{OFS=";"} {gsub(/^\/+|\/+$/, "", $2); print}' > ${f}_update_commits.temp
    mv ${f}_update_commits.temp ${f}_update_commits
done


for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da7_data/basemaps/gz/c2fbbFull.V3.$i.s | grep ".java;[0-9a-f]\{40\};[0-9a-f]\{40\}" | join -t\; - pom.xml_commits.$i > pom.xml_update_commits.$i &
    done
    wait
done
wait
cat pom.xml_update_commits.{0..127} | sort -t\; -k1 >pom.xml_update_commits
rm pom.xml_update_commits..{0..127}
rm pom.xml_commits.{0..127}
awk -F';' 'BEGIN{OFS=";"} {gsub(/^\/+|\/+$/, "", $2); print}' pom.xml_update_commits > pom.xml_update_commits.temp
mv pom.xml_update_commits.temp pom.xml_update_commits
