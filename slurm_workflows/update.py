#!/usr/bin/python
# -- coding: utf-8 --
"""author: Martin Schilling (martin.schilling@med.uni-goettingen.de), 2025

Logic of `slurm_wf.update_metadata`: update the archived metadata of Slurm jobs.
Refresh the efficiency report of a running or pending job, add the data of the slurm output files,
and summarize the efficiency of the archived jobs.
"""
import glob
import os
import statistics
from datetime import date
from typing import List, Optional

from slurm_workflows.metadata import METADATA_FILE, SBATCH_FILE
from slurm_workflows.metadata import as_list, parse_job_dir, read_metadata, write_metadata
from slurm_workflows.slurm import matches_jobid, reportseff_from_jobid, sbatch_parameters_to_dict
from slurm_workflows.slurm import slurm_output_files, slurm_output_to_dict

# The efficiency report of a job is available for around one week after the submission.
REPORTSEFF_MAX_DAYS = 8

UNFINISHED_STATES = ("RUNNING", "PENDING")


def update_sbatch_data(subfolders: List[str]):
    """Copy the #SBATCH parameters into the metadata.

    Args:
        subfolders: Archive folders.
    """
    update_dir = []

    for folder in subfolders:
        metadata = os.path.join(folder, METADATA_FILE)
        if os.path.isfile(metadata):
            metadict = read_metadata(metadata)

            sbatch_file = os.path.join(folder, SBATCH_FILE)
            sbatch_dict = {}
            sbatch_parameters_to_dict(sbatch_file, sbatch_dict)

            for key, value in sbatch_dict.items():
                if key not in metadict:

                    update_dir.append(folder)
                    metadict[key] = value
                elif value != metadict[key]:
                    update_dir.append(folder)
                    metadict[key] = value

            if folder in update_dir:
                write_metadata(metadict, metadata)

    update_dir = list(set(update_dir))
    update_dir.sort()

    for folder in update_dir:
        print(f"Updated sbatch parameters of folder {folder}.")

    if len(update_dir) == 0:
        print("All directories contain updated sbatch information.")


def update_reporteff(subfolders: List[str]):
    """Refresh the efficiency report of a recent job that is pending, running, or has no report.

    Args:
        subfolders: Archive folders.
    """
    update_dir = []

    for folder in subfolders:
        metadata = os.path.join(folder, METADATA_FILE)
        if os.path.isfile(metadata):
            metadict = read_metadata(metadata)

            # check for dates in the last 8 days
            date_str = [int(i) for i in metadict["date"].split("-")]
            job_date = date(date_str[0], date_str[1], date_str[2])
            days_past = date.today() - job_date
            if days_past.days > REPORTSEFF_MAX_DAYS:
                continue

            reports = as_list(metadict.get("Reportseff", []))
            for report in reports:
                if report["State"] in UNFINISHED_STATES:
                    update_dir.append(folder)
                    break

            if len(reports) == 0:
                update_dir.append(folder)

    for folder in update_dir:
        print(f"Updating efficiency report of folder {folder}.")
        metadata = os.path.join(folder, METADATA_FILE)

        metadict = read_metadata(metadata)
        reportseff_from_jobid(parse_job_dir(folder)[1], metadict)

        write_metadata(metadict, metadata)

    if len(update_dir) == 0:
        print("All directories contain updated efficiency reports.")


def check_metadata(subfolders: List[str]):
    """Correct the date and the task from the task folder name, and the efficiency report from the JobID.

    A report of another JobID is deleted.

    Args:
        subfolders: Archive folders.
    """
    update_metadata = []
    for folder in subfolders:
        contents = os.path.basename(parse_job_dir(folder)[0]).split("_")
        folder_date = contents[0]
        task = "_".join(contents[1:])

        metadata = os.path.join(folder, METADATA_FILE)

        if os.path.isfile(metadata):
            metadict = read_metadata(metadata)

            if metadict["date"] != folder_date:
                update_metadata.append(folder)
                metadict["date"] = folder_date

            if metadict["task"] != task:
                metadict["task"] = task
                update_metadata.append(folder)

            reports = as_list(metadict.get("Reportseff", []))
            if any(not matches_jobid(r["JobID"], metadict["jobid"]) for r in reports):
                metadict["Reportseff"] = []
                reportseff_from_jobid(metadict["jobid"], metadict)
                update_metadata.append(folder)

            write_metadata(metadict, metadata)

    update_metadata = list(set(update_metadata))
    update_metadata.sort()

    for folder in update_metadata:
        print(f"Updated essential metadata for {folder}.")


def update_slurm_output(subfolders: List[str], slurm_dir: str):
    """Add the data of the slurm output files of each job to its metadata.

    Each file `slurm-<jobid>.out` or `slurm-<jobid>_<array_index>.out` gives one entry of the list
    'SlurmOutput'.

    Args:
        subfolders: Archive folders.
        slurm_dir: Directory of the slurm output files.
    """
    update_dir = []

    for folder in subfolders:
        metadata = os.path.join(folder, METADATA_FILE)
        if not os.path.isfile(metadata):
            continue

        metadict = read_metadata(metadata)

        jobid = metadict.get("jobid")
        if not jobid:
            continue

        slurm_files = slurm_output_files(slurm_dir, jobid)

        if not slurm_files:
            continue

        new_slurm_output = [slurm_output_to_dict(sf) for sf in slurm_files]
        if new_slurm_output == metadict.get("SlurmOutput"):
            continue

        metadict["SlurmOutput"] = new_slurm_output
        update_dir.append(folder)

        write_metadata(metadict, metadata)

    update_dir = list(set(update_dir))
    update_dir.sort()

    for folder in update_dir:
        print(f"Updated slurm output information of folder {folder}.")

    if len(update_dir) == 0:
        print("No matching slurm output files found.")


