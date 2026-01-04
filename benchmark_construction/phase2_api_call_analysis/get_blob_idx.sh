# Get the offset and length of each blob object
cd ../../benchmark/Phase2
for p in {py,java}; do
    for s in {0..31}; do
        for j in {0..3}; do
            i=$((j + s * 4))
            cat /data/All.blobs/blob_$i.idx | awk -F\; '{if(NF>5){print $5","$2","$3}else{print $4","$2","$3}}' | sort -t\, -T. -S 15G -k1,1 | join -t\, -o 1.1 1.2 1.3 - ${p}_blob.$i >${p}_blob_$i.idx &
        done
        wait
    done
    wait
    rm {p}_blob.{0..127}
    cat ${p}_blob_{0..127}.idx > ${p}_blob.idx
    rm ${p}_blob_{0..127}.idx
done
