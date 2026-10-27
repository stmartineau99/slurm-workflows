#!/usr/bin/python
# -- coding: utf-8 --
"""Recording of the micromamba environment which a job runs in.
"""
import hashlib
import json
import os
import subprocess


def environment_to_dict(
    env_name: str,
    env_dir: str,
    metadict: dict,
) -> None:
    """Add the micromamba environment of a job to the metadata.

    A lock file of the conda packages and a file of the pip packages are written into `env_dir`, both
    named by a hash of their content. The metadata records the environment name and both file names.
    A job which finished must still be archived, so a failed command is reported and skipped.

    Args:
        env_name: Name of the micromamba environment.
        env_dir: Directory of the environment files.
        metadict: Metadata of the job.
    """
    micromamba = os.environ.get("MAMBA_EXE", "micromamba")
    try:
        result = subprocess.run([micromamba, "env", "list", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        print(f"Warning: the environment is not recorded. {micromamba} could not be run: {exc}")
        return
    env_paths = json.loads(result.stdout.decode('utf-8')).get("envs", []) if result.returncode == 0 else []
    if env_name not in [os.path.basename(path) for path in env_paths]:
        print(f"Warning: the environment is not recorded. Environment {env_name} not found.")
        return

    commands = {
        "lock": [micromamba, "env", "export", "-n", env_name, "--explicit"],
        "pip": [micromamba, "run", "-n", env_name, "python", "-m", "pip", "freeze", "--exclude-editable"],
    }

    outputs = {}
    for key, command in commands.items():
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            print(f"Warning: the environment is not recorded. {micromamba} could not be run: {exc}")
            return
        if result.returncode != 0:
            print(f"Warning: the environment is not recorded. '{' '.join(command)}' failed: "
                  f"{result.stderr.decode('utf-8').strip()}")
            return
        outputs[key] = result.stdout.decode('utf-8')

    # pip lists the packages of conda with the file URL of their build. They are part of the lock already.
    outputs["pip"] = "".join(line for line in outputs["pip"].splitlines(keepends=True) if " @ file://" not in line)

    env_hash = hashlib.sha256((outputs["lock"] + outputs["pip"]).encode('utf-8')).hexdigest()[:12]
    file_names = {"lock": f"{env_name}-{env_hash}.lock", "pip": f"{env_name}-{env_hash}.pip.txt"}

    os.makedirs(env_dir, exist_ok=True)
    for key, file_name in file_names.items():
        env_file = os.path.join(env_dir, file_name)

        # only write new environment files if the hash doesn't match an existing file.
        if not os.path.isfile(env_file):
            with open(env_file, "w") as myfile:
                myfile.write(outputs[key])

    metadict["Environment"] = {"name": env_name, **file_names}
