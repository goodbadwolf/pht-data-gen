#!/usr/bin/env python3
import argparse
from dataclasses import dataclass, field
import datetime
from enum import StrEnum
from functools import total_ordering
import hashlib
import logging
import os
import re
from sqlite3 import Time
import subprocess
import sys
import time
from pathlib import Path
from string import Template
from typing import Optional, Tuple


# ---------------------------
# UTILITIES
# ---------------------------
def ensure_dir_exists(dir_path: str):
    os.makedirs(dir_path, exist_ok=True)


def create_md5_prefix(string: str, length=8) -> str:
    return hashlib.md5(string.encode()).hexdigest()[:length]


def init_logging(log_level: int, log_file: Optional[str] = None):
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(module)s: %(message)s"
    )
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    # Optional file handler
    if log_file:
        fh = logging.FileHandler(log_file, mode="w")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger


# Ensure common log directory exists
ensure_dir_exists("batched_logs")


# ---------------------------
# MODELS
# ---------------------------
class TimeUnit(StrEnum):
    SECONDS = "secs"
    MILLISECONDS = "millis"
    MINUTES = "mins"
    HOURS = "hrs"


@total_ordering
class TimeInterval:
    _units_in_seconds = {
        TimeUnit.MILLISECONDS: 1 / 1000,
        TimeUnit.SECONDS: 1,
        TimeUnit.MINUTES: 60,
        TimeUnit.HOURS: 3600,
    }

    def __init__(self, value, unit=TimeUnit.SECONDS):
        if unit not in self._units_in_seconds:
            raise ValueError(f"Unsupported unit: {unit}")
        self._seconds = float(value) * self._units_in_seconds[unit]

    def to(self, unit=TimeUnit.SECONDS):
        if unit not in self._units_in_seconds:
            raise ValueError(f"Unsupported unit: {unit}")
        return self._seconds / self._units_in_seconds[unit]

    def __eq__(self, other):
        if isinstance(other, TimeInterval):
            return self._seconds == other._seconds
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, TimeInterval):
            return self._seconds < other._seconds
        return NotImplemented

    def __add__(self, other):
        if isinstance(other, TimeInterval):
            return TimeInterval(self._seconds + other._seconds)
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, TimeInterval):
            return TimeInterval(self._seconds - other._seconds)
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return TimeInterval(self._seconds * other)
        return NotImplemented

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return TimeInterval(self._seconds / other)
        return NotImplemented

    def __repr__(self):
        return f"{self.to('secs'):.2f} secs"


@dataclass
class Frame:
    spp: int
    num: int
    render_time: TimeInterval

    @property
    def adjusted_render_time(self):
        return self.render_time * 1.05


@dataclass
class SppSet:
    spp: int
    start_frame: int
    end_frame: int  # exclusive
    render_time: TimeInterval = field(default_factory=lambda: TimeInterval(0))

    def hash_str(self) -> str:
        return f"{self.spp}-{self.start_frame}_{self.end_frame}"


@dataclass
class SppSetList:
    sppsets: list[SppSet] = field(default_factory=list)
    render_time: TimeInterval = field(default_factory=lambda: TimeInterval(0))

    def can_add_frame(self, frame: Frame) -> bool:
        new_render_time = self.render_time + frame.adjusted_render_time
        # Exceeds max time limit
        if new_render_time > DEFAULT_MAX_JOB_TIME:
            return False
        return True

    def add_frame(self, frame: Frame) -> bool:
        if not self.can_add_frame(frame):
            return False

        self.render_time += frame.adjusted_render_time
        if not self.sppsets or self.sppsets[-1].spp != frame.spp:
            self.sppsets.append(
                SppSet(
                    frame.spp,
                    frame.num,
                    frame.num + 1,
                    frame.adjusted_render_time,
                )
            )
        elif self.sppsets[-1].spp == frame.spp:
            self.sppsets[-1].end_frame = frame.num + 1
            self.sppsets[-1].render_time += frame.adjusted_render_time
        else:
            LOG.error(f"Invalid frame: {frame}")
            return False
        return True

    def is_empty(self) -> bool:
        return not self.sppsets


