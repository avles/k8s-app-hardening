#!/usr/bin/env python3

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



def get_containers_from_content(content):
    kind = content.get('kind', '')
    spec = content.get('spec', {})
    
    if kind in ['Deployment', 'StatefulSet', 'DaemonSet']:
        template_spec = spec.get('template', {}).get('spec', {})
    
    elif kind in ['CronJob']:
        template_spec = spec.get('jobTemplate', {}).get('spec', {}).get('template', {}).get('spec', {})
    
    elif kind in ['Job']:
        template_spec = spec.get('template', {}).get('spec', {})
    
    else:
        return []
    
    containers = template_spec.get('containers', [])
    init_containers = template_spec.get('initContainers', [])
    
    return containers + init_containers  # concatenate the lists and return


def apply_switches(all_content, switches, api_migration_pathway):
    global_modified = False
    for content in all_content:
        modified = False
        if 'kind' in content:  # Syntax was incomplete, added a colon
            if content['kind'] in ['Deployment', 'StatefulSet', 'CronJob', 'Job' 'DaemonSet']:
                containers = get_containers_from_content(content)
                print("cat")
                print(containers)
                #containers = content.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
                for container in containers:
                    security_context = container.get('securityContext', {})  # Initialize security_context

                    if switches.get("vault_command", "off") == "on":
                        if "vault" in container.get("image", ""):
                            if "command" not in container:
                                container['command'] = ["vault"]
                                modified = True

                    if switches.get("nonroot", "off") == "on":
                        print("Implement runAsNonRoot")
                        security_context['runAsNonRoot'] = True
                        modified = True

                    # New Code Block to remove runAsUser: 0
                    if switches.get("remove_rootaszero", "off") == "on":
                        print("Implement Remove Root User assigned as 0")
                        if security_context.get('runAsUser') == 0:
                            del security_context['runAsUser']
                            modified = True

                    if switches.get("previlege_escalation", "off") == "on":
                        print("Implement allowPrivilegeEscalation")
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

        # ... (snip) ... The body of the old 'apply_switches' goes here
        # ... (snip) ... Just remember to set 'modified = True' wherever you make changes
        global_modified = global_modified or modified
    return global_modified


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
    print_k8zilla()
    display_message_and_wait()

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
        repo_modified = False  # Initialize as False before processing files in the repo
        for root, _, files in os.walk(repo_name):
            for file in files:
                if file.endswith(".yaml"):
                    filepath = os.path.join(root, file)
                    all_content = []
                    with open(filepath, 'r') as f:
                        all_documents = yaml.load_all(f)
                        for doc in all_documents:
                            all_content.append(doc)

                    modified = apply_switches(all_content, switches, api_migration_pathway)
                    if modified:
                        repo_modified = True  # Set to True if any file is modified
                        with open(filepath, 'w') as f:
                            for idx, content in enumerate(all_content):
                                if idx != 0:
                                    f.write('---\n')  # Add a separator if this isn't the first document
                                yaml.dump(content, f)

        if repo_modified:  # Use repo_modified here
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

def display_message_and_wait():
    print("Welcome to k8zilla! Before you run this ensure you have performed all these steps:")
    print("1. Get a Personal Access Token from Bitbucket and set that as an Env variable K8_HARDEN_PAT")
    print("2. In projects.yaml, verify if you have added all the repos, turn on the switches, and check migration instructions")
    print("3. Check your source and target branch")
    print()
    print("If all set, type 'proceed' to begin")

    user_input = input()
    if user_input.lower() == 'proceed':
        print("Proceeding...")
    else:
        print("Operation cancelled.")
        exit(1)

def print_k8zilla():
    art = '''
  _     ___     _ _ _       
 | |   / _ \   (_) | |      
 | | _| (_) |____| | | __ _ 
 | |/ /> _ <_  / | | |/ _` |
 |   <| (_) / /| | | | (_| |
 |_|\_\\___/___|_|_|_|\__,_|
         Making K8s 
     Safer & Complaint
 '''
    print(art)                            

if __name__ == "__main__":
    main()
