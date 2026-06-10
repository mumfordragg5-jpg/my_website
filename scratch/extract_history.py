import os
import subprocess
import json
from pathlib import Path

def extract_git_history():
    repo_dir = Path("d:/work_doc/python_project/my_website")
    history_dir = repo_dir / "data" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    
    print("开始获取 data/etf_data.json 的 Git 提交历史...")
    
    # 运行 git log 获取提交哈希和短日期
    # --follow 可以追踪重命名或移动（此处其实不太需要，但加上更保险）
    res = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "--follow", "--format=%H %ad", "--date=short", "data/etf_data.json"],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8"
    )
    
    lines = res.stdout.strip().splitlines()
    print(f"共找到 {len(lines)} 次提交记录。")
    
    # 我们按日期分组，只保留每一天“最后提交”的那个 commit（由于 git log 是降序输出的，所以第一个遇到的日期就是当天的最后一次提交）
    seen_dates = set()
    commits_to_process = []
    
    for line in lines:
        parts = line.split()
        if len(parts) != 2:
            continue
        commit_sha, commit_date = parts
        
        # 只保留唯一日期的首次遇到记录（也就是当天的最后一次提交）
        if commit_date not in seen_dates:
            seen_dates.add(commit_date)
            commits_to_process.append((commit_sha, commit_date))
            
    print(f"去重后，共需提取 {len(commits_to_process)} 个不同交易日的数据...")
    
    # 依次提取
    success_count = 0
    for commit_sha, commit_date in commits_to_process:
        try:
            # 运行 git show 获取特定 commit 中的文件内容
            show_res = subprocess.run(
                ["git", "-C", str(repo_dir), "show", f"{commit_sha}:data/etf_data.json"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            )
            
            # 解析 json 确保其格式正确且无损坏
            data = json.loads(show_res.stdout)
            
            # 写入对应的归档文件
            output_file = history_dir / f"etf_data_{commit_date}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            print(f"  [成功] 恢复 {commit_date} 数据 -> {output_file.name}")
            success_count += 1
            
        except Exception as e:
            print(f"  [失败] 无法提取 {commit_date} (commit: {commit_sha[:8]}): {e}")
            
    print(f"\n提取完成！成功恢复 {success_count} 天的历史数据。")

if __name__ == "__main__":
    extract_git_history()