class Job:
    scene: str
    quality: str
    sppsets_array: list[SppSetList]

    def __init__(self, scene: str, quality: str):
        self.scene = scene
        self.quality = quality
        self.sppsets_array = [SppSetList()]

    def can_add_frame(self, frame: Frame) -> bool:
        if frame.adjusted_render_time > DEFAULT_MAX_JOB_TIME:
            return False

        sppsets_list = self.sppsets_array[-1]
        can_add_to_last = sppsets_list.can_add_frame(frame)
        if can_add_to_last and len(self.sppsets_array) < DEFAULT_JOB_ARRAY_SIZE:
            return True

        # Assume that each SppSetList, other than the last one,
        # has consumed DEFAULT_MAX_JOB_TIME
        render_time = DEFAULT_MAX_JOB_TIME * len(self.sppsets_array)
        render_time += frame.adjusted_render_time
        return render_time < DEFAULT_MAX_JOB_ARRAY_TIME

    def add_frame(self, frame: Frame) -> bool:
        if not self.can_add_frame(frame):
            return False

        sppsets_list = self.sppsets_array[-1]
        if sppsets_list.can_add_frame(frame):
            sppsets_list.add_frame(frame)
            return True
        sppsets_list = SppSetList()
        self.sppsets_array.append(sppsets_list)
        return sppsets_list.add_frame(frame)

    def is_empty(self) -> bool:
        if len(self.sppsets_array) == 1 and self.sppsets_array[0].is_empty():
            return True
        return False


# ---------------------------
# SLURM SCRIPT GENERATION
# ---------------------------
class SlurmTemplate(Template):
    delimiter = "%%"


class SlurmScriptGeneratorOptions:
    scene: str
    quality: str
    job_scripts_dir: str
    job_logs_dir: str
    sppsets_array: list[list[SppSet]]
    dry_run: bool


@dataclass
class SlurmScript:
    content: str
    job_name: str
    filename: str

    def save(self):
        try:
            with open(self.filename, "w") as f:
                f.write(self.content)
            os.chmod(self.filename, 0o755)
        except IOError as e:
            LOG.error(f"Error writing script file: {e}")
            sys.exit(1)


