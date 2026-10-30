import subprocess
result = subprocess.run(['/opt/homebrew/bin/yt-dlp', '--get-title', 'https://www.youtube.com/watch?v=vyUX6wQLCIM'], capture_output=True, text=True)
print('STDOUT:', result.stdout)
print('STDERR:', result.stderr[:500])
print('RC:', result.returncode)
