# Split commit shas into 32 sections
python split_shas.py -f c2fpkgvvtype.csv -c 0 -p c -n 32 -s 1
echo $(cat c.* | wc -l) commits
# 14,092,985 commits

# Get child commits. Since the V3 version of c2cc and c2pc maps were not available
# at the experiment time. We use the later V2409 version, which is a superset of V3.
cd ../benchmark/updates
for s in {0..3}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2ccFull.V2409.$i.s | join -t\; - c.$i >c2cc.tmp.$i &
    done
    wait
done
wait
cat c2cc.tmp.{0..31} | sort -t\; -k1 >c2cc.tmp
rm c2cc.tmp.{0..31}

# Get parent commits.
for s in {0..3}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2pcFull.V2409.$i.s | join -t\; - c.$i >c2pc.tmp.$i &
    done
    wait
done
wait
cat c2pc.tmp.{0..31} | sort -t\; -k1 >c2pc.tmp
rm c2pc.tmp.{0..31}

# Split child commits and parent commits into 128 sections
cd -
python split_shas.py -f c2cc.tmp -c 1 -p cc -n 128 -d\;
python split_shas.py -f c2pc.tmp -c 1 -p pc -n 128 -d\;

# Get child commit's author time
cd ../benchmark/updates
for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2datFull.V2409.$i.s | cut -d\; -f1,2 | join -t\; - cc.$i >cc2t.$i &
    done
    wait
done
wait
cat cc2t.{0..127} | sort -t\; -k1 >cc2t
rm cc2t.{0..127}
rm cc.{0..127}

# Get parent commit's author time
for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2datFull.V2409.$i.s | cut -d\; -f1,2 | join -t\; - pc.$i >pc2t.$i &
    done
    wait
done
wait
cat pc2t.{0..127} | sort -t\; -k1 >pc2t
rm pc2t.{0..127}
rm pc.{0..127}

# Select the nearest child commit
sort -t\; -k2 c2cc.tmp | join -t\; -1 2 -2 1 -a 1 -o 1.1 1.2 2.2 - cc2t | sort -t\; -k1,1 -k3,3 | cut -d\; -f1,2 | sort -t\; -u -k1,1 -o c2cc
rm c2cc.tmp
echo $(cat c2cc | wc -l) commits has $(cut -d\; -f2 c2cc | sort -u | wc -l) child commit
# 8,782,517 commits has 8,522,827 child commit

# Select the nearest parent commit
sort -t\; -k2 c2pc.tmp | join -t\; -1 2 -2 1 -a 1 -o 1.1 1.2 2.2 - pc2t | sort -t\; -k1,1 -k3,3 | cut -d\; -f1,2 | sort -t\; -u -k1,1 -o c2pc
rm c2pc.tmp
echo $(cut c2pc | wc -l) commits has $(cut -d\; -f2 c2pc | sort -u | wc -l) parent commit
# 14,092,985 commits has 6,915,290 parent commit

# Merge all commits
cat c.{0..31} | sort >c
rm c.{0..31}

# Split child commits and parent commits into 32 sections
cd -
python split_shas.py -f c2cc -c 1 -p cc -n 32 -d\;
python split_shas.py -f c2pc -c 1 -p pc -n 32 -d\;

# Get child commits' child commit
cd ../benchmark/updates
for s in {0..3}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2ccFull.V2409.$i.s | join -t\; - cc.$i >cc2ccc.tmp.$i &
    done
    wait
done
wait
cat cc2ccc.tmp.{0..31} | sort -t\; -k1 >cc2ccc.tmp
rm cc2ccc.tmp.{0..31}

# Get parent commits' parent commit
for s in {0..3}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2pcFull.V2409.$i.s | join -t\; - pc.$i >pc2ppc.tmp.$i &
    done
    wait
done
wait
cat pc2ppc.tmp.{0..31} | sort -t\; -k1 >pc2ppc.tmp
rm pc2ppc.tmp.{0..31}

# Split child child commits and parent parent commits into 128 sections
cd -
python split_shas.py -f cc2ccc.tmp -c 1 -p ccc -n 128 -d\;
python split_shas.py -f pc2ppc.tmp -c 1 -p ppc -n 128 -d\;

# Get child child commit's author time
cd ../benchmark/updates
for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2datFull.V2409.$i.s | cut -d\; -f1,2 | join -t\; - ccc.$i >ccc2t.$i &
    done
    wait
done
wait
cat ccc2t.{0..127} | sort -t\; -k1 >ccc2t
rm ccc2t.{0..127}
rm ccc.{0..127}

# Get parent parent commit's author time
cd ../benchmark/updates
for s in {0..15}; do
    for j in {0..7}; do
        i=$((j + s * 8))
        zcat /da8_data/basemaps/gz/c2datFull.V2409.$i.s | cut -d\; -f1,2 | join -t\; - ppc.$i >ppc2t.$i &
    done
    wait
done
wait
cat ppc2t.{0..127} | sort -t\; -k1 >ppc2t
rm ppc2t.{0..127}
rm ppc.{0..127}

# Select the nearest child child commit
sort -t\; -k2 cc2ccc.tmp | join -t\; -1 2 -2 1 -a 1 -o 1.1 1.2 2.2 - ccc2t | sort -t\; -k1,1 -k3,3 | cut -d\; -f1,2 | sort -t\; -u -k1,1 -o cc2ccc
rm cc2ccc.tmp ccc2t
echo $(cat cc2ccc | wc -l) child commits has $(cut -d\; -f2 cc2ccc | sort -u | wc -l) child child commit
# 5,309,651 child commits has 5,253,033 child child commit

# Select the nearest parent parent commit
sort -t\; -k2 pc2ppc.tmp | join -t\; -1 2 -2 1 -a 1 -o 1.1 1.2 2.2 - ppc2t | sort -t\; -k1,1 -k3,3 | cut -d\; -f1,2 | sort -t\; -u -k1,1 -o pc2ppc
rm pc2ppc.tmp ppc2t
echo $(cat pc2ppc | wc -l) parent commits has $(cut -d\; -f2 pc2ppc | sort -u | wc -l) parent parent commit
# 6,753,277 parent commits has 6,308,168 parent parent commit

# Join commits, parent commits, parent parent commits, child commits, and child child commits
join -t\; -1 1 -2 1 -a1 -o 1.1 2.2 c c2pc | sort -t\; -k2 | join -t\; -1 2 -2 1 -a1 -o 1.1 1.2 2.2 - pc2ppc | sort -t\; -k1 | join -t\; -1 1 -2 1 -a1 -o 1.1 1.2 1.3 2.2 - c2cc | sort -t\; -k4 | join -t\; -1 4 -2 1 -a1 -o 1.1 1.2 1.3 1.4 2.2 - cc2ccc | sort -t\; -k1 >c.pc.ppc.cc.ccc

rm c c2pc pc2ppc c2cc cc2ccc

# Obtain all unique commit shas
cat c.pc.ppc.cc.ccc | tr -s ';' '\n' | sort -u >all_commits
echo $(cat all_commits | wc -l) commits in total
# 26,554,523 commits in total