class SlurmScriptGenerator:
    job_id: int = 0

    def __init__(self, template_file: str):
        self.template_file = template_file
        self.template: Optional[SlurmTemplate] = None
        self.load_template()

    def load_template(self):
        try:
            with open(self.template_file, "r") as f:
                self.template = SlurmTemplate(f.read())
        except FileNotFoundError:
            LOG.error(f"Template file '{self.template_file}' not found.")
            sys.exit(1)

    def generate_script(self, opts: SlurmScriptGeneratorOptions) -> SlurmScript:
        if not self.template:
            LOG.error("Template not loaded.")
            sys.exit(1)
        script_vars = vars(opts).copy()
        script_vars.update(self._generate_bash_arrays(opts.sppsets_array))
        script_vars["job_array_str"] = f"0-{len(opts.sppsets_array) - 1}"
        job_name = f"{opts.scene}_{SlurmScriptGenerator.job_id}"
        SlurmScriptGenerator.job_id += 1
        script_vars["job_name"] = job_name

        first_sppset = opts.sppsets_array[0][0]
        log_filename_fragment = (
            f"{first_sppset.spp}-{first_sppset.start_frame}_{first_sppset.end_frame}"
        )
        log_out_filename = f"{job_name}_{log_filename_fragment}_%a.out"
        script_vars["job_logs_out_path"] = os.path.join(
            opts.job_logs_dir, log_out_filename
        )
        log_err_filename = f"{job_name}_{log_filename_fragment}_%a.err"
        script_vars["job_logs_err_path"] = os.path.join(
            opts.job_logs_dir, log_err_filename
        )
        script_filename = os.path.join(opts.job_scripts_dir, f"{job_name}.sh")
        try:
            return SlurmScript(
                self.template.substitute(script_vars), job_name, script_filename
            )
        except KeyError as e:
            LOG.error(f"Missing required variable in template: {e}")
            sys.exit(1)

    def _generate_bash_arrays(self, sppsets_array: list[SppSetList]) -> dict[str, str]:
        sppsets_bash_array = []
        for i, sppsets in enumerate(sppsets_array):
            sppsets_bash_array.append(
                " ".join(
                    [f"{spp.spp}={spp.start_frame},{spp.end_frame}" for spp in sppsets]
                )
            )
            LOG.debug(f"SPPSets: {i} => {sppsets_bash_array[-1]}")
        return {
            "sppsets_array": f"({' '.join(f'"{sppsets}"' for sppsets in sppsets_bash_array)})",
        }

    def submit_script(self, script: SlurmScript) -> Tuple[int, str, str]:
        try:
            result = subprocess.run(
                ["sbatch", script.filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                check=True,
            )
            return (result.returncode, result.stdout, result.stderr)
        except subprocess.CalledProcessError as e:
            LOG.error(f"Error executing sbatch: {e}")
            return (e.returncode, e.stdout, e.stderr)


# ---------------------------
# JOB SCHEDULER
# ---------------------------
DEFAULT_SPPS = [8, 16, 32, 64, 128, 256, 512, 1024]
DEFAULT_FRAMES_COUNT = 32
DEFAULT_POLL_TIME = TimeInterval(1, "mins")
DEFAULT_JOB_ARRAY_SIZE = 10
DEFAULT_MAX_JOB_TIME = TimeInterval(2, "hrs")
DEFAULT_MAX_JOB_ARRAY_TIME = DEFAULT_MAX_JOB_TIME * DEFAULT_JOB_ARRAY_SIZE


class JobScheduler:
    def __init__(
        self,
        scene: str,
        quality: str,
        template_file: str,
        job_scripts_dir: str,
        job_logs_dir: str,
        dry_run: bool,
    ):
        self.scene = scene
        self.quality = quality
        self.template_file = template_file
        self.job_scripts_dir = job_scripts_dir
        self.job_logs_dir = job_logs_dir
        self.dry_run = dry_run

        ensure_dir_exists(self.job_scripts_dir)
        ensure_dir_exists(self.job_logs_dir)

    def sleep(self, duration: TimeInterval):
        if self.dry_run:
            now = datetime.datetime.now()
            end_time = now + datetime.timedelta(seconds=duration.to("secs"))
            LOG.info(
                f"[DRY RUN] Would wait from {now} to {end_time} ({duration.to('mins'):.2f} mins)"
            )
            time.sleep(2)
        else:
            start_time = datetime.datetime.now()
            remaining = duration
            LOG.info(f"Sleeping for {duration.to('mins'):.2f} mins")
            while remaining > TimeInterval(0):
                sleep_time = min(DEFAULT_POLL_TIME, remaining)
                time.sleep(sleep_time.to("secs"))
                remaining -= sleep_time
                elapsed = datetime.datetime.now() - start_time
                LOG.info(f"Elapsed: {elapsed}")

    def get_4spp_log_path(self) -> Optional[Path]:
        pattern = f"{self.scene}*4-0_{DEFAULT_FRAMES_COUNT}*.out"
        log_dir = Path(self.job_logs_dir)
        matches = list(log_dir.glob(pattern))
        return matches[0] if matches else None

    def calculate_avg_time(
        self, force_recalc: bool = False
    ) -> Tuple[TimeInterval, int]:
        def _calculate_avg_time(self) -> Tuple[TimeInterval, int]:
            if self.dry_run:
                mock_avg_time = TimeInterval(20, "secs")
                LOG.info(
                    f"[DRY RUN] Using mock avg time: {mock_avg_time.to('secs'):.2f} secs per frame"
                )
                return mock_avg_time, DEFAULT_FRAMES_COUNT
            log_path = self.get_4spp_log_path()
            if not log_path or not log_path.is_file():
                return TimeInterval(0), 0
            total = TimeInterval(0, TimeUnit.MILLISECONDS)
            count = 0
            pattern = re.compile(r"Frame\s*>\s*Elapsed\s*time:\s*(\d+)\s*ms")
            with open(log_path, "r") as f:
                for line in f:
                    if match := pattern.search(line):
                        total += TimeInterval(int(match.group(1)), "millis")
                        count += 1
                        LOG.debug(f"Frame timing: {match.group(1)} ms")
            if count:
                avg = total / count
                LOG.info(
                    f"Calculated avg frame time: {avg.to('secs'):.2f} secs from {count} frames"
                )
                return avg, count
            return TimeInterval(0), 0

        avg_time, count = _calculate_avg_time(self)
        if (
            avg_time.to(TimeUnit.SECONDS) > 0 and count == DEFAULT_FRAMES_COUNT
        ) or not force_recalc:
            return avg_time, count

        def wait_for_4spp_completion() -> bool:
            LOG.info("Waiting for 4spp render to complete...")
            max_attempts = 3
            attempts = 0
            while attempts < max_attempts:
                avg_time, count = self.calculate_avg_time()
                if avg_time.to() > 0 and count == DEFAULT_FRAMES_COUNT:
                    LOG.info("4spp render completed successfully")
                    return True

                attempts += 1
                LOG.info(f"Attempt {attempts}/{max_attempts}, waiting...")
                GUESS_AVG_TIME = TimeInterval(20, "secs")
                self.sleep(GUESS_AVG_TIME * DEFAULT_FRAMES_COUNT * attempts)
            LOG.error("Timeout waiting for 4spp render to complete")
            return False

        if avg_time.to("secs") == 0 or count != DEFAULT_FRAMES_COUNT:
            LOG.info("No average time available. Submitting job for 4spp first.")
            four_spp_job = Job(
                scene=self.scene,
                quality=self.quality,
            )
            for frame_num in range(DEFAULT_FRAMES_COUNT):
                if not four_spp_job.add_frame(Frame(4, frame_num, TimeInterval(0))):
                    LOG.error("Failed to add frame to 4spp job. Fatal error.")
                    return TimeInterval(0), 0

            self.submit_job(four_spp_job)
            LOG.info("Waiting for 4spp job to complete")
            if not wait_for_4spp_completion():
                LOG.error("Failed to complete 4spp render. Exiting.")
                return TimeInterval(0), 0
            LOG.info("Recalculating average render time after 4spp completion")
            avg_time_4spp, frame_count = _calculate_avg_time()
            if avg_time_4spp.to() == 0 or frame_count == 0:
                LOG.error("Failed to calculate average time after 4spp completion")
                return TimeInterval(0), 0
            return avg_time_4spp, frame_count

    def run(self):
        LOG.info(
            f"Starting render scheduler for scene: {self.scene}, quality: {self.quality}"
        )
        avg_time, count = self.calculate_avg_time(force_recalc=True)
        if avg_time.to("secs") == 0 or count != DEFAULT_FRAMES_COUNT:
            LOG.error("No average frame time available. Exiting...")
            return

        all_frames = [
            Frame(spp, i, avg_time * (spp / 4))
            for spp in DEFAULT_SPPS
            for i in range(DEFAULT_FRAMES_COUNT)
        ]
        all_frames.sort(key=lambda f: (f.spp, f.render_time))
        current_job = None
        for frame in all_frames:
            if not current_job:
                current_job = Job(scene=self.scene, quality=self.quality)
            if current_job.can_add_frame(frame):
                current_job.add_frame(frame)
            else:
                self.submit_job(current_job)
                current_job = None
                LOG.info(
                    f"Waiting {DEFAULT_MAX_JOB_TIME.to('mins')} mins before submitting next job"
                )
                self.sleep(DEFAULT_MAX_JOB_TIME)

    def submit_job(self, job: Job):
        if job.is_empty():
            LOG.info("Skipping empty job.")
            return

        args = SlurmScriptGeneratorOptions()
        args.scene = self.scene
        args.quality = self.quality
        args.job_scripts_dir = self.job_scripts_dir
        args.job_logs_dir = self.job_logs_dir
        args.sppsets_array = [
            sppsets_list.sppsets for sppsets_list in job.sppsets_array
        ]
        args.dry_run = self.dry_run

        generator = SlurmScriptGenerator(self.template_file)
        script = generator.generate_script(args)
        LOG.info(
            f"{'[DRY RUN] ' if self.dry_run else ''}"
            + f"Generated SLURM script at {script.filename}"
        )
        script.save()
        if self.dry_run:
            LOG.info("[DRY RUN] Job not submitted.")
            return
        ret, out, err = generator.submit_script(script)
        if ret == 0:
            LOG.info(f"Job {script.job_name} submitted successfully: {out.strip()}")
        else:
            LOG.error(f"Job {script.job_name} submission failed: {err}")
            sys.exit(1)


# ---------------------------
# MAIN ENTRY POINT
# ---------------------------
LOG: Optional[logging.Logger] = None


def main():
    parser = argparse.ArgumentParser(
        description="slurm_util.py: generates scripts and submits them to SLURM."
    )
    parser.add_argument("--scene", required=True, help="Scene name")
    parser.add_argument("--quality", default="720p", help="Render quality")
    parser.add_argument(
        "--template",
        default="talapas/slurm_job.sh.template",
        help="Path to SLURM script template file",
    )
    parser.add_argument(
        "--job-scripts-dir",
        default="talapas_jobs",
        help="Output directory for generated job scripts",
    )
    parser.add_argument(
        "--job-logs-dir", default="talapas_logs", help="Directory for job logs"
    )
    parser.add_argument(
        "--spps",
        nargs="+",
        type=int,
        default=DEFAULT_SPPS,
        help="List of samples per pixel",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate scripts but do not submit them to SLURM",
    )
    args = parser.parse_args()

    global LOG
    log_path = os.path.join("batched_logs", f"{args.scene}_{args.quality}_progress.log")
    LOG = init_logging(logging.INFO if not args.dry_run else logging.DEBUG, log_path)

    scheduler = JobScheduler(
        scene=args.scene,
        quality=args.quality,
        template_file=args.template,
        job_scripts_dir=args.job_scripts_dir,
        job_logs_dir=args.job_logs_dir,
        dry_run=args.dry_run,
    )
    scheduler.run()


if __name__ == "__main__":
    main()
