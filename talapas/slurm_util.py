#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import logging
from dataclasses import dataclass
from string import Template
from typing import Dict, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@dataclass
class SppSet:
    spp: int
    start_frame: int
    end_frame: int

    @classmethod
    def from_str(cls, param_str: str) -> "SppSet":
        try:
            spp, frame_range = param_str.split("=")
            start_frame, end_frame = map(int, frame_range.split(","))
            return cls(int(spp), start_frame, end_frame)
        except ValueError:
            raise ValueError(
                f"Invalid parameter format. \nExpected format: spp=start,end \nGot: {param_str}"
            )

    def to_hash_str(self) -> str:
        return f"{self.spp}_{self.start_frame}_{self.end_frame}"


class SppParser:
    def __init__(self, param_str: str):
        self.spp_sets_str = param_str

    def parse(self) -> List[SppSet]:
        """Parse parameter sets in the format 'spp=start,end [spp2=start2,end2 ...]'"""
        try:
            return [SppSet.from_str(param) for param in self.spp_sets_str.split()]
        except ValueError as e:
            logging.error(f"Error parsing spp sets: {e}")
            raise


class SlurmTemplate(Template):
    delimiter = "%%"


class SlurmScriptGenerator:
    def __init__(self, template_file):
        self.template_file = template_file
        self.template = None

    def load(self):
        self.load_template()

    def load_template(self):
        try:
            with open(self.template_file, "r") as f:
                self.template = SlurmTemplate(f.read())
        except FileNotFoundError:
            logging.error(f"Error: Template file '{self.template_file}' not found.")
            return

    def generate_script(self, args):
        if not self.template:
            logging.error("Error: Template not loaded.")
            sys.exit(1)

        script_vars = vars(args).copy()
        script_vars.update(self._generate_bash_arrays(args.spp_sets))

        try:
            return self.template.substitute(script_vars)
        except KeyError as e:
            logging.error(f"Error: Missing required variable in template: {e}")
            sys.exit(1)

    def save_script(self, content, output_file):
        try:
            with open(output_file, "w") as f:
                f.write(content)
            # Make the script executable
            os.chmod(output_file, 0o755)
        except IOError as e:
            logging.error(f"Error writing script file: {e}")
            sys.exit(1)

    def submit_script(self, script_path) -> Tuple[int, str, str]:
        try:
            result = subprocess.run(
                ["sbatch", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                check=True,
            )
            return (result.returncode, result.stdout, result.stderr)

        except subprocess.CalledProcessError as e:
            logging.error(f"Error executing sbatch: {e}")
            return (e.returncode, e.stdout, e.stderr)

    def _generate_bash_arrays(self, spp_sets: List[SppSet]) -> Dict[str, str]:
        """Generate bash arrays for spp and frame values"""

        spp_strs = [str(spp_set.spp) for spp_set in spp_sets]
        start_strs = [str(spp_set.start_frame) for spp_set in spp_sets]
        end_strs = [str(spp_set.end_frame) for spp_set in spp_sets]

        max_spp_width = max(len(s) for s in spp_strs)
        max_start_width = max(len(s) for s in start_strs)
        max_end_width = max(len(s) for s in end_strs)

        # Find the maximum width needed for consistent alignment
        max_value_width = max(max_spp_width, max_start_width, max_end_width)

        # Pad all values to the maximum width
        spp_values = [s.rjust(max_value_width) for s in spp_strs]
        start_frame_values = [s.rjust(max_value_width) for s in start_strs]
        end_frame_values = [s.rjust(max_value_width) for s in end_strs]

        # Calculate the maximum variable name length for alignment
        var_names = ["spp_values", "start_frame_values", "end_frame_values"]
        max_name_length = max(len(name) for name in var_names) + 1

        # Generate the formatted strings with consistent padding
        # The first value of each array is padded with spaces to align with first value of all other arrays
        return {
            "spp_values": f"({' ' * (max_name_length - len('spp_values'))}{' '.join(spp_values)})",
            "start_frame_values": f"({' ' * (max_name_length - len('start_frame_values'))}{' '.join(start_frame_values)})",
            "end_frame_values": f"({' ' * (max_name_length - len('end_frame_values'))}{' '.join(end_frame_values)})",
            "job_array": f"0-{len(spp_sets) - 1}",
        }


def create_md5_prefix(str: str, length=8) -> str:
    return hashlib.md5(str.encode()).hexdigest()[:length]


def ensure_dir_exists(dir_path: str):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate and submit SLURM scripts from template"
    )

    parser.add_argument(
        "--template",
        help="Path to the SLURM script template file",
        default="slurm_job.sh.template",
    )
    parser.add_argument(
        "--output-dir",
        help="Output path for the generated SLURM script",
        default="talapas_jobs",
    )
    parser.add_argument(
        "--job-logs-dir",
        help="Path to the log directory when running the jobs",
        default="talapas_logs",
    )
    parser.add_argument("--scene", help="Scene name", required=True)
    parser.add_argument(
        "--spp-sets",
        help='Parameter sets in format "spp=start,end [spp2=start2,end2 ...]"',
        required=True,
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit generated script to SLURM",
    )

    args = parser.parse_args()
    args.spp_sets = SppParser(args.spp_sets).parse()
    if len(args.spp_sets) >= 10:
        logging.error(
            "Error: Maximum of 10 spp sets allowed. Please reduce the number of sets."
        )
        return

    hash_id = create_md5_prefix(
        "_".join([spp_set.to_hash_str() for spp_set in args.spp_sets])
    )
    args.job_name = f"{args.scene}.{hash_id}"
    ensure_dir_exists(args.output_dir)
    ensure_dir_exists(args.job_logs_dir)

    generator = SlurmScriptGenerator(args.template)
    generator.load()
    script_content = generator.generate_script(args)
    script_filename = f"{args.output_dir}/{args.job_name}.sh"
    generator.save_script(script_content, script_filename)

    logging.info(f"Generated SLURM script: {script_filename}")

    if not args.submit:
        logging.info("Script was not submitted. Use --submit to submit the job.")
        return

    return_code, std_out, std_err = generator.submit_script(script_filename)
    if return_code == 0:
        logging.info(f"Successfully submitted job: {std_out}")
    else:
        logging.error(f"Error submitting job: {std_err}")
        sys.exit(1)

    return


if __name__ == "__main__":
    main()
