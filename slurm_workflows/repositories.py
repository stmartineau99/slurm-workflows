#!/usr/bin/python
# -- coding: utf-8 --
"""author: Martin Schilling (martin.schilling@med.uni-goettingen.de), 2025

Handling of the git repositories which are tracked with a job.
"""
import os
import subprocess


def write_repository_file(
    repositories: dict,
    output_file: str,
) -> None:
    """Write the repositories of the settings in the tab-separated format read by `repository_status_to_dict()`.

    Args:
        repositories: Dictionary mapping repository names to their local paths.
        output_file: Path of the output file.
    """
    with open(output_file, "w") as myfile:
        for name, path in repositories.items():
            myfile.write(f"{name}\t{path}\n")


def write_repository_diff(
    repo_name: str,
    repo_path: str,
    diff_dir: str,
) -> None:
    """Write the uncommitted changes of a repository.

    `git diff HEAD` goes to `<repo_name>.diff`. The untracked files which are not ignored go to
    `<repo_name>.untracked.txt`, as a list without their content. An empty output is not written.

    Args:
        repo_name: Name of the repository.
        repo_path: Path of the repository.
        diff_dir: Output directory.
    """
    commands = {
        f"{repo_name}.diff": ["git", "diff", "HEAD"],
        f"{repo_name}.untracked.txt": ["git", "ls-files", "--others", "--exclude-standard"],
    }
    for file_name, command in commands.items():
        output = subprocess.run(command, cwd=repo_path, stdout=subprocess.PIPE).stdout.decode('utf-8')
        if output:
            with open(os.path.join(diff_dir, file_name), "w") as myfile:
                myfile.write(output)


def repository_status_to_dict(
    repository_file: str,
    metadict: dict,
    diff_dir: str = None,
) -> None:
    """Add the git hash and the status of each repository to the metadata.

    Each line of the repository file holds a repository name and a path, separated by a tab. The
    status is 'clean' or 'dirty'.

    Args:
        repository_file: Path of the repository file.
        metadict: Metadata of the job.
        diff_dir: Directory for the uncommitted changes of each dirty repository, or None.
    """
    repo_list = []

    if os.path.isfile(repository_file):
        with open(repository_file, 'rt', encoding="utf8", errors='ignore') as myfile:
            for line in myfile:
                content = line.strip().split()
                if len(content) == 0:
                    continue
                if len(content) != 2:
                    raise ValueError(f"Ensure that the file containing repositories has the correct format. "
                                     f"Check the line '{line.strip()}' of {repository_file}.")

                repo_name = content[0]
                repo_path = content[1]

                if os.path.isdir(repo_path):
                    repo_version = subprocess.run(["git", "rev-parse", "HEAD"],
                                                  cwd=repo_path, stdout=subprocess.PIPE).stdout.decode('utf-8')
                    git_status_out = subprocess.run(["git", "status", "--porcelain"],
                                                    cwd=repo_path, stdout=subprocess.PIPE).stdout.decode('utf-8')
                    if len(git_status_out) == 0:
                        git_status = "clean"
                    else:
                        git_status = "dirty"
                        if diff_dir is not None:
                            write_repository_diff(repo_name, repo_path, diff_dir)

                    repo_list.append({"repo_name": repo_name,
                                      "repo_version": repo_version.strip(),
                                      "status": git_status})
                else:
                    print("Repository path " + repo_path + " could not be resolved.")

    metadict["Repositories"] = repo_list
