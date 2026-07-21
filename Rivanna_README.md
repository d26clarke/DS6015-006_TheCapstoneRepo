
# DS6050_G12_PROJECT

Repository for uvaMSDS 6015-006 Tree Canopy Capstone Project

Enter some project details here

## Running on UVA Rivanna

## Usage/Examples

Run single slurm to generate tiff files and centroids
```bash
  sbatch slurm/run_single.slurm 
```


Git Recovery

Good news — nothing is actually gone yet. git reset --hard doesn't delete commits immediately; it just moves your branch pointer. The commits themselves stay in Git's internal storage until garbage collection eventually cleans them up (which doesn't happen automatically for at least 30 days by default). You can get them back via the reflog — Git's record of every place HEAD has pointed.
Step 1 — Find the commit you reset away from


git reflog

a1b2c3d HEAD@{0}: reset: moving to HEAD~2
e4f5g6h HEAD@{1}: commit: <your 2nd commit message>
i7j8k9l HEAD@{2}: commit: <your 1st commit message>

Step 2 — Look at it first, don't jump straight back to it

git show HEAD@{1} --stat

Step 3 — Recover just what you need

git checkout HEAD@{1} -- path/to/file/you/actually/want

Option B — recover everything onto a side branch, then cherry-pick, if you want to poke around more safely before deciding:

git branch recovery-branch HEAD@{1}
git checkout recovery-branch
# inspect, diff, decide what you actually want

Your main branch is untouched by this — it just gives you the full old state on a separate branch to compare against.

# 1. Go up to the repo root (3 levels up from where you are now)
cd ../../..

# 2. Save files_to_recover_reporoot.txt into the repo root, then run:
zip -r recovered_files.zip -@ < files_to_recover_reporoot.txt
