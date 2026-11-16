#!/bin/bash
#SBATCH --job-name=mcoc-g8-final
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%A_%a.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Ejecuta sbatch desde la raíz del proyecto}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
exec "${PYTHON:-python}" -m scripts.final_campaign run "${1:?Falta el directorio del lote}" --index "${SLURM_ARRAY_TASK_ID:?Falta --array}"
