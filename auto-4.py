import os
import yaml
import git
import shutil
from pathlib import Path
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=2, offset=0)

def read_env_variable():
    PAT = os.environ.get("K8_HARDEN_PAT")
    if PAT is None:
        print("K8_HARDEN_PAT is not set.")
        exit(1)
    return PAT

def read_project_file():
    with open("projects.yaml", 'r') as f:
        projects = yaml.load(f)
        #projects = yaml.safe_load(f)
    return projects['repos']

def clone_repo(url, PAT):
    clone_url = url.replace("https://", f"https://{PAT}@")
    repo_name = url.split("/")[-1].replace(".git", "")
    if Path(repo_name).exists():
        # Remove existing folder
        shutil.rmtree(repo_name)
    git.Repo.clone_from(clone_url, repo_name)
    return repo_name


from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def process_yaml_files(repo_name):
    modified = False
    for root, _, files in os.walk(repo_name):
        for file in files:
            if file.endswith(".yaml"):
                file_path = os.path.join(root, file)
                modified |= process_yaml_file(file_path)
    return modified

def process_yaml_file(file_path):
    modified = False
    with open(file_path, 'r') as f:
        content = yaml.load(f)

    if content is None or not isinstance(content, dict):
        print(f"Warning: Skipping invalid or empty YAML file: {file_path}")
        return False

    if content.get('kind') not in ['Deployment', 'StatefulSet']:
        return False

    for container_type in ['initContainers', 'containers']:
        containers = content['spec']['template']['spec'].get(container_type, [])
        
        for container in containers:
            security_context = container.get('securityContext', {})

            if container.get('image', '').startswith('vault'):
                if 'command' not in container:
                    container['command'] = ["vault"]
                    modified = True

            if security_context.get('runAsNonRoot') is None:
                security_context['runAsNonRoot'] = True
                modified = True

            if security_context.get('allowPrivilegeEscalation') is None:
                security_context['allowPrivilegeEscalation'] = False
                modified = True

            container['securityContext'] = security_context

    if modified:
        with open(file_path, 'w') as f:
            yaml.dump(content, f)

    return modified


def process_yaml_files2(repo_name):
    modified = False
    for root, _, files in os.walk(repo_name):
        for file in files:
            if file.endswith(".yaml"):
                filepath = os.path.join(root, file)
                with open(filepath, 'r') as f:
                    content = yaml.safe_load(f)
                
                if 'kind' in content and content['kind'] in ['Deployment', 'StatefulSet']:
                    containers = content.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
                    init_containers = content.get('spec', {}).get('template', {}).get('spec', {}).get('initContainers', [])
                    
                    for container_list in [containers, init_containers]:
                        for container in container_list:
                            if 'securityContext' not in container:
                                container['securityContext'] = {}
                            container['securityContext']['runAsNonRoot'] = True
                            container['securityContext']['allowPrivilegeEscalation'] = False
                            if "vault" in container.get("image", ""):
                                if "command" not in container:
                                    container['command'] = ["vault"]
                                    
                    modified = True
                    with open(filepath, 'w') as f:
                        yaml.safe_dump(content, f)
    return modified

def create_branch_and_commit(repo_name):
    repo = git.Repo(repo_name)
    repo.git.fetch('origin')
    try:
        if 'origin/feature_k8s_hardening' in repo.git.branch('-r'):
            print(f"feature_k8s_hardening branch already exists in remote for {repo_name}, skipping...")
            return False
        repo.git.checkout(b='feature_k8s_hardening')
    except git.exc.GitCommandError as e:
        print(f"An error occurred: {str(e)}, skipping...")
        return False
    repo.git.add(A=True)
    repo.git.commit(m='Harden Kubernetes configurations')
    repo.git.push('origin', 'feature_k8s_hardening')
    return True

def main():
    PAT = read_env_variable()
    repos = read_project_file()

    # Create a directory for cloned repos, if it exists delete and recreate
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
        repo_name = clone_repo(url, PAT)
        modified = process_yaml_files(repo_name)
        
        if modified:
            branch_created = create_branch_and_commit(repo_name)
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
