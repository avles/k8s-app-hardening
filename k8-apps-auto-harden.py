import os
import yaml
from github import Github
import git
import shutil  

def read_pat():
    pat = os.getenv("K8S_HARDEN_PAT")
    if not pat:
        print("Personal Access Token not set. Terminating.")
        exit(1)
    return pat

def read_projects():
    with open("projects.yaml", 'r') as stream:
        try:
            return yaml.safe_load(stream)["repos"]
        except Exception as e:
            print(f"Error reading projects.yaml: {e}")
            exit(1)

def process_yaml_files(repo_dir):
    modified_files = []
    for root, dirs, files in os.walk(repo_dir):
        for filename in files:
            if filename.endswith('.yaml'):
                filepath = os.path.join(root, filename)
                with open(filepath, 'r') as stream:
                    try:
                        yaml_data = yaml.safe_load(stream)
                    except Exception as e:
                        continue

                modified = False
                if "kind" in yaml_data and yaml_data["kind"] in ["Deployment", "StatefulSet"]:
                    template_spec = yaml_data.get("spec", {}).get("template", {}).get("spec", {})
                    for container_type in ["containers", "initContainers"]:
                        containers = template_spec.get(container_type, [])
                        for container in containers:
                            security_context = container.get("securityContext", {})
                            if "runAsNonRoot" not in security_context:
                                security_context["runAsNonRoot"] = True
                                modified = True
                            if "allowPrivilegeEscalation" not in security_context:
                                security_context["allowPrivilegeEscalation"] = False
                                modified = True
                            container["securityContext"] = security_context

                            if container.get("image", "").find("vault") != -1:
                                if "command" not in container:
                                    container["command"] = ["vault"]
                                    modified = True

                    if modified:
                        with open(filepath, 'w') as out_stream:
                            yaml.safe_dump(yaml_data, out_stream)
                        modified_files.append(filepath)

    return modified_files


def main():
    pat = read_pat()
    projects = read_projects()
    github_instance = Github(pat)
    report = {}

    for project in projects:
        url = project["url"]
        repo_name = url.split("/")[-1].replace(".git", "")
        user_name = url.split("/")[-2]

        repo_dir = f"/tmp/{repo_name}"

        # Remove existing directory if present
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
        
        git.Repo.clone_from(url, repo_dir, branch='main', env={'GIT_ASKPASS': 'echo', 'GIT_USERNAME': user_name, 'GIT_PASSWORD': pat})

        repo_git = git.Repo(repo_dir)
        
        # Pull latest changes
        repo_git.git.pull('origin', 'main')
        
        # Checkout to a new branch
        repo_git.git.checkout('-b', 'feature_k8s_hardening')

        modified_files = process_yaml_files(repo_dir)

        if modified_files:
            repo_git.git.add(all=True)
            repo_git.git.commit(m='K8s hardening applied.')
            
            # Push to remote
            try:
                repo_git.git.push('--set-upstream', 'origin', 'feature_k8s_hardening')
                report[repo_name] = "Modified"
            except Exception as e:
                report[repo_name] = f"Failed to push: {e}"
        else:
            report[repo_name] = "No modifications or not compliant"

    # Create Report
    print("=== Report ===")
    with open('report.txt', 'w') as f:
        for repo, status in report.items():
            line = f"{repo}: {status}"
            print(line)
            f.write(line + '\n')

if __name__ == "__main__":
    main()
