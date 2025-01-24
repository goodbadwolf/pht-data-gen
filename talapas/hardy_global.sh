#!/bin/bash
#SBATCH --account=cdux
#SBATCH --job-name=hardy_global
#SBATCH --output=logs/out_hardy_global_%a.out
#SBATCH --error=logs/err_hardy_global_%a.err
#SBATCH --partition=compute
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=500M
#SBATCH --array=0-5

module load gcc/12

spp_values=(        4 8 16 32 64 128)
start_frame_values=(0 0  0  0  0   0)

# spp_values=(        2048 4096 4096)
# start_frame_values=(10   4    8)


spp=${spp_values[$SLURM_ARRAY_TASK_ID]}
start_frame=${start_frame_values[$SLURM_ARRAY_TASK_ID]}

./build_and_run.sh --mode pht --spp $spp --scene hardy_global --start-frame $start_frame