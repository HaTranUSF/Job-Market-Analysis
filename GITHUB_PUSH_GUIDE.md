# GitHub Push Reference Guide

This guide provides the steps to push a local folder to a GitHub repository, including how to handle common scenarios like existing remote files.

## 1. Initial Setup

Open your terminal (PowerShell or Command Prompt) and navigate to your project folder:
```powershell
cd "C:\Users\tranm\Downloads\Project"
```

### Protect Sensitive Files
Create a `.gitignore` file to ensure you don't upload sensitive data (like API keys) or temporary files:
```bash
# Create the file and add common exclusions
echo ".env" >> .gitignore
echo ".ipynb_checkpoints/" >> .gitignore
echo "__pycache__/" >> .gitignore
```

## 2. Initialize and Commit
Initialize the local Git repository and save your current progress:
```bash
git init                           # Initialize Git
git add .                          # Stage all files
git commit -m "Initial commit"      # Commit changes
git branch -M main                 # Rename branch to 'main'
```

## 3. Connect to GitHub
Link your local repository to the GitHub URL:
```bash
git remote add origin https://github.com/HaTranUSF/Job-Market-Analysis.git
```

## 4. Sync and Push
If your GitHub repository is **not empty** (e.g., it has a README or License), follow these steps:

### Option A: Repository is NOT empty (Recommended)
```bash
git pull origin main --rebase      # Sync remote changes with local
git push -u origin main            # Push local changes
```

### Option B: Repository is empty
```bash
git push -u origin main
```

---

## Daily Workflow
After you make changes to your files, follow these three steps to update GitHub:

1. **Stage changes:**
   ```bash
   git add .
   ```
2. **Commit changes:**
   ```bash
   git commit -m "Describe what you changed"
   ```
3. **Push to GitHub:**
   ```bash
   git push
   ```

## Common Troubleshooting
*   **"Rejected / non-fast-forward":** This means GitHub has files you don't have locally. Use `git pull origin main --rebase` to sync.
*   **Authentication failed:** Ensure you are logged into the GitHub CLI or that your Git credentials are saved in Windows Credential Manager.