def parse_percent(value: str) -> Optional[float]:
    """Convert a percentage of the efficiency report into a number.

    Args:
        value: Value of the efficiency report, for example '85.3%'.

    Returns:
        float: The value without the percent sign, or None if the report has no value.
    """
    if value and value not in ('---', 'N/A', ''):
        try:
            return float(value.rstrip('%'))
        except ValueError:
            return None
    return None


def average_efficiency(subfolders: List[str], slurm_dir: Optional[str] = None):
    """Print the average efficiency and the core hours of the jobs.

    The efficiency comes from the 'Reportseff' entry of each job that is not RUNNING or PENDING.
    The core hours come from the 'SlurmOutput' entry, or else from the files in `slurm_dir`.

    Args:
        subfolders: Archive folders.
        slurm_dir: Directory of the slurm output files, or None.
    """
    cpu_effs = []
    mem_effs = []
    time_effs = []
    core_hours_list = []

    for folder in subfolders:
        metadata = os.path.join(folder, METADATA_FILE)
        if not os.path.isfile(metadata):
            continue

        metadict = read_metadata(metadata)

        for report in as_list(metadict.get("Reportseff", [])):
            if report.get("State") in UNFINISHED_STATES:
                continue
            cpu = parse_percent(report.get("CPUEff"))
            mem = parse_percent(report.get("MemEff"))
            time_eff = parse_percent(report.get("TimeEff"))
            if cpu is not None:
                cpu_effs.append(cpu)
            if mem is not None:
                mem_effs.append(mem)
            if time_eff is not None:
                time_effs.append(time_eff)

        slurm_outputs = as_list(metadict.get("SlurmOutput", []))

        if slurm_outputs:
            job_core_hours = [so["core_hours"] for so in slurm_outputs if so.get("core_hours") is not None]
            if job_core_hours:
                core_hours_list.append(sum(job_core_hours))
        elif slurm_dir:
            jobid = metadict.get("jobid")
            if jobid:
                job_core_hours = [core_hours for core_hours in
                                  (slurm_output_to_dict(sf).get("core_hours")
                                   for sf in slurm_output_files(slurm_dir, jobid))
                                  if core_hours is not None]
                if job_core_hours:
                    core_hours_list.append(sum(job_core_hours))

    print(f"Efficiency summary for {len(subfolders)} job(s):")

    if cpu_effs:
        print(f"  Average CPU Efficiency:    {statistics.mean(cpu_effs):.1f}% (n={len(cpu_effs)})")
    else:
        print("  Average CPU Efficiency:    N/A")

    if mem_effs:
        print(f"  Average Memory Efficiency: {statistics.mean(mem_effs):.1f}% (n={len(mem_effs)})")
    else:
        print("  Average Memory Efficiency: N/A")

    if time_effs:
        print(f"  Average Time Efficiency:   {statistics.mean(time_effs):.1f}% (n={len(time_effs)})")
    else:
        print("  Average Time Efficiency:   N/A")

    if core_hours_list:
        print(f"  Average Core Hours: {statistics.mean(core_hours_list):.2f} (n={len(core_hours_list)})")
        print(f"  Median Core Hours: {statistics.median(core_hours_list):.2f} (n={len(core_hours_list)})")
        print(f"  Total Core Hours:   {sum(core_hours_list):.2f}")
    else:
        print("  Core Hours:                N/A")


def update_archive(
        input_dir: str,
        pattern: Optional[str] = None,
        check_general_info: bool = False,
        check_sbatch_info: bool = False,
        slurm_dir: Optional[str] = None,
        average: bool = False,
):
    """Update the metadata of the archive folders in a directory.

    The efficiency report is always refreshed.

    Args:
        input_dir: Directory of the task folders `<date>_<suffix>`, which hold one `<jobid>` folder per job.
        pattern: Part of the name of the task folders to update, or None for all.
        check_general_info: Run `check_metadata()`.
        check_sbatch_info: Run `update_sbatch_data()`.
        slurm_dir: Directory of the slurm output files, or None.
        average: Print the efficiency summary.
    """
    task_dirs = glob.glob(os.path.join(input_dir, "*" if pattern is None else f"*{pattern}*"))
    subfolders = sorted(f.path for task_dir in task_dirs if os.path.isdir(task_dir)
                        for f in os.scandir(task_dir) if f.is_dir() and f.name.isdigit())
    if pattern is not None and len(subfolders) == 0:
        raise ValueError(f"No subfolders match pattern {pattern}.")

    if check_sbatch_info:
        update_sbatch_data(subfolders)

    if check_general_info:
        check_metadata(subfolders)

    if slurm_dir is not None:
        update_slurm_output(subfolders, slurm_dir)

    update_reporteff(subfolders)

    if average:
        average_efficiency(subfolders, slurm_dir)
