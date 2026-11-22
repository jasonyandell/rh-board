# source me: toolchain and paths for run.py (read-only use of the shared elan)
export ELAN_HOME=$HOME/code/rh/work/elan PATH=$HOME/code/rh/work/elan/bin:$PATH
export TREE=$HOME/code/rh/rd-trees/frontier/lean OUT=$HOME/code/rh/rd-trees/frontier/out
export PINNED=$HOME/code/rh/lean/src
export LEAN=$ELAN_HOME/toolchains/leanprover--lean4---v4.36.0/bin/lean
export LEAN_PATH=$(cd $TREE && lake env printenv LEAN_PATH)
