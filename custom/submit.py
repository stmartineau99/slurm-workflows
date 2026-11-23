#!/usr/bin/env python
import json
import shlex
import shutil
import datetime
import tempfile
import tomllib
import argparse
from pathlib import Path

from slurm_workflows.deploy import submit_chain
from slurm_workflows.repositories import check_dirty, job_repositories

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
MAIL_TYPE = "BEGIN,END,FAIL"

OPTIONAL_SBATCH = {
    "partition": "-p {}",
    "gpu": "-G {}",
    "constraint": "-C {}",
    "qos": "--qos={}",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Submit the jobs from the [jobs] table of a run config. Unknown arguments go to the job script."
    )
    parser.add_argument("config", type=str, help="Path to TOML config file.")
    parser.add_argument("-s", "--settings", type=str, required=True, help="Settings file of the project.")
    parser.add_argument("--job", type=str, default=None, help="Submit only this job. By default, submit all jobs.")
    parser.add_argument("--slurm_profile", type=str, default=None, help="Override slurm profile in config.")
    parser.add_argument("--allow_dirty", action="store_true", default=False,
                        help="Submit even if a tracked repository has uncommitted changes.")
    parser.add_argument("--dry_run", action="store_true", default=False)

    return parser.parse_known_args()


def load_profile(name):
    path = PROFILE_DIR / f"{name}.toml"
    if not path.exists():
        valid = ", ".join(sorted(p.stem for p in PROFILE_DIR.glob("*.toml")))
        raise FileNotFoundError(f"Profile not found: {name}. Select from list: {valid}")
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_jobs(config_path, job=None):
    with open(config_path, "rb") as f:
        jobs = tomllib.load(f).get("jobs")
    if not jobs:
        raise KeyError(f"No [jobs] table in {config_path}.")

    job_tables = {k: v for k, v in jobs.items() if isinstance(v, dict)}
    if job is not None and job not in job_tables:
        raise KeyError(f"No job '{job}' in {config_path}. Available: {', '.join(job_tables)}")

    selected = []
    for name in [job] if job else job_tables:
        spec = dict(job_tables[name])
        spec.setdefault("env", jobs.get("env"))
        if not spec["env"]:
            raise KeyError(f"No env set for job '{name}' in {config_path}.")
        selected.append((name, spec))
    return selected


def load_settings(settings_file):
    with open(settings_file) as f:
        settings = json.load(f)
    if not settings.get("archive_dir"):
        raise KeyError(f"No archive_dir set in {settings_file}.")
    if settings_file.stem not in settings.get("repositories", {}):
        raise KeyError(f"No repository '{settings_file.stem}' in {settings_file}.")
    return settings


def build_script(config_path, job, spec, profile, task_dir, repo_dir, settings_file, user_address, extra_args=()):
    slurm = {**profile, **spec.get("slurm", {})}
    script = repo_dir / spec["script"]
    if not script.exists():
        raise FileNotFoundError(f"Missing script: {script}")

    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={config_path.stem}_{job}",
        f"#SBATCH -o {task_dir}/slurm-%j.out",
        f"#SBATCH -t {slurm.get('time', '06:00:00')}",
        f"#SBATCH --nodes={slurm.get('nodes', 1)}",
        f"#SBATCH --cpus-per-task={slurm.get('cpus', 4)}",
        f"#SBATCH --mem={slurm.get('mem', '32G')}",
    ]
    lines += [f"#SBATCH {fmt.format(slurm[key])}" for key, fmt in OPTIONAL_SBATCH.items() if slurm.get(key)]
    if user_address:
        lines += [f"#SBATCH --mail-user={user_address}", f"#SBATCH --mail-type={MAIL_TYPE}"]
    lines += [
        "",
        "source ~/.bashrc",
        f"micromamba activate {spec['env']}",
        f"slurm_wf.write_metadata -j \"$SLURM_JOB_ID\" -s \"{settings_file}\" \"{task_dir}\"",
        "",
        f"cd {script.parent}",
        "",
        f"{shlex.join(['python', str(script)])} --config \"{task_dir}/config.toml\" {shlex.join(extra_args)}".rstrip(),
        "",
    ]
    return "\n".join(lines)


def get_job_files(task_dir, file_dir):
    date, job = task_dir.name.split("_", 1)
    return Path(file_dir) / f"{date}_sbatch_{job}.sbatch", Path(file_dir) / f"{date}_config_{job}.toml"


def main():
    args, extra_args = parse_args()

    config_path = Path(args.config).resolve()
    jobs = load_jobs(config_path, args.job)
    if extra_args and len(jobs) > 1:
        raise ValueError(f"Extra arguments {extra_args} need a specific job. Select one with --job.")
    settings_file = Path(args.settings).resolve()
    settings = load_settings(settings_file)
    project = settings_file.stem
    repo_dir = Path(settings["repositories"][project])
    repositories = job_repositories(settings)
    dirty = check_dirty(repositories, settings.get("untracked_files_dirty", False))
    dirty_message = None
    if dirty and not args.allow_dirty:
        dirty_message = f"Dirty repositories: {', '.join(dirty)}. Pass --allow_dirty to submit anyway."
        if not args.dry_run:
            raise RuntimeError(dirty_message)

    date = datetime.date.today().isoformat()
    run_dir = Path(settings["archive_dir"]) / config_path.parent.name / config_path.stem
    dependency = None
    with tempfile.TemporaryDirectory() as file_dir:
        sbatch_files = []
        for job, spec in jobs:
            profile = load_profile(args.slurm_profile or spec["slurm_profile"])
            task_dir = run_dir / f"{date}_{job}"
            script_text = build_script(config_path, job, spec, profile, task_dir, repo_dir, settings_file,
                                       settings.get("user_address"), extra_args)

            if args.dry_run:
                print(f"Submit {get_job_files(task_dir, '<tmp>')[0].name} into {task_dir}, dependency: {dependency}.")
                print(script_text)
                dependency = f"<{config_path.stem}_{job}>"
                continue

            sbatch_file, config_file = get_job_files(task_dir, file_dir)
            sbatch_file.write_text(script_text)
            shutil.copy(config_path, config_file)
            sbatch_files.append(str(sbatch_file))

        if sbatch_files:
            run_dir.mkdir(parents=True, exist_ok=True)
            submit_chain(sbatch_files, str(run_dir), repositories, str(settings_file), project=project)

    if dirty_message is not None:
        print(f"Warning: {dirty_message}")


if __name__ == "__main__":
    main()
