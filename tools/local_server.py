import http.server
import socketserver
import urllib.parse
import json
import subprocess
import os
import sys
from pathlib import Path

# Server Port
PORT = 8000
# Project Root Directory
PROJECT_DIR = Path(__file__).resolve().parent.parent

class LocalServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), *kwargs)

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        
        # Intercept local api route
        if path == "/api/etf-data" or path == "/my_website/api/etf-data":
            date_list = query.get("date")
            if not date_list:
                self.send_error(400, "Bad Request: Missing date parameter")
                return
                
            target_date = date_list[0].strip()
            history_file = PROJECT_DIR / "data" / "history" / f"etf_data_{target_date}.json"
            
            # If historical archive does not exist, run python script in background to calculate
            if not history_file.exists():
                print(f"\n[API] Archive etf_data_{target_date}.json not found. Launching calculation...")
                script_path = PROJECT_DIR / "scripts" / "quantum_etf_dingtalk.py"
                
                try:
                    res = subprocess.run(
                        [sys.executable, str(script_path), "--once", "--date", target_date, "--no-publish"],
                        cwd=str(PROJECT_DIR),
                        capture_output=True,
                        text=True,
                        encoding="utf-8"
                    )
                    
                    if res.returncode != 0:
                        print(f"[API] Script execution failed (exit code {res.returncode}):\n{res.stderr}")
                        self.send_error(500, f"Internal Server Error: Script failed with code {res.returncode}")
                        return
                        
                except Exception as e:
                    self.send_error(500, f"Internal Server Error: Failed to execute script: {e}")
                    return
            
            # Verify file generated successfully
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                    print(f"[API] Returned history data package for {target_date}")
                    return
                except Exception as e:
                    self.send_error(500, f"Internal Server Error: Failed to read data: {e}")
                    return
            else:
                self.send_error(404, f"Not Found: Failed to generate data for date {target_date}")
                return
                
        super().do_GET()

def run_server():
    os.chdir(str(PROJECT_DIR))
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), LocalServerHandler) as httpd:
        print("============================================================")
        print("  Local ETF Dev Server started successfully!")
        print(f"  Web Access URL:   http://localhost:{PORT}/etf.html")
        print(f"  History API URL:  http://localhost:{PORT}/api/etf-data?date=YYYY-MM-DD")
        print("  Note: Background calculation triggers automatically on date query.")
        print("============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    run_server()
