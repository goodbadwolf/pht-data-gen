#!/bin/bash
#SBATCH --account=cdux
#SBATCH --job-name=fftle_0
#SBATCH --output=logs/out_fftle_0_%a.out
#SBATCH --error=logs/err_fftle_0_%a.err
#SBATCH --partition=compute
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=500M
#SBATCH --array=0-6

module load gcc/12

spp_values=(        4 32 128 512 1024 1024 1024)
start_frame_values=(0  0   0   0    0   10   20)

spp=${spp_values[$SLURM_ARRAY_TASK_ID]}
start_frame=${start_frame_values[$SLURM_ARRAY_TASK_ID]}

./build_and_run.sh --mode pht --spp $spp --scene fftle_0 --start-frame $start_frame