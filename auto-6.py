import os
import shutil
import subprocess
from pathlib import Path
from ruamel.yaml import YAML
import git

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def read_env_variable():
    PAT = os.environ.get("K8_HARDEN_PAT")
    if PAT is None:
        print("K8_HARDEN_PAT is not set.")
        exit(1)
    return PAT


def read_project_file():
    with open("projects.yaml", 'r') as f:
        project_data = yaml.load(f)
    return project_data


def clone_repo(url, PAT, source_branch):
    clone_url = url.replace("https://", f"https://{PAT}@")
    repo_name = url.split("/")[-1].replace(".git", "")
    if Path(repo_name).exists():
        shutil.rmtree(repo_name)
    repo = git.Repo.clone_from(clone_url, repo_name)
    repo.git.checkout(source_branch)
    return repo_name


def apply_switches(content, switches, api_migration_pathway):
    modified = False
    if 'kind' in content:  # Syntax was incomplete, added a colon
        if content['kind'] in ['Deployment', 'StatefulSet', 'CronJob', 'Job' 'DaemonSet']:
            containers = content.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
            for container in containers:
                security_context = container.get('securityContext', {})  # Initialize security_context

                if switches.get("vault_command", "off") == "on":
                    if "vault" in container.get("image", ""):
                        if "command" not in container:
                            container['command'] = ["vault"]
                            modified = True

                if switches.get("nonroot", "off") == "on":
                    print("Implement runAsNonRoot")
                    if security_context.get('runAsNonRoot') is None:
                        security_context['runAsNonRoot'] = True
                        modified = True

                if switches.get("previlege_escalation", "off") == "on":
                    print("Implement allowPrivilegeEscalation")
                    if security_context.get('allowPrivilegeEscalation') is None:
                        security_context['allowPrivilegeEscalation'] = False
                        modified = True

                container['securityContext'] = security_context  # Update the securityContext in the container

        if switches.get("upgrade_apis", "off") == "on":
            # Implement API version upgrade
            api_version = content.get("apiVersion", "")
            print(api_version)
            for api_path in api_migration_pathway:
                if api_version == api_path.get("from_api_version", ""):
                    content["apiVersion"] = api_path.get("to_api_version", "")
                    print(content["apiVersion"])
                    strategy = api_path.get("strategy", "")
                    if strategy == "kubectl_convert":
                        # Here you would call `kubectl convert` using subprocess or similar
                        pass
                    modified = True

    return modified

def create_branch_and_commit(repo_name, target_branch):
    repo = git.Repo(repo_name)
    repo.git.fetch('origin')
    try:
        if f'origin/{target_branch}' in repo.git.branch('-r'):
            print(f"{target_branch} branch already exists in remote for {repo_name}, skipping...")
            return False
        repo.git.checkout(b=target_branch)
    except git.exc.GitCommandError as e:
        print(f"An error occurred: {str(e)}, skipping...")
        return False
    repo.git.add(A=True)
    repo.git.commit(m='Harden Kubernetes configurations')
    repo.git.push('origin', target_branch)
    return True


def main():
    PAT = read_env_variable()
    project_data = read_project_file()
    repos = project_data.get('repos', [])
    switches = project_data.get('switches', {})
    api_migration_pathway = project_data.get('api_migration_pathway', [])
    source_branch = project_data.get('source_branch', 'main')
    target_branch = project_data.get('target_branch', 'feature_k8s_hardening')

    if Path("temp_repos").exists():
        shutil.rmtree("temp_repos")
    Path("temp_repos").mkdir()
    os.chdir("temp_repos")

    report = {
        "modified": [],
        "not_modified": [],
        "skipped": []
    }

    for repo in repos:
        url = repo['url']
        print(f"Processing {url}...")
        repo_name = clone_repo(url, PAT, source_branch)
        modified = False
        for root, _, files in os.walk(repo_name):
            for file in files:
                if file.endswith(".yaml"):
                    filepath = os.path.join(root, file)
                    with open(filepath, 'r') as f:
                        content = yaml.load(f)

                    modified = apply_switches(content, switches, api_migration_pathway)
                    if modified:
                        with open(filepath, 'w') as f:
                            yaml.dump(content, f)

        if modified:
            branch_created = create_branch_and_commit(repo_name, target_branch)
            if branch_created:
                report["modified"].append(repo_name)
            else:
                report["skipped"].append(repo_name)
        else:
            report["not_modified"].append(repo_name)

    print("Report:")
    print(f"Modified: {report['modified']}")
    print(f"Not Modified: {report['not_modified']}")
    print(f"Skipped: {report['skipped']}")
    with open("report.txt", "w") as f:
        f.write("Report:\n")
        f.write(f"Modified: {report['modified']}\n")
        f.write(f"Not Modified: {report['not_modified']}\n")
        f.write(f"Skipped: {report['skipped']}\n")


if __name__ == "__main__":
    main()
