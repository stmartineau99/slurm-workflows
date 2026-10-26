#!/usr/bin/python
# -- coding: utf-8 --
"""author: Martin Schilling (martin.schilling@med.uni-goettingen.de), 2025

Access to the files of an archive folder, and creation of its `metadata.json`.
"""
import json
import os

from slurm_workflows.repositories import repository_status_to_dict
from slurm_workflows.settings import USER_SETTINGS, load_settings
from slurm_workflows.slurm import reportseff_from_jobid, sbatch_parameters_to_dict

METADATA_FILE = "metadata.json"
SBATCH_FILE = "sbatch.sbatch"
LOG_FILE = "log.txt"


def read_metadata(
    metadata_file: str,
) -> dict:
    """Read a metadata file of an archive folder.

    Args:
        metadata_file: Path of the metadata file.

    Returns:
        dict: Content of the metadata file.
    """
    with open(metadata_file, "r") as myfile:
        return json.loads(myfile.read())


def write_metadata(
    metadict: dict,
    metadata_file: str,
) -> None:
    """Write a metadata file of an archive folder.

    The key order and the tab indentation of the archived files are kept.

    Args:
        metadict: Metadata of the job.
        metadata_file: Path of the metadata file.
    """
    with open(metadata_file, "w") as myfile:
        json.dump(metadict, myfile, sort_keys=False, indent="\t", separators=(",", ": "))


def as_list(
    value,
) -> list:
    """Return a metadata entry which can hold a single entry or a list of entries as a list.

    Args:
        value: Value of a metadata entry.

    Returns:
        list: The value itself if it is a list, otherwise a list with the value as its only entry.
    """
    return value if isinstance(value, list) else [value]


def parse_job_dir(
    input_dir: str,
) -> tuple:
    """Split an archive folder `<date>_<suffix>/<jobid>` into its task folder and its JobID.

    Args:
        input_dir: Archive folder of one job.

    Returns:
        tuple: The task folder `<date>_<suffix>` and the JobID.
    """
    input_dir = os.path.abspath(input_dir)
    jobid = os.path.basename(input_dir)
    if not jobid.isdigit():
        raise ValueError(f"Check correct format of input directory {input_dir}: 'yyyy-mm-dd_suffix/<jobid>'.")
    return os.path.dirname(input_dir), jobid


def init_metadict(
    input_dir: str,
) -> dict:
    """Create the metadata of a job from the name of its archive folder.

    Args:
        input_dir: Archive folder `<date>_<suffix>/<jobid>` with the date as YYYY-MM-DD.

    Returns:
        dict: The keys 'date' and 'task'. 'task' holds the suffix.
    """
    folder_name = os.path.basename(parse_job_dir(input_dir)[0])
    contents = folder_name.split("_")

    if len(contents) < 2:
        raise ValueError(f"Check correct format of input directory {folder_name}: 'yyyy-mm-dd_suffix'.")

    return {"date": contents[0], "task": "_".join(contents[1:])}


def user_to_metadict(
    metadict: dict,
    settings_file: str = None,
) -> None:
    """Add the identifiers of the person who ran the job to the metadata.

    A job which finished must still be archived, so an unusable settings file is reported and
    skipped instead of failing the archiving step.

    Args:
        metadict: Metadata of the job.
        settings_file: Settings file of the project, or None.
    """
    if settings_file is None:
        print("Warning: the HPC user is not recorded. No settings file is given.")
        return

    try:
        settings = load_settings(settings_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Warning: the HPC user is not recorded. {exc}")
        return

    for key in USER_SETTINGS:
        if settings[key]:
            metadict[key] = settings[key]


def write_job_metadata(
    input_dir: str,
    output_file: str = None,
    repository_file: str = None,
    overwrite: bool = False,
    settings_file: str = None,
):
    """Create or update the `metadata.json` of an archive folder.

    Args:
        input_dir: Archive folder `<date>_<suffix>/<jobid>` of one job.
        output_file: Metadata file. Default: `<input_dir>/metadata.json`.
        repository_file: Git repositories to record, or None.
        overwrite: Replace an existing `metadata.json`.
        settings_file: Settings file of the project, which names the HPC user.
    """
    if output_file is None:
        output_file = os.path.join(input_dir, METADATA_FILE)
    else:
        output_file = os.path.abspath(output_file)

    jobid = parse_job_dir(input_dir)[1]
    sbatch_file = os.path.join(input_dir, SBATCH_FILE)

    if os.path.isfile(output_file) and not overwrite:
        metadict = read_metadata(output_file)
    else:
        metadict = init_metadict(input_dir)

    user_to_metadict(metadict, settings_file)
    sbatch_parameters_to_dict(sbatch_file, metadict=metadict)
    reportseff_from_jobid(jobid, metadict)
    # A resubmission can run on a newer commit, so the hash is refreshed for an existing file too.
    if repository_file is not None:
        repository_status_to_dict(repository_file, metadict=metadict)

    write_metadata(metadict, output_file)
