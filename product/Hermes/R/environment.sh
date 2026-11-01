#!/bin/bash
bnn_r_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$bnn_r_root/environment.sh"
export HERMES_BN_R_HOME="$bnn_r_root/R"
export R_HOME="/Library/Frameworks/R.framework/Resources"
export HERMES_BN_R_EXECUTABLE="$R_HOME/bin/Rscript"
export R_LIBS_USER="$bnn_r_root/Services/software/R/framework-library:$bnn_r_root/R/serena-library"
export R_PROFILE_USER=/dev/null R_ENVIRON_USER=/dev/null R_MAKEVARS_USER=/dev/null
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
